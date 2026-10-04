import json

import numpy as np
import pandas as pd
import pytest

from gl import data as D
from gl import features, fusion, metrics
from gl import pipeline as P


def test_verify_ok(workspace):
    cfg, _ = workspace
    assert D.verify(cfg)["ok"]


def test_verify_detects_group_leakage(workspace):
    cfg, tmp = workspace
    va = pd.read_csv(tmp / "splits" / "validation.csv")
    tr = pd.read_csv(tmp / "splits" / "train.csv")
    va.loc[0, "group_id"] = tr.loc[0, "group_id"]
    va.to_csv(tmp / "splits" / "validation.csv", index=False)
    rep = D.verify(cfg)
    assert not rep["ok"] and any("shared groups" in p for p in rep["problems"])


def test_verify_detects_modified_split(workspace):
    cfg, tmp = workspace
    te = pd.read_csv(tmp / "splits" / "test.csv")
    te.loc[0, "price"] += 1
    te.to_csv(tmp / "splits" / "test.csv", index=False)
    assert any("hash differs" in p for p in D.verify(cfg)["problems"])


def test_behavioural_features_only_the_methodology_fields(workspace):
    cfg, _ = workspace
    tr = D.load_split(cfg, "train")
    cols = set(features.BehaviouralFeatures().fit(tr).columns_)
    assert {"price", "price_ratio_category", "account_age_days", "account_age_days_missing", "seller_rating"} <= cols
    forbidden = {"target", "final_label", "annotation_readiness", "image_count", "platform", "title_len", "group_id"}
    assert not forbidden & cols


def test_category_ratio_is_fit_on_training_rows_only(workspace):
    cfg, _ = workspace
    tr = D.load_split(cfg, "train")
    f = features.BehaviouralFeatures().fit(tr)
    other = tr.copy()
    other["price"] = other["price"] * 1000  # validation-like shift must not change the fitted medians
    before = f.cat_median.copy()
    f.transform(other)
    pd.testing.assert_series_equal(before, f.cat_median)


def test_pick_threshold_and_counts():
    y = np.array([0, 0, 0, 1, 1, 1])
    p = np.array([0.1, 0.2, 0.6, 0.4, 0.7, 0.9])
    r = metrics.at_threshold(y, p, metrics.pick_threshold(y, p, "max_f1"))
    assert r["tp"] + r["fp"] + r["tn"] + r["fn"] == 6
    assert metrics.at_threshold(y, p, metrics.pick_threshold(y, p, "recall_target", 1.0))["recall"] == 1.0


def test_bootstraps_bracket_point_and_ignore_nan():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 200)
    p = y * 0.3 + rng.random(200)
    g = np.repeat(np.arange(100), 2)
    p_nan = p.copy()
    p_nan[:10] = np.nan
    ci = metrics.group_bootstrap(y, p_nan, g, lambda a, b: metrics.ranking(a, b)["roc_auc"], 200)
    assert ci["lo"] <= ci["point"] <= ci["hi"]
    d = metrics.paired_bootstrap_diff(y, p, p * 0.5 + rng.random(200) * 0.5, g, lambda a, b: metrics.ranking(a, b)["roc_auc"], 200)
    assert d["lo"] <= d["point"] <= d["hi"] and 0 <= d["p_better"] <= 1


def test_all_seven_configurations():
    cfgs = fusion.all_configs(["V", "T", "B"])
    assert [fusion.config_name(c) for c in cfgs] == ["V", "T", "B", "V+T", "V+B", "T+B", "V+T+B"]
    assert [fusion.config_name(c) for c in fusion.all_configs(["B"])] == ["B"]


def test_fusion_availability_and_bands():
    rng = np.random.default_rng(0)
    n = 400
    y = (rng.random(n) < 0.3).astype(int)
    g = np.arange(n)
    pb = np.clip(0.3 + 0.3 * y + rng.normal(0, 0.15, n), 0.01, 0.99)
    pv = np.clip(0.3 + 0.1 * y + rng.normal(0, 0.2, n), 0.01, 0.99)
    pv[:40] = np.nan  # V unavailable for some listings
    fm = fusion.FusionModel(["V", "B"], [0.1, 1.0], folds=3).fit({"V": pv, "B": pb}, y, g)
    p = fm.predict({"V": pv, "B": pb})
    assert np.isfinite(p).all() and p.min() >= 0 and p.max() <= 1
    # a listing with no V signal still gets a score
    assert np.isfinite(fm.predict({"V": np.full(5, np.nan), "B": pb[:5]})).all()
    bands = fusion.fit_bands(y, p, 0.9, 0.6)
    assert bands["low_moderate"] < bands["moderate_high"]
    tab = fusion.band_table(y, p, bands)
    assert sum(r["n"] for r in tab) == n


def test_pipeline_fast_signals_final_ledger_predict(workspace):
    """B + text baseline + exploratory + fusion + report, then the sealed test once, then predict."""
    cfg, tmp = workspace
    run = P.run_all(cfg, "t", None, with_t=False)
    for f in ("report.html", "REPORT.md", "validation_metrics.json", "val_predictions.csv", "oof_predictions.csv",
              "fusion.joblib", "explanations_sample.md", "signals/B.npz"):
        assert (run / f).exists(), f
    for f in ("roc", "precision_recall", "model_comparison", "config_comparison", "score_distributions", "calibration_compare",
              "band_chart", "threshold_sweep_fusion", "confusion_flag_moderate_or_high", "group_performance", "shap_summary",
              "dataset_overview", "stacker_weights"):
        assert (run / "figures" / f"{f}.png").exists(), f
    assert not (run / "test_metrics.json").exists()  # training never touches the test set
    assert json.loads((run / "run.json").read_text())["test_used"] is False

    P.final_test(cfg, run)
    assert (run / "test_metrics.json").exists() and (run / "figures" / "roc_test.png").exists()
    ledger = json.loads((tmp / "evaluations" / "ledger.json").read_text())["test_evaluations"]
    assert ledger[0]["run"] == run.name
    with pytest.raises(SystemExit):
        P.final_test(cfg, run)  # a second look at the test set is refused

    out = P.predict_file(cfg, run, tmp / "splits" / "validation.csv", tmp / "scored.csv")
    assert {"risk_score_0_100", "band"} <= set(out.columns) and out["band"].isin(["Low", "Moderate", "High"]).all()


def test_resume_skips_finished_signals(workspace):
    cfg, _ = workspace
    run = P.run_all(cfg, "t", None, with_t=False)
    t0 = json.loads((run / "run.json").read_text())["signals_done"]["B"]["seconds"]
    P.run_all(cfg, "t", run.name, with_t=False)
    assert json.loads((run / "run.json").read_text())["signals_done"]["B"]["seconds"] == t0


def test_text_cue_T_signal_end_to_end(workspace):
    """Methodology v2: the T slot filled by TF-IDF + text cues (CPU only), through fusion, sealed test and predict."""
    cfg, tmp = workspace
    cfg["signals"]["textual"].update(enabled=True, impl="cues")
    run = P.run_all(cfg, "cues", None, with_t=True)
    assert (run / "signals" / "T.npz").exists() and (run / "models" / "T.joblib").exists()
    assert not (run / "xlmr").exists()
    fj = json.loads((run / "fusion.json").read_text())
    assert {"T", "B", "T+B"} <= set(fj["configs"])
    diag = json.loads((run / "train_diagnostics.json").read_text())
    assert "cue_effects" in diag["T"]
    P.final_test(cfg, run)
    assert "T" in json.loads((run / "test_metrics.json").read_text())["models"]
    out = P.predict_file(cfg, run, tmp / "splits" / "validation.csv", tmp / "scored.csv")
    assert "p_T" in out.columns and out["band"].isin(["Low", "Moderate", "High"]).all()


# ------------------------------------------------------------------------------ audit fixes
def test_sealed_test_labels_are_never_read_outside_final(workspace, monkeypatch):
    """verify() and the whole training/report path read the test split without labels; only final_test may read them."""
    cfg, _ = workspace
    reads = []
    real = pd.read_csv

    def spy(path_, *a, **k):
        if str(path_).endswith("test.csv"):
            reads.append(k.get("usecols"))
        return real(path_, *a, **k)

    monkeypatch.setattr(D.pd, "read_csv", spy)
    assert D.verify(cfg)["ok"]
    run = P.run_all(cfg, "seal", None, with_t=False)
    assert reads and all(u is not None and "target" not in u for u in reads), reads
    assert not (run / "test_metrics.json").exists()
    reads.clear()
    P.final_test(cfg, run)            # the one place allowed to read the full test split
    assert any(u is None for u in reads)


def test_manifest_row_counts_are_enforced(workspace):
    cfg, tmp = workspace
    man = json.loads((tmp / "splits" / "split_manifest.json").read_text())
    man["counts"]["train"]["rows"] += 1
    (tmp / "splits" / "split_manifest.json").write_text(json.dumps(man))
    assert any("row count" in p for p in D.verify(cfg)["problems"])


def test_parity_features_use_only_app_available_inputs(workspace):
    cfg, _ = workspace
    tr = D.load_split(cfg, "train")
    full = set(features.TabularFeatures().fit(tr).columns_)
    par = set(features.TabularFeatures(parity=True).fit(tr).columns_)
    offline = {"condition", "image_count", "reused_image_indicator", "possible_duplicate", "redacted_pii_count"}
    assert offline <= full and not offline & par
    assert "phash_reuse" not in full | par


def test_image_meta_is_measured_from_files_for_new_listings(workspace):
    """No frozen listing-ID join: an unseen listing gets real measurements instead of blanks, capped at 3 photos."""
    cfg, tmp = workspace
    va = D.load_split(cfg, "validation").head(3)
    empty = pd.DataFrame(columns=["listing_id", *features.META_COLS])
    im = features.image_meta_for(cfg, va, empty)
    assert im.index.tolist() == va["listing_id"].tolist()
    assert (im["img_meta_count"] >= 1).all() and (im["img_meta_count"] <= 3).all()
    assert im[["img_min_side", "img_mean_side", "img_mean_kb"]].notna().all().all()
    assert features.image_meta_from_files([tmp / "imgs" / va["primary_image_path"].iloc[0]])["img_mean_side"] == 64.0


def test_nested_tuning_selects_parameters_inside_each_outer_fold(workspace):
    from gl.models import Signal, out_of_fold

    class Spy(Signal):
        name = "spy"

        def __init__(self):
            super().__init__(0)
            self.tuned_on, self.fitted_on = [], []

        def tune(self, df, y, groups, folds):
            self.tuned_on.append(set(df["listing_id"]))
            return self

        def fit(self, df, y):
            self.fitted_on.append(set(df["listing_id"]))
            return self

        def predict(self, df):
            return np.full(len(df), 0.5)

    cfg, _ = workspace
    tr = D.load_split(cfg, "train")
    spy = Spy()
    shared_t, shared_f = [], []
    spy.fresh = lambda: _Child(spy, shared_t, shared_f)

    class _Child(Spy):
        def __init__(self, parent, t, f):
            Signal.__init__(self, 0)
            self.tuned_on, self.fitted_on = t, f

    oof, fold_id = out_of_fold(spy, tr, D.labels(cfg, tr), D.groups(cfg, tr), 3, 42, tune_folds=2)
    assert len(shared_t) == 3 == len(shared_f)
    for t, f in zip(shared_t, shared_f):
        assert t == f and len(t) < len(tr)     # tuned on exactly the outer-training rows, never on the whole train
    assert set(fold_id.tolist()) == {0, 1, 2} and np.isfinite(oof).all()


def test_stale_signal_artifacts_are_refused_on_resume(workspace):
    cfg, _ = workspace
    run = P.new_run(cfg, "stale")
    P.train_signal(cfg, run, "B")
    z = np.load(run / "signals" / "B.npz")
    assert {"fp", "fold_id", "oof_ids", "val_ids"} <= set(z.files)
    assert (z["fold_id"] >= 0).all() and len(z["oof_ids"]) == len(z["oof"])
    cfg["signals"]["behavioural"]["features"] = ["price", "price_ratio_category"]    # config changed after training
    with pytest.raises(SystemExit):
        P.train_signal(cfg, run, "B")
    P.train_signal(cfg, run, "B", force=True)                                         # explicit retrain is allowed


def test_reports_label_calibrated_single_signal_configs_distinctly():
    from gl.plots import name
    assert name("T") == "T Textual" and name("cfg_T") != name("T") and "calibrated" in name("cfg_T")
