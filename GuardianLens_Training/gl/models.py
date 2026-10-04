"""Signals that fit inside the generic tune / fit / predict / out-of-fold framework.

B  BehaviouralSignal  XGBoost on behavioural fields (methodology)
V  VisualSignal       logistic head on CLIP-consistency + SSCD copy-detection features (methodology)
   TfidfSignal        text baseline reference (methodology step 2)
   TabularSignal      exploratory everything-in-one gradient boosting (reference only, not fused)
T  (XLM-R) lives in xlmr.py because it needs a GPU and its own fold loop.

Every signal is fit on TRAIN rows only; predictions for unavailable inputs are NaN (fusion handles that).
"""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd
from scipy.sparse import hstack
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import StandardScaler

from .features import BehaviouralFeatures, TabularFeatures


def _text(df: pd.DataFrame) -> list[str]:
    return (df["title"].fillna("") + " . " + df["description"].fillna("")).tolist()


def _cv_score(build, params_list, X_take, y, groups, folds, seed) -> tuple[dict, list[float]]:
    """Grouped CV AUC for each candidate; returns the best params and every score."""
    skf = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    splits = list(skf.split(np.zeros(len(y)), y, groups))
    scores = []
    for params in params_list:
        aucs = []
        for tr, va in splits:
            m = build(params)
            m.fit(X_take(tr), y[tr])
            aucs.append(roc_auc_score(y[va], m.predict_proba(X_take(va))[:, 1]))
        scores.append(float(np.mean(aucs)))
    return params_list[int(np.argmax(scores))], scores


class Signal:
    name = "signal"

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.params: dict = {}
        self.tuning: list = []

    def fresh(self):
        c = copy.copy(self)
        c.model = None
        return c

    def fold_context(self, df_fit, df_eval):
        """Hook called before tuning/fitting on `df_fit` and predicting `df_eval`. Signals whose INPUTS depend on a
        reference set (V: SSCD copy detection) rebuild those inputs from `df_fit` only. Default: nothing."""


# ------------------------------------------------------------------------------------------------ B
class BehaviouralSignal(Signal):
    name = "B"
    GRID = [{"max_depth": d, "n_estimators": n, "min_child_weight": m, "learning_rate": 0.05}
            for d, n, m in ((2, 150, 3), (3, 150, 5), (3, 300, 5), (4, 200, 10))]

    def __init__(self, seed=42, features: list[str] | None = None):
        super().__init__(seed)
        self.features = features
        self.params = self.GRID[1]
        self.feats = self.model = None

    def _xgb(self, p, y):
        import xgboost as xgb
        pos = max(int(np.sum(y)), 1)
        return xgb.XGBClassifier(
            n_estimators=p["n_estimators"], max_depth=p["max_depth"], learning_rate=p["learning_rate"],
            min_child_weight=p["min_child_weight"], subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
            scale_pos_weight=(len(y) - pos) / pos,  # imbalance handling (methodology)
            tree_method="hist", eval_metric="logloss", random_state=self.seed, n_jobs=4, verbosity=0)

    def tune(self, df, y, groups, folds):
        outer = self

        class _M:
            def __init__(s, p):
                s.p = p

            def fit(s, d, yy):
                s.f = BehaviouralFeatures(outer.features).fit(d)
                s.m = outer._xgb(s.p, yy).fit(s.f.transform(d), yy)

            def predict_proba(s, d):
                return s.m.predict_proba(s.f.transform(d))

        self.params, self.tuning = _cv_score(lambda p: _M(p), self.GRID, lambda i: df.iloc[i], y, groups, folds, self.seed)
        return self

    def fit(self, df, y):
        self.feats = BehaviouralFeatures(self.features).fit(df)
        self.model = self._xgb(self.params, y).fit(self.feats.transform(df), y)
        return self

    def predict(self, df):
        return self.model.predict_proba(self.feats.transform(df))[:, 1]

    def transform(self, df):
        return self.feats.transform(df)

    def shap_values(self, df) -> pd.DataFrame:
        """TreeSHAP (XGBoost's exact `pred_contribs`): log-odds contribution of each feature per listing."""
        import xgboost as xgb
        X = self.transform(df)
        contrib = self.model.get_booster().predict(xgb.DMatrix(X), pred_contribs=True)
        out = pd.DataFrame(contrib[:, :-1], columns=X.columns, index=df.index)
        out["_base"] = contrib[:, -1]
        return out


# ------------------------------------------------------------------------------------------------ V
class VisualSignal(Signal):
    name = "V"
    GRID = [{"C": c} for c in (0.01, 0.1, 1.0, 10.0)]

    def __init__(self, builder, cols: list[str], seed=42):
        """builder(ref_df, all_df) -> per-listing V feature table whose SSCD reference corpus is `ref_df` only."""
        super().__init__(seed)
        self.builder, self.cols = builder, cols
        self.table = None
        self.params = {"C": 0.1}
        self.model = self.scaler = None

    def fold_context(self, df_fit, df_eval):
        self.table = self.builder(df_fit, pd.concat([df_fit, df_eval]))

    def _X(self, df):
        t = self.table.reindex(df["listing_id"])
        avail = t["v_available"].fillna(False).to_numpy(dtype=bool)
        X = t[self.cols].astype(float).fillna(0.0).to_numpy()
        return X, avail

    def tune(self, df, y, groups, folds):
        outer = self

        class _M:
            def __init__(s, C):
                s.C = C

            def fit(s, d, yy):
                X, a = outer._X(d)
                s.sc = StandardScaler().fit(X[a])
                s.lr = LogisticRegression(C=s.C, max_iter=3000).fit(s.sc.transform(X[a]), yy[a])

            def predict_proba(s, d):
                X, a = outer._X(d)
                p = np.full(len(X), 0.5)
                p[a] = s.lr.predict_proba(s.sc.transform(X[a]))[:, 1]
                return np.column_stack([1 - p, p])

        best, self.tuning = _cv_score(lambda p: _M(p["C"]), self.GRID, lambda i: df.iloc[i], y, groups, folds, self.seed)
        self.params = best
        return self

    def fit(self, df, y):
        X, a = self._X(df)
        self.scaler = StandardScaler().fit(X[a])
        self.model = LogisticRegression(C=self.params["C"], max_iter=3000).fit(self.scaler.transform(X[a]), y[a])
        return self

    def predict(self, df):
        X, a = self._X(df)
        p = np.full(len(X), np.nan)
        if a.any():
            p[a] = self.model.predict_proba(self.scaler.transform(X[a]))[:, 1]
        return p

    @property
    def coefficients(self) -> dict:
        return dict(zip(self.cols, self.model.coef_[0].tolist()))


# ------------------------------------------------------------------------------------- references
class TfidfSignal(Signal):
    name = "text_baseline"
    GRID = [{"C": c} for c in (0.3, 1.0, 3.0, 10.0)]

    def __init__(self, seed=42):
        super().__init__(seed)
        self.params = {"C": 1.0}
        self.word = self.char = self.model = None

    def _vec(self):
        self.word = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=30000, sublinear_tf=True, lowercase=True)
        self.char = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3, max_features=60000,
                                    sublinear_tf=True, lowercase=True)

    def _X(self, texts, fit=False):
        if fit:
            self._vec()
            return hstack([self.word.fit_transform(texts), self.char.fit_transform(texts)]).tocsr()
        return hstack([self.word.transform(texts), self.char.transform(texts)]).tocsr()

    def tune(self, df, y, groups, folds):
        texts = np.array(_text(df), dtype=object)
        outer = self

        class _M:
            def __init__(s, C):
                s.C, s.o = C, TfidfSignal(outer.seed)

            def fit(s, t, yy):
                s.lr = LogisticRegression(C=s.C, max_iter=3000).fit(s.o._X(list(t), fit=True), yy)

            def predict_proba(s, t):
                return s.lr.predict_proba(s.o._X(list(t)))

        best, self.tuning = _cv_score(lambda p: _M(p["C"]), self.GRID, lambda i: texts[i], y, groups, folds, self.seed)
        self.params = best
        return self

    def fit(self, df, y):
        X = self._X(_text(df), fit=True)
        self.model = LogisticRegression(C=self.params["C"], max_iter=3000).fit(X, y)
        return self

    def predict(self, df):
        return self.model.predict_proba(self._X(_text(df)))[:, 1]

    def top_terms(self, k: int = 15) -> dict:
        names = np.array(list(self.word.get_feature_names_out()) + list(self.char.get_feature_names_out()))
        order = np.argsort(self.model.coef_[0])
        return {"risky": names[order[::-1][:k]].tolist(), "legitimate": names[order[:k]].tolist()}


class TabularSignal(Signal):
    """Exploratory: listing + seller + text cues + image metadata in one gradient-boosting model."""
    name = "tabular_ext"
    GRID = [{"max_depth": d, "max_iter": n, "learning_rate": 0.05} for d, n in ((2, 150), (3, 150), (3, 300), (4, 200))]

    def __init__(self, seed=42, use_platform=True, image_meta=None, parity=False):
        super().__init__(seed)
        self.use_platform, self.image_meta, self.parity = use_platform, image_meta, parity
        self.params = self.GRID[1]
        self.feats = self.model = None

    def _gb(self, params, mask):
        return HistGradientBoostingClassifier(
            max_depth=params["max_depth"], max_iter=params["max_iter"], learning_rate=params["learning_rate"],
            min_samples_leaf=20, l2_regularization=1.0, categorical_features=mask, random_state=self.seed)

    def tune(self, df, y, groups, folds):
        outer = self

        class _M:
            def __init__(s, p):
                s.p = p

            def fit(s, d, yy):
                s.f = TabularFeatures(outer.use_platform, outer.image_meta, outer.parity).fit(d)
                s.m = outer._gb(s.p, s.f.categorical_mask_).fit(s.f.transform(d), yy)

            def predict_proba(s, d):
                return s.m.predict_proba(s.f.transform(d))

        self.params, self.tuning = _cv_score(lambda p: _M(p), self.GRID, lambda i: df.iloc[i], y, groups, folds, self.seed)
        return self

    def fit(self, df, y):
        self.feats = TabularFeatures(self.use_platform, self.image_meta, self.parity).fit(df)
        self.model = self._gb(self.params, self.feats.categorical_mask_).fit(self.feats.transform(df), y)
        return self

    def predict(self, df):
        return self.model.predict_proba(self.feats.transform(df))[:, 1]

    def transform(self, df):
        return self.feats.transform(df)


def out_of_fold(signal: Signal, df, y, groups, folds: int, seed: int, tune_folds: int | None = None):
    """Score for every train row from a model that never saw that row's duplicate/repost group.

    Returns (oof, fold_id). When `tune_folds` is given, hyperparameters are re-selected INSIDE each outer training
    partition (nested), so the held-out fold's labels never influence parameter choice. `fold_context` lets signals
    with reference-based inputs (V) rebuild them from the fold's training rows only.
    """
    oof = np.full(len(y), np.nan)
    fold_id = np.full(len(y), -1)
    for k, (tr, va) in enumerate(fold_indices(y, groups, folds, seed)):
        s = signal.fresh()
        s.fold_context(df.iloc[tr], df.iloc[va])
        if tune_folds:
            s.tune(df.iloc[tr], y[tr], groups[tr], tune_folds)
        s.fit(df.iloc[tr], y[tr])
        oof[va] = s.predict(df.iloc[va])
        fold_id[va] = k
    return oof, fold_id


def fold_indices(y, groups, folds: int, seed: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """The one canonical fold assignment shared by every signal (so OOF scores are comparable)."""
    skf = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=seed)
    return list(skf.split(np.zeros(len(y)), y, groups))


# ------------------------------------------------------------------------------------ T (cues)
class TextCueSignal(Signal):
    """Methodology v2 replacement for the failed XLM-R in the T slot (CPU only).

    TF-IDF (word + char) plus hand-crafted text cues (contact / payment / urgency / refund wording, URLs, phone
    numbers, length and capitalisation statistics) in ONE logistic regression. Text only: no price, seller or
    image information, so it stays a pure textual signal.
    """
    name = "T"
    GRID = [{"C": c, "w": w} for c in (0.1, 0.3, 1.0) for w in (0.5, 1.0)]

    def __init__(self, seed=42):
        super().__init__(seed)
        self.params = {"C": 0.3, "w": 1.0}
        self.word = self.char = self.scaler = self.model = None

    @staticmethod
    def _cues(df: pd.DataFrame) -> np.ndarray:
        from .features import text_cues
        rows = [text_cues(t, d) for t, d in zip(df["title"].fillna(""), df["description"].fillna(""))]
        return np.log1p(np.clip(pd.DataFrame(rows).to_numpy(dtype=float), 0, None))

    def _X(self, df, fit=False):
        from scipy.sparse import csr_matrix
        texts = _text(df)
        cues = self._cues(df)
        if fit:
            self.word = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=30000, sublinear_tf=True)
            self.char = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3, max_features=60000, sublinear_tf=True)
            self.scaler = StandardScaler().fit(cues)
            W, Ch = self.word.fit_transform(texts), self.char.fit_transform(texts)
        else:
            W, Ch = self.word.transform(texts), self.char.transform(texts)
        return hstack([W, Ch, csr_matrix(self.scaler.transform(cues) * self.params["w"])]).tocsr()

    def tune(self, df, y, groups, folds):
        outer = self

        class _M:
            def __init__(s, p):
                s.o = TextCueSignal(outer.seed)
                s.o.params = p

            def fit(s, d, yy):
                s.o.fit(d, yy)

            def predict_proba(s, d):
                p = s.o.predict(d)
                return np.column_stack([1 - p, p])

        self.params, self.tuning = _cv_score(lambda p: _M(p), self.GRID, lambda i: df.iloc[i], y, groups, folds, self.seed)
        return self

    def fit(self, df, y):
        X = self._X(df, fit=True)
        self.model = LogisticRegression(C=self.params["C"], max_iter=3000).fit(X, y)
        return self

    def predict(self, df):
        p = self.model.predict_proba(self._X(df))[:, 1]
        empty = ((df["title"].fillna("").str.strip() == "") & (df["description"].fillna("").str.strip() == "")).to_numpy()
        p[empty] = np.nan
        return p

    def top_cue_effects(self) -> dict:
        """Coefficients of the hand-crafted cues (standardised, so comparable)."""
        from .features import text_cues
        names = list(text_cues("", "").keys())
        coef = self.model.coef_[0][-len(names):] * 1.0
        return dict(sorted(zip(names, coef.tolist()), key=lambda t: -abs(t[1])))
