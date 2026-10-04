"""Methodology steps 5-6: out-of-fold logistic-regression fusion, sigmoid calibration, Low/Moderate/High bands.

* Inputs are the out-of-fold probabilities of V, T and B plus an "available" indicator per signal
  (a missing signal contributes logit 0 and indicator 0, so the fusion degrades gracefully).
* Calibration is a sigmoid (Platt) fitted on the OUT-OF-FOLD stacker scores of the TRAIN rows only, so the
  validation split remains untouched evidence for the claimed quality.
* Bands are fixed on validation (see config `bands`).
* All seven configurations V, T, B, V+T, V+B, T+B, V+T+B are fit on the same rows with the same procedure.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict

from . import metrics

SIGNAL_KEYS = ["V", "T", "B"]


def config_name(keys) -> str:
    return "+".join(keys)


def all_configs(available: list[str]) -> list[list[str]]:
    """Every non-empty subset of the available signals, in the methodology's order (singles, pairs, triple)."""
    keys = [k for k in SIGNAL_KEYS if k in available]
    return [list(c) for r in range(1, len(keys) + 1) for c in combinations(keys, r)]


def logit(p, eps: float = 1e-4):
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    return np.log(p / (1 - p))


def design(P: dict, keys: list[str]) -> np.ndarray:
    cols = []
    for k in keys:
        p = np.asarray(P[k], float)
        ok = ~np.isnan(p)
        z = np.zeros(len(p))
        z[ok] = logit(p[ok])
        cols += [z, ok.astype(float)]
    return np.column_stack(cols)


def sigmoid(z):
    return 1 / (1 + np.exp(-np.asarray(z, float)))


class FusionModel:
    def __init__(self, keys: list[str], c_grid, folds: int = 5, seed: int = 42):
        self.keys, self.c_grid, self.folds, self.seed = keys, list(c_grid), folds, seed
        self.stacker = self.calibrator = None

    def fit(self, P_oof: dict, y, groups):
        X = design(P_oof, self.keys)
        splits = list(StratifiedGroupKFold(self.folds, shuffle=True, random_state=self.seed).split(X, y, groups))
        self.stacker = LogisticRegressionCV(Cs=self.c_grid, cv=splits, scoring="roc_auc", max_iter=3000).fit(X, y)
        # sigmoid calibration on out-of-fold stacker scores (train rows only)
        c = float(self.stacker.C_[0])
        z_oof = cross_val_predict(LogisticRegression(C=c, max_iter=3000), X, y, cv=splits, method="decision_function")
        self.calibrator = LogisticRegression(C=1e6, max_iter=1000).fit(z_oof.reshape(-1, 1), y)
        self.z_oof = z_oof
        return self

    def raw_score(self, P: dict) -> np.ndarray:
        """Uncalibrated stacker probability."""
        return sigmoid(self.stacker.decision_function(design(P, self.keys)))

    def predict(self, P: dict) -> np.ndarray:
        """Calibrated probability."""
        z = self.stacker.decision_function(design(P, self.keys))
        return self.calibrator.predict_proba(z.reshape(-1, 1))[:, 1]

    @property
    def weights(self) -> dict:
        coef = self.stacker.coef_[0]
        return {k: float(coef[2 * i]) for i, k in enumerate(self.keys)}

    @property
    def availability_weights(self) -> dict:
        coef = self.stacker.coef_[0]
        return {k: float(coef[2 * i + 1]) for i, k in enumerate(self.keys)}


def fit_bands(y_val, p_val, low_max_recall: float, high_min_precision: float) -> dict:
    """Low/Moderate boundary keeps recall >= low_max_recall; Moderate/High boundary is the lowest threshold with
    precision >= high_min_precision. Chosen on VALIDATION only."""
    y_val, p_val = np.asarray(y_val), np.asarray(p_val)
    t_low = metrics.pick_threshold(y_val, p_val, "recall_target", low_max_recall)
    cands = np.unique(p_val[p_val > t_low])
    t_high = None
    for t in cands:
        if metrics.at_threshold(y_val, p_val, t)["precision"] >= high_min_precision:
            t_high = float(t)
            break
    if t_high is None:  # fallback: max-F1 point if it lies above t_low, else the midpoint of the remaining range
        t_f1 = metrics.pick_threshold(y_val, p_val, "max_f1")
        t_high = t_f1 if t_f1 > t_low else float((t_low + p_val.max()) / 2)
    return {"low_moderate": float(t_low), "moderate_high": float(t_high)}


def assign_band(p, bands: dict) -> np.ndarray:
    p = np.asarray(p, float)
    return np.where(p >= bands["moderate_high"], "High", np.where(p >= bands["low_moderate"], "Moderate", "Low"))


def band_table(y, p, bands: dict) -> list[dict]:
    y = np.asarray(y)
    b = assign_band(p, bands)
    rows = []
    for name in ("Low", "Moderate", "High"):
        m = b == name
        rows.append({"band": name, "n": int(m.sum()), "risky": int(y[m].sum()),
                     "risky_rate": float(y[m].mean()) if m.any() else float("nan"),
                     "share_of_listings": float(m.mean()), "share_of_risky_caught": float(y[m].sum() / max(y.sum(), 1))})
    return rows
