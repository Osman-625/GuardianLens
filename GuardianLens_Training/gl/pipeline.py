"""Pipeline: new-run -> signals (B, V, T + references) -> fuse (OOF fusion, calibration, bands) -> report -> sealed final test.

Run layout (runs/<id>/):
  signals/<KEY>.npz      out-of-fold scores on train + scores on validation, per signal
  models/<KEY>.joblib    model fitted on all of train (V stores only the head; features are rebuilt from the cache)
  xlmr/fold<k>/          the five XLM-R fold models (T)
  fusion.joblib          the seven fusion configurations, calibrators, thresholds and bands
  val_predictions.csv, validation_metrics.json, figures/, report.html, REPORT.md, explanations_sample.md
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform as _platform
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from . import data as D
from . import features as F
from . import fusion, metrics, plots, plots_ext, visual
from .config import path
from .models import (BehaviouralSignal, TabularSignal, TextCueSignal, TfidfSignal, VisualSignal, fold_indices,
                     out_of_fold)

CORE = ["V", "T", "B"]
REFS = ["text_baseline", "tabular_ext"]
META_COLS = ["listing_id", "target", "group_id", "platform", "category", "language"]


def _log(msg: str):
    print(msg, flush=True)


def _versions() -> dict:
    import sklearn
    v = {"python": _platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
         "scikit-learn": sklearn.__version__}
    for mod in ("xgboost", "torch", "transformers"):
        try:
            v[mod] = __import__(mod).__version__
        except Exception:
            pass
    return v


# ------------------------------------------------------------------------------------------- runs
def runs_dir(cfg: dict) -> Path:
    return path(cfg, "runs_dir")


def resolve_run(cfg: dict, run: str | None) -> Path:
    if not run or run == "latest":
        marker = runs_dir(cfg) / "LATEST"
        if not marker.exists():
            raise SystemExit("No runs yet. Run: python -m gl all")
        return runs_dir(cfg) / marker.read_text().strip()
    p = Path(run)
    return p if p.is_absolute() else runs_dir(cfg) / run


def new_run(cfg: dict, tag: str = "run") -> Path:
    rep = D.verify(cfg)
    if not rep["ok"]:
        raise SystemExit("Data integrity check failed:\n  - " + "\n  - ".join(rep["problems"]))
    run_dir = runs_dir(cfg) / f"{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_{tag}"
    (run_dir / "figures").mkdir(parents=True)
    (run_dir / "signals").mkdir()
    (run_dir / "models").mkdir()
    cfg_out = {k: v for k, v in cfg.items() if not k.startswith("_")}
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": run_dir.name, "created": dt.datetime.now().isoformat(timespec="seconds"), "config": cfg_out,
        "versions": _versions(), "data": rep, "test_used": False,
        "split_hashes": json.loads((path(cfg, "splits_dir") / "split_manifest.json").read_text())["files"],
        "signals_done": {}}, indent=2), encoding="utf-8")
    (runs_dir(cfg) / "LATEST").write_text(run_dir.name)
    _log(f"new run {run_dir.name}  (data ok: {rep['splits']})")
    return run_dir


def _meta(run_dir: Path) -> dict:
    return json.loads((run_dir / "run.json").read_text())


def _save_meta(run_dir: Path, meta: dict):
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _diag(run_dir: Path) -> dict:
    p = run_dir / "train_diagnostics.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _trval(cfg: dict):
    tr, va = D.load_split(cfg, "train"), D.load_split(cfg, "validation")
    return tr, va, D.labels(cfg, tr), D.labels(cfg, va), D.groups(cfg, tr)


def _auc(y, p):
    ok = ~np.isnan(p)
    return float(roc_auc_score(np.asarray(y)[ok], np.asarray(p)[ok])) if ok.sum() > 10 and len(set(np.asarray(y)[ok])) > 1 else float("nan")


def available_signals(run_dir: Path) -> list[str]:
    return [k for k in CORE + REFS if (run_dir / "signals" / f"{k}.npz").exists()]


# ---------------------------------------------------------------------------------------- signals
CODE_FILES = ("data.py", "features.py", "models.py", "visual.py", "xlmr.py", "fusion.py")


def fingerprint(cfg: dict, key: str) -> str:
    """Identity of everything that determines a signal's result: its config, the CV settings, the frozen split hashes and
    the modelling code. Stored with each signal and checked on resume, so a stale artifact is never silently reused."""
    sec = {"B": ("signals", "behavioural"), "V": ("signals", "visual"), "T": ("signals", "textual"),
           "text_baseline": ("references", "text_baseline"), "tabular_ext": ("references", "exploratory_tabular")}[key]
    part = {k: v for k, v in cfg[sec[0]][sec[1]].items() if k != "enabled"}
    h = hashlib.sha256()
    h.update(json.dumps({"key": key, "cfg": part, "seed": cfg["seed"], "cv": cfg["cv"]}, sort_keys=True, default=str).encode())
    h.update(json.dumps(json.loads((path(cfg, "splits_dir") / "split_manifest.json").read_text())["files"], sort_keys=True).encode())
    root = Path(__file__).parent
    for f in CODE_FILES:
        h.update((root / f).read_bytes())
    return h.hexdigest()[:16]


def _visual_builder(cfg: dict, store: dict, meta_table: pd.DataFrame):
    """Returns (builder, cols). builder(ref_df, df) builds the V feature table with the SSCD reference corpus = ref_df ONLY.
    Image measurements (optional) come from the first 3 photos, or are measured from the image files for new listings."""
    vc = cfg["signals"]["visual"]
    cols = list(visual.FEATURES) + (list(visual.META_FEATURES) if vc.get("include_image_metadata") else [])

    def build(ref: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
        table = visual.build_features(cfg, store, ref, df)
        if vc.get("include_image_metadata"):
            im = F.image_meta_for(cfg, df, meta_table)
            for c in visual.META_FEATURES:
                table[c] = im[c].reindex(table.index)
        return table

    return build, cols


def train_signal(cfg: dict, run_dir: Path, key: str, force: bool = False) -> dict:
    out = run_dir / "signals" / f"{key}.npz"
    fp = fingerprint(cfg, key)
    if out.exists() and not force:
        z = np.load(out)
        old = str(z["fp"]) if "fp" in z.files else None
        if old is not None and old != fp:
            raise SystemExit(f"[{key}] this run's saved signal was trained with a different config/code/split (fingerprint "
                             f"{old} vs {fp}). Start a new run, or pass --force to retrain it.")
        _log(f"[{key}] already trained in this run, skipping (use --force to redo)")
        return {}
    t0 = time.time()
    tr, va, ytr, yva, gtr = _trval(cfg)
    seed, folds, tf = cfg["seed"], cfg["cv"]["folds"], cfg["cv"]["tune_folds"]
    nested = cfg["cv"].get("nested_tuning", True)
    info: dict = {}
    _log(f"[{key}] training ...")

    t_impl = cfg["signals"]["textual"].get("impl", "xlmr")
    if key == "T" and t_impl == "xlmr":
        from . import xlmr
        r = xlmr.train_signal(cfg, run_dir, tr, va, ytr, gtr, yva, _log, fp=fp)
        oof, val = r["oof"], r["val"]
        fold_id = np.full(len(ytr), -1)
        for k, (_, vai) in enumerate(fold_indices(ytr, gtr, folds, seed)):
            fold_id[vai] = k
        info = {"history_file": "xlmr_history.json"}
    else:
        if key == "B":
            s = BehaviouralSignal(seed, cfg["signals"]["behavioural"].get("features"))
        elif key == "V":
            store = visual.extract(cfg, pd.concat([tr, va]), _log)
            builder, cols = _visual_builder(cfg, store, F.image_metadata(cfg))
            s = VisualSignal(builder, cols, seed)
        elif key == "T":  # impl == "cues": methodology v2, CPU-only text signal
            s = TextCueSignal(seed)
        elif key == "text_baseline":
            s = TfidfSignal(seed)
        elif key == "tabular_ext":
            parity = cfg["references"]["exploratory_tabular"].get("variant", "parity") == "parity"
            s = TabularSignal(seed, True, F.image_metadata(cfg), parity)
            info["variant"] = "parity" if parity else "full"
        else:
            raise SystemExit(f"unknown signal {key!r}")
        if nested:   # hyperparameters re-selected inside every outer training partition
            _log(f"[{key}] nested out-of-fold predictions ({folds} folds, tuning inside each fold) ...")
            oof, fold_id = out_of_fold(s, tr, ytr, gtr, folds, seed, tf)
            s.fold_context(tr, va)
            s.tune(tr, ytr, gtr, tf)       # final hyperparameters from ALL of train, used for the validation/test model
        else:
            s.fold_context(tr, va)
            s.tune(tr, ytr, gtr, tf)
            _log(f"[{key}] best params {s.params}; out-of-fold predictions ({folds} folds) ...")
            oof, fold_id = out_of_fold(s, tr, ytr, gtr, folds, seed)
        s.fit(tr, ytr)
        val = s.predict(va)
        info.update({"params": s.params, "grid_cv_auc": s.tuning, "nested_tuning": bool(nested)})
        if key == "V":
            info["coefficients"] = s.coefficients
            s.table.to_csv(run_dir / "visual_features_trainval.csv")
            tab, bld, s.table, s.builder = s.table, s.builder, None, None  # rebuilt from the embedding cache at test time
            joblib.dump(s, run_dir / "models" / f"{key}.joblib")
            s.table, s.builder = tab, bld
        else:
            joblib.dump(s, run_dir / "models" / f"{key}.joblib")
        if key == "text_baseline":
            info["top_terms"] = s.top_terms()
        if key == "T":
            info["cue_effects"] = s.top_cue_effects()

    np.savez(out, oof=oof, val=val, fp=fp, fold_id=fold_id, oof_ids=tr["listing_id"].to_numpy(str),
             val_ids=va["listing_id"].to_numpy(str))
    meta = _meta(run_dir)
    meta["signals_done"][key] = {"oof_auc": _auc(ytr, oof), "val_auc": _auc(yva, val), "seconds": round(time.time() - t0, 1),
                                 "fingerprint": fp}
    _save_meta(run_dir, meta)
    d = _diag(run_dir)
    d[key] = info
    (run_dir / "train_diagnostics.json").write_text(json.dumps(d, indent=2), encoding="utf-8")
    _log(f"[{key}] out-of-fold AUC {meta['signals_done'][key]['oof_auc']:.3f} | validation AUC "
         f"{meta['signals_done'][key]['val_auc']:.3f} | {time.time() - t0:.0f}s")
    return info


# ------------------------------------------------------------------------------------------ fusion
def _col_thresholds(y, p, target_recall):
    ok = ~np.isnan(p)
    return {"max_f1": metrics.pick_threshold(y[ok], p[ok], "max_f1"),
            "recall_target": metrics.pick_threshold(y[ok], p[ok], "recall_target", target_recall)}


def fuse(cfg: dict, run_dir: Path) -> Path:
    tr, va, ytr, yva, gtr = _trval(cfg)
    have = available_signals(run_dir)
    core = [k for k in CORE if k in have]
    if not core:
        raise SystemExit("Train at least one of V, T, B first (gl signal B).")
    sig = {k: np.load(run_dir / "signals" / f"{k}.npz") for k in have}
    P_oof = {k: sig[k]["oof"] for k in core}
    P_val = {k: sig[k]["val"] for k in core}
    seed, folds, fc = cfg["seed"], cfg["cv"]["folds"], cfg["fusion"]
    _log(f"fusing signals {core}: {len(fusion.all_configs(core))} configurations")

    fusions: dict[str, fusion.FusionModel] = {}
    for keys in fusion.all_configs(core):
        fusions[fusion.config_name(keys)] = fusion.FusionModel(keys, fc["c_grid"], folds, seed).fit(P_oof, ytr, gtr)
    full = fusion.config_name(core)
    ff = fusions[full]

    val_df = va[META_COLS].copy()
    for k in have:
        val_df[f"p_{k}"] = sig[k]["val"]
    for name, fm in fusions.items():
        val_df[f"p_cfg_{name}"] = fm.predict(P_val)
    val_df["p_fusion"] = val_df[f"p_cfg_{full}"]
    val_df["p_fusion_raw"] = ff.raw_score(P_val)

    ec = cfg["evaluation"]
    thresholds = {c[2:]: _col_thresholds(yva, val_df[c].to_numpy(), ec["target_recall"]) for c in val_df if c.startswith("p_")}
    bands = fusion.fit_bands(yva, val_df["p_fusion"].to_numpy(), cfg["bands"]["low_max_recall"], cfg["bands"]["high_min_precision"])
    val_df["score_0_100"] = np.round(100 * val_df["p_fusion"]).astype(int)
    val_df["band"] = fusion.assign_band(val_df["p_fusion"].to_numpy(), bands)
    val_df.to_csv(run_dir / "val_predictions.csv", index=False)
    pd.DataFrame({"listing_id": tr["listing_id"], "target": ytr, **{f"p_{k}": P_oof[k] for k in core}}).to_csv(
        run_dir / "oof_predictions.csv", index=False)

    joblib.dump({"fusions": fusions, "full": full, "core": core, "thresholds": thresholds, "bands": bands},
                run_dir / "fusion.joblib")
    info = {"configs": {n: {"keys": m.keys, "weights": m.weights, "availability_weights": m.availability_weights,
                            "C": float(m.stacker.C_[0])} for n, m in fusions.items()},
            "bands": bands, "thresholds": thresholds, "core": core}
    (run_dir / "fusion.json").write_text(json.dumps(info, indent=2), encoding="utf-8")

    # SHAP (B) and explanations
    extra = {}
    bpath = run_dir / "models" / "B.joblib"
    if bpath.exists():
        b = joblib.load(bpath)
        shap_df = b.shap_values(va)
        Xb = b.transform(va)
        plots_ext.shap_summary(shap_df, Xb, run_dir / "figures" / "shap_summary.png")
        extra["shap_mean_abs"] = {c: float(np.abs(shap_df[c]).mean()) for c in shap_df.columns if c != "_base"}
        _write_explanations(run_dir, va, val_df, shap_df, Xb)
    vp = run_dir / "visual_features_trainval.csv"
    if vp.exists():
        Fv = pd.read_csv(vp).set_index("listing_id")
        both = pd.concat([tr, va])
        plots_ext.visual_feature_dists(Fv.reindex(both["listing_id"]), np.concatenate([ytr, yva]),
                                       run_dir / "figures" / "visual_feature_dists.png")
    d = _diag(run_dir)
    d["fusion"] = {**info, **extra}
    (run_dir / "train_diagnostics.json").write_text(json.dumps(d, indent=2), encoding="utf-8")
    meta = _meta(run_dir)
    meta["thresholds"], meta["bands"] = thresholds, bands
    _save_meta(run_dir, meta)

    from .report import evaluate_validation
    evaluate_validation(cfg, run_dir, _log)
    return run_dir


def _write_explanations(run_dir: Path, va: pd.DataFrame, val_df: pd.DataFrame, shap_df: pd.DataFrame, Xb: pd.DataFrame):
    from . import explain
    vp = run_dir / "visual_features_trainval.csv"
    Fv = pd.read_csv(vp).set_index("listing_id") if vp.exists() else None
    items = []
    for band in ("High", "Moderate", "Low"):
        idx = val_df.index[val_df["band"] == band][:4]
        for i in idx:
            row = val_df.loc[i]
            lid = row["listing_id"]
            vis = Fv.loc[lid] if Fv is not None and lid in Fv.index else None
            pt = row["p_T"] if "p_T" in val_df else None
            e = explain.explain_listing(Xb.loc[i], shap_df.loc[i], vis, pt, band, int(row["score_0_100"]))
            items.append({"id": f"{lid[:8]} ({va.loc[i, 'category']}, {va.loc[i, 'platform']})", "target": int(row["target"]), **e})
    (run_dir / "explanations_sample.md").write_text(explain.to_markdown(items), encoding="utf-8")


# --------------------------------------------------------------------------------------- evaluate
def score_columns(pred_df: pd.DataFrame) -> dict:
    return {c[2:]: pred_df[c].to_numpy(dtype=float) for c in pred_df.columns if c.startswith("p_")}


def evaluate_frame(cfg: dict, pred_df: pd.DataFrame, thresholds: dict, bands: dict, split: str, fig_dir: Path,
                   diag: dict | None = None, history: dict | None = None) -> dict:
    """Metrics + every chart for one split. Thresholds and bands are frozen (chosen on validation)."""
    y = pred_df["target"].to_numpy().astype(int)
    g = pred_df["group_id"].to_numpy()
    S = score_columns(pred_df)
    n_boot, seed = cfg["evaluation"]["bootstrap_resamples"], cfg["seed"]
    singles = [k for k in ["V", "T", "B", "text_baseline", "tabular_ext"] if k in S]
    cfgs = [k for k in S if k.startswith("cfg_")]
    names = singles + cfgs + ["fusion"]
    auc_fn = lambda a, b: roc_auc_score(a, b)  # noqa: E731
    ap_fn = lambda a, b: metrics.ranking(a, b)["pr_auc"]  # noqa: E731

    res: dict = {"split": split, "n": int(len(y)), "prevalence": float(y.mean()),
                 "baselines": {"flag_everything_f1": metrics.f1_if_flag_everything(y), "prevalence": float(y.mean())},
                 "availability": {k: float((~np.isnan(S[k])).mean()) for k in singles}, "models": {}}
    for k in names:
        p = S[k]
        ok = ~np.isnan(p)
        th = thresholds[k]
        res["models"][k] = {
            "n_scored": int(ok.sum()),
            "roc_auc": metrics.group_bootstrap(y, p, g, auc_fn, n_boot, seed),
            "pr_auc": metrics.group_bootstrap(y, p, g, ap_fn, n_boot, seed),
            "calibration": {kk: v for kk, v in metrics.calibration(y[ok], p[ok]).items() if kk != "bins"},
            "operating": {rule: metrics.at_threshold(y[ok], p[ok], th[rule]) for rule in ("max_f1", "recall_target")},
        }
    fp = S["fusion"]
    res["fusion_config"] = "+".join(c for c in CORE if c in S)
    res["band_thresholds"] = bands
    res["bands"] = fusion.band_table(y, fp, bands)
    res["operating_bands"] = {"flag_moderate_or_high": metrics.at_threshold(y, fp, bands["low_moderate"]),
                              "flag_high_only": metrics.at_threshold(y, fp, bands["moderate_high"])}
    cal_raw, cal_cal = metrics.calibration(y, S["fusion_raw"]), metrics.calibration(y, fp)
    res["calibration_compare"] = {"before": {k: v for k, v in cal_raw.items() if k != "bins"},
                                  "after": {k: v for k, v in cal_cal.items() if k != "bins"}}
    res["fusion_vs_single"] = {}
    for k in [s for s in ("V", "T", "B") if s in S]:
        res["fusion_vs_single"][k] = {
            "roc_auc": metrics.paired_bootstrap_diff(y, fp, S[k], g, auc_fn, n_boot, seed),
            "pr_auc": metrics.paired_bootstrap_diff(y, fp, S[k], g, ap_fn, n_boot, seed)}
    dims = {d: metrics.by_group(y, fp, pred_df[d].to_numpy(), bands["low_moderate"]) for d in ("platform", "category", "language")}
    res["groups"] = dims

    fd = Path(fig_dir)
    sfx = "" if split == "validation" else f"_{split}"
    shown = {k: S[k] for k in singles + ["fusion"]}
    figs = []
    figs.append(plots.roc(y, shown, fd / f"roc{sfx}.png", f"ROC curves ({split})"))
    figs.append(plots.pr(y, shown, fd / f"precision_recall{sfx}.png", f"Precision-recall curves ({split})"))
    figs.append(plots.model_comparison(
        [{"model": k, "roc_auc": res["models"][k]["roc_auc"], "pr_auc": res["models"][k]["pr_auc"]} for k in singles + ["fusion"]],
        fd / f"model_comparison{sfx}.png", float(y.mean()), split))
    figs.append(plots_ext.config_comparison(
        [{"name": k[4:], "roc_auc": res["models"][k]["roc_auc"], "pr_auc": res["models"][k]["pr_auc"]} for k in cfgs],
        fd / f"config_comparison{sfx}.png", float(y.mean()), split))
    figs.append(plots.score_distributions(y, shown, fd / f"score_distributions{sfx}.png",
                                              {k: thresholds[k]["max_f1"] for k in shown}, split))
    figs.append(plots_ext.calibration_compare(y, fp, cal_raw, cal_cal, fd / f"calibration_compare{sfx}.png", split))
    figs.append(plots.threshold_sweep(metrics.threshold_table(y, fp),
                                      {"Moderate": bands["low_moderate"], "High": bands["moderate_high"]},
                                      fd / f"threshold_sweep_fusion{sfx}.png", f"Fusion threshold sweep ({split}); band cut-offs"))
    figs.append(plots_ext.band_chart(res["bands"], bands, fd / f"band_chart{sfx}.png", split))
    for key, label in (("flag_moderate_or_high", "Moderate+High flagged"), ("flag_high_only", "High only flagged")):
        figs.append(plots.confusion_matrix(res["operating_bands"][key], fd / f"confusion_{key}{sfx}.png", f"{label} ({split})"))
    figs.append(plots.group_performance(dims, fd / f"group_performance{sfx}.png", res["models"]["fusion"]["roc_auc"]["point"]))
    w = (diag or {}).get("fusion", {}).get("configs", {}).get("+".join(c for c in CORE if c in S), {}).get("weights")
    if w and split == "validation":
        figs.append(plots.stacker_weights(w, fd / "stacker_weights.png"))
    if history and split == "validation":
        figs.append(plots.training_history(history, fd / "xlmr_training_history.png"))
    res["figures"] = figs
    return res


# ----------------------------------------------------------------------------------------- final
def _ledger(cfg: dict) -> dict:
    p = path(cfg, "ledger")
    return json.loads(p.read_text()) if p.exists() else {"test_evaluations": []}


def _score_df(cfg: dict, run_dir: Path, df: pd.DataFrame, tr: pd.DataFrame, log=_log) -> dict:
    """Scores of every trained signal for arbitrary listings (sealed test, or new listings)."""
    P = {}
    have = available_signals(run_dir)
    for k in have:
        if k == "T" and not (run_dir / "models" / "T.joblib").exists():
            from . import xlmr
            P[k] = xlmr.score_new(cfg, run_dir, df)
        elif k == "V":
            s = joblib.load(run_dir / "models" / "V.joblib")
            both = pd.concat([tr, df]).drop_duplicates("listing_id")
            store = visual.extract(cfg, both, log)
            s.builder, _ = _visual_builder(cfg, store, F.image_metadata(cfg))
            s.fold_context(tr, df)      # SSCD reference = the training split only
            P[k] = s.predict(df)
        else:
            m = joblib.load(run_dir / "models" / f"{k}.joblib")
            if getattr(m, "image_meta", None) is not None:   # new listings: measure their image files, no frozen join
                new = F.image_meta_for(cfg, df, m.image_meta).reset_index()
                m.image_meta = pd.concat([m.image_meta, new]).drop_duplicates("listing_id")
            P[k] = m.predict(df)
    return P


def final_test(cfg: dict, run_dir: Path, force: bool = False) -> dict:
    """Score the held-out test ONCE with the frozen models, thresholds and bands. Recorded in the ledger."""
    ledger = _ledger(cfg)
    if (any(e["run"] == run_dir.name for e in ledger["test_evaluations"]) or (run_dir / "test_metrics.json").exists()) and not force:
        raise SystemExit(f"Test already evaluated for {run_dir.name} (see {path(cfg, 'ledger')}). Looking again after seeing the "
                         "result invalidates it; use --force only to reproduce.")
    rep = D.verify(cfg)
    if not rep["ok"]:
        raise SystemExit("Data integrity check failed:\n  - " + "\n  - ".join(rep["problems"]))
    fz = joblib.load(run_dir / "fusion.joblib")
    tr, te = D.load_split(cfg, "train"), D.load_split(cfg, "test")
    P = _score_df(cfg, run_dir, te, tr)
    pred = te[META_COLS].copy()
    for k, p in P.items():
        pred[f"p_{k}"] = p
    for name, fm in fz["fusions"].items():
        pred[f"p_cfg_{name}"] = fm.predict(P)
    pred["p_fusion"] = pred[f"p_cfg_{fz['full']}"]
    pred["p_fusion_raw"] = fz["fusions"][fz["full"]].raw_score(P)
    pred["score_0_100"] = np.round(100 * pred["p_fusion"]).astype(int)
    pred["band"] = fusion.assign_band(pred["p_fusion"].to_numpy(), fz["bands"])
    pred.to_csv(run_dir / "test_predictions.csv", index=False)
    diag = _diag(run_dir)
    res = evaluate_frame(cfg, pred, fz["thresholds"], fz["bands"], "test", run_dir / "figures", diag)
    (run_dir / "test_metrics.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    ledger["test_evaluations"].append({
        "run": run_dir.name, "time": dt.datetime.now().isoformat(timespec="seconds"),
        "test_sha256": D.sha256(path(cfg, "splits_dir") / "test.csv"), "rows": res["n"],
        "fusion_roc_auc": res["models"]["fusion"]["roc_auc"]["point"]})
    lp = path(cfg, "ledger")
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    meta = _meta(run_dir)
    meta["test_used"] = True
    _save_meta(run_dir, meta)
    from .report import build_report
    build_report(cfg, run_dir)
    return res


# ---------------------------------------------------------------------------------------- predict
def predict_file(cfg: dict, run_dir: Path, csv_in: Path, csv_out: Path) -> pd.DataFrame:
    """Score new listings (same columns as the split CSVs). Missing signals are handled by the availability indicators."""
    fz = joblib.load(run_dir / "fusion.joblib")
    df = pd.read_csv(csv_in)
    for col in ("title", "description"):
        df[col] = df.get(col, "").fillna("").astype(str)
    if cfg["target"]["group_column"] not in df:
        df[cfg["target"]["group_column"]] = df["listing_id"]
    tr = D.load_split(cfg, "train")
    P = _score_df(cfg, run_dir, df, tr)
    full = fz["fusions"][fz["full"]]
    for k in full.keys:
        P.setdefault(k, np.full(len(df), np.nan))
    p = full.predict(P)
    out = df[["listing_id"]].copy() if "listing_id" in df else pd.DataFrame(index=df.index)
    for k, v in P.items():
        out[f"p_{k}"] = v
    out["risk_score_0_100"] = np.round(100 * p).astype(int)
    out["band"] = fusion.assign_band(p, fz["bands"])
    out.to_csv(csv_out, index=False)
    return out


def run_all(cfg: dict, tag: str, run: str | None, with_t: bool, force: bool = False) -> Path:
    run_dir = resolve_run(cfg, run) if run else new_run(cfg, tag)
    keys = []
    if cfg["signals"]["behavioural"]["enabled"]:
        keys.append("B")
    if cfg["signals"]["visual"]["enabled"]:
        keys.append("V")
    if with_t and cfg["signals"]["textual"]["enabled"]:
        keys.append("T")
    if cfg["references"]["text_baseline"]["enabled"]:
        keys.append("text_baseline")
    if cfg["references"]["exploratory_tabular"]["enabled"]:
        keys.append("tabular_ext")
    for k in keys:
        train_signal(cfg, run_dir, k, force)
    fuse(cfg, run_dir)
    return run_dir
