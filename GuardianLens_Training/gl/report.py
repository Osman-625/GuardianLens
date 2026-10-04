"""Validation entry point and the REPORT.md / report.html builder (charts embedded, one self-contained page)."""
from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path

import pandas as pd

from . import data as D
from . import plots
from .plots import name


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def evaluate_validation(cfg: dict, run_dir: Path, log=print) -> dict:
    from .pipeline import evaluate_frame

    pred = pd.read_csv(run_dir / "val_predictions.csv")
    fz = _read(run_dir / "fusion.json")
    diag = _read(run_dir / "train_diagnostics.json") or {}
    hist = _read(run_dir / "xlmr_history.json")
    fig_dir = run_dir / "figures"
    dfs = {s: D.load_split(cfg, s)[["platform", "category", "target"]] for s in ("train", "validation")}  # test stays sealed
    plots.dataset_overview(dfs, fig_dir / "dataset_overview.png")
    res = evaluate_frame(cfg, pred, fz["thresholds"], fz["bands"], "validation", fig_dir, diag, hist)
    res["figures"].append("dataset_overview.png")
    (run_dir / "validation_metrics.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    build_report(cfg, run_dir)
    log(f"validation report -> {run_dir / 'report.html'}")
    return res


# ------------------------------------------------------------------------------- helpers
def _f(x, d=3):
    return "n/a" if x is None or x != x else f"{x:.{d}f}"


def _ci(m: dict) -> str:
    return f"{_f(m['point'])} [{_f(m['lo'])}, {_f(m['hi'])}]"


def _strength(auc: float) -> str:
    return ("no better than chance" if auc < 0.55 else "weak" if auc < 0.65 else "modest" if auc < 0.75
            else "useful" if auc < 0.85 else "strong")


def _verdict(res: dict, split: str) -> list[str]:
    ms, L = res["models"], []
    fus = ms["fusion"]
    pt, lo, hi = fus["roc_auc"]["point"], fus["roc_auc"]["lo"], fus["roc_auc"]["hi"]
    if lo > 0.5:
        L.append(f"**The fused {res.get('fusion_config', 'V+T+B')} model ranks risky above legitimate listings better than chance** on {split}: ROC AUC {_f(pt)} "
                 f"(95% CI {_f(lo)}-{_f(hi)} excludes 0.5), a **{_strength(pt)}** signal.")
    else:
        L.append(f"**The fused {res.get('fusion_config', 'V+T+B')} model is not reliably better than chance** on {split}: ROC AUC {_f(pt)} (95% CI {_f(lo)}-{_f(hi)} includes 0.5).")
    sig = {k: ms[k] for k in ("V", "T", "B") if k in ms}
    for k, m in sig.items():
        a = m["roc_auc"]
        status = "no reliable signal (CI includes 0.5)" if a["lo"] <= 0.5 else _strength(a["point"])
        L.append(f"{name(k)}: ROC AUC {_ci(a)}, {status}.")
    if len(sig) > 1:
        bk = max(sig, key=lambda k: sig[k]["roc_auc"]["point"])
        d = res["fusion_vs_single"][bk]["roc_auc"]
        verdict = ("a real improvement" if d["lo"] > 0 else "NOT distinguishable from zero" if d["hi"] >= 0
                   else "worse than the best single signal")
        L.append(f"Fusion vs best single signal ({name(bk)}): AUC difference {d['point']:+.3f} (95% CI {d['lo']:+.3f} to {d['hi']:+.3f}), {verdict}.")
    cfgs = {k: v for k, v in ms.items() if k.startswith("cfg_")}
    if cfgs:
        bc = max(cfgs, key=lambda k: cfgs[k]["roc_auc"]["point"])
        L.append(f"Best of the seven configurations: **{bc[4:]}** (AUC {_f(cfgs[bc]['roc_auc']['point'])}).")
    for k in ("text_baseline", "tabular_ext"):
        if k in ms:
            L.append(f"Reference {name(k)}: AUC {_ci(ms[k]['roc_auc'])}.")
    b = res["bands"]
    rates = [x["risky_rate"] for x in b]
    mono = all(rates[i] <= rates[i + 1] for i in range(2) if rates[i] == rates[i] and rates[i + 1] == rates[i + 1])
    L.append("Risk bands: " + ", ".join(f"{x['band']} {x['n']} listings ({_f(x['risky_rate'], 2)} risky)" for x in b)
             + f". The risky rate {'rises' if mono else 'does NOT rise'} from Low to High.")
    cc = res["calibration_compare"]
    L.append(f"Calibration: ECE {_f(cc['before']['ece'])} before, {_f(cc['after']['ece'])} after the sigmoid; Brier {_f(cc['after']['brier'])} "
             f"(a constant base-rate score gives about {_f(res['prevalence'] * (1 - res['prevalence']))}).")
    for k, m in ms.items():
        if m["calibration"]["score_std"] < 0.02:
            what = "this calibrated single-signal configuration" if k.startswith("cfg_") else "this signal"
            L.append(f"WARNING: {name(k)} scores have std {m['calibration']['score_std']:.4f}: almost constant. A constant calibrated output "
                     f"is not by itself proof that the raw signal collapsed ({what}); check the raw signal's own spread.")
    return L


def _rows_models(res: dict, keys: list[str]) -> list[list]:
    rows = []
    for k in keys:
        m = res["models"][k]
        op = m["operating"]["max_f1"]
        rows.append([name(k), m["n_scored"], _ci(m["roc_auc"]), _ci(m["pr_auc"]), _f(op["f1"], 2), _f(op["precision"], 2),
                     _f(op["recall"], 2), _f(m["calibration"]["brier"]), _f(m["calibration"]["score_std"], 3)])
    return rows


MODEL_HEADER = ["Model", "Scored", "ROC AUC [95% CI]", "PR AUC [95% CI]", "F1", "Precision", "Recall", "Brier", "Score std"]
BAND_HEADER = ["Band", "Listings", "Risky", "Risky rate", "Share of listings", "Share of all risky caught"]
OP_HEADER = ["Rule", "Threshold", "TP", "FP", "TN", "FN", "Precision", "Recall", "Specificity", "F1", "MCC", "Flagged"]

CAPTIONS = {
    "dataset_overview": "The frozen dataset: sizes and class balance per split, and risky rate by platform and category.",
    "config_comparison": "Methodology step 5: the seven configurations V, T, B, V+T, V+B, T+B, V+T+B on the same listings, with 95% bootstrap CIs. Best configuration in red.",
    "model_comparison": "Each signal, the references and the fusion, with 95% CIs (bootstrap over listing groups). Dashed = chance (AUC) or base rate (PR AUC).",
    "roc": "ROC curves. The diagonal is chance; further up-left is better.",
    "precision_recall": "Precision-recall curves. The dashed line is the base rate.",
    "score_distributions": "Predicted score per true class. Separated blue/orange humps = good ranking; one narrow spike = a collapsed model.",
    "calibration_compare": "Reliability before and after the sigmoid calibration (fitted on out-of-fold train scores only), and the calibrated score distribution.",
    "threshold_sweep_fusion": "Precision, recall and F1 against the threshold; dashed lines are the Moderate and High cut-offs fixed on validation.",
    "band_chart": "Low / Moderate / High bands: how many listings fall in each, and how many of them are actually risky. The risky share should rise from Low to High.",
    "confusion_flag_moderate_or_high": "Confusion matrix if Moderate and High both count as flagged.",
    "confusion_flag_high_only": "Confusion matrix if only High counts as flagged.",
    "group_performance": "ROC AUC of the fusion by platform, category and language (groups with at least 15 listings and both classes).",
    "stacker_weights": "How much the fusion trusts each signal (coefficient on its logit).",
    "shap_summary": "TreeSHAP for the behavioural XGBoost model: which behavioural features push a listing toward risk.",
    "visual_feature_dists": "The visual signal's inputs by true class: CLIP photo-title consistency and SSCD copy-detection similarity.",
    "xlmr_training_history": "XLM-R fine-tuning per fold: train loss, early-stopping AUC and score spread (near 0 = collapse).",
}
VAL_ORDER = ["dataset_overview", "config_comparison", "model_comparison", "roc", "precision_recall", "score_distributions",
             "calibration_compare", "band_chart", "threshold_sweep_fusion", "confusion_flag_moderate_or_high",
             "confusion_flag_high_only", "group_performance", "stacker_weights", "shap_summary", "visual_feature_dists",
             "xlmr_training_history"]
TEST_ORDER = ["config_comparison", "model_comparison", "roc", "precision_recall", "score_distributions", "calibration_compare",
              "band_chart", "confusion_flag_moderate_or_high", "confusion_flag_high_only", "group_performance"]


def _figs(run_dir: Path, names: list[str], suffix: str = ""):
    out = []
    for n in names:
        f = run_dir / "figures" / f"{n}{suffix}.png"
        if f.exists():
            out.append({"t": "img", "file": f"figures/{f.name}", "path": f, "cap": CAPTIONS.get(n, n)})
    return out


def _op_rows(res: dict) -> list[list]:
    rows = []
    for key, lab in (("flag_moderate_or_high", "Flag Moderate + High"), ("flag_high_only", "Flag High only")):
        o = res["operating_bands"][key]
        rows.append([lab, _f(o["threshold"], 4), o["tp"], o["fp"], o["tn"], o["fn"], _f(o["precision"]), _f(o["recall"]),
                     _f(o["specificity"]), _f(o["f1"]), _f(o["mcc"]), f"{o['flagged_fraction']:.0%}"])
    return rows


def build_report(cfg: dict, run_dir: Path):
    val = _read(run_dir / "validation_metrics.json")
    test = _read(run_dir / "test_metrics.json")
    run = _read(run_dir / "run.json")
    diag = _read(run_dir / "train_diagnostics.json") or {}
    if not val:
        return
    S = [{"t": "h1", "x": "GuardianLens - training report"}]
    d = run["data"]["splits"]
    S.append({"t": "p", "x": f"Run `{run['run_id']}` | created {run['created']} | target: annotated risk (suspicious + scam_fraud = 1), "
                             f"**not confirmed fraud** | train {d['train']['rows']} / validation {d['validation']['rows']} / test {d['test']['rows']} listings | "
                             f"test set: {'USED (see below)' if test else 'sealed, not used'} | variant: T = "
                             f"{run['config']['signals']['textual'].get('impl', 'xlmr')}, V image metadata = "
                             f"{'on' if run['config']['signals']['visual'].get('include_image_metadata') else 'off'} | signals trained: "
                             + ", ".join(f"{k} (val AUC {_f(v['val_auc'])})" for k, v in run["signals_done"].items())})
    S.append({"t": "h2", "x": "Verdict (validation)"})
    S.extend({"t": "li", "x": x} for x in _verdict(val, "validation"))

    cfg_keys = [k for k in val["models"] if k.startswith("cfg_")]
    S.append({"t": "h2", "x": "Seven-configuration ablation (methodology RQ2/RQ3)"})
    S.append({"t": "table", "header": MODEL_HEADER, "rows": _rows_models(val, cfg_keys)})
    S.append({"t": "small", "x": "Each configuration is a logistic-regression fusion of the named signals' out-of-fold scores plus availability indicators, "
                                 "calibrated by a sigmoid, scored on the same validation listings. Single-signal rows are calibrated single signals."})
    S.append({"t": "h2", "x": "Signals and reference models (validation)"})
    singles = [k for k in ("V", "T", "B", "text_baseline", "tabular_ext") if k in val["models"]] + ["fusion"]
    S.append({"t": "table", "header": MODEL_HEADER, "rows": _rows_models(val, singles)})
    S.append({"t": "small", "x": "F1/precision/recall use each model's own max-F1 threshold chosen on validation. Text baseline and the exploratory extended tabular "
                                 "model are references, not part of the fusion."})
    if val.get("fusion_vs_single"):
        S.append({"t": "h2", "x": "Does fusion beat each single signal? (paired bootstrap, validation)"})
        S.append({"t": "table", "header": ["vs signal", "AUC difference [95% CI]", "P(fusion better)", "PR AUC difference [95% CI]"],
                  "rows": [[name(k), f"{v['roc_auc']['point']:+.3f} [{v['roc_auc']['lo']:+.3f}, {v['roc_auc']['hi']:+.3f}]",
                            _f(v["roc_auc"]["p_better"], 2), f"{v['pr_auc']['point']:+.3f} [{v['pr_auc']['lo']:+.3f}, {v['pr_auc']['hi']:+.3f}]"]
                           for k, v in val["fusion_vs_single"].items()]})
    S.append({"t": "h2", "x": "Risk bands and operating points (fixed on validation)"})
    S.append({"t": "table", "header": BAND_HEADER,
              "rows": [[b["band"], b["n"], b["risky"], _f(b["risky_rate"], 2), f"{b['share_of_listings']:.0%}", f"{b['share_of_risky_caught']:.0%}"] for b in val["bands"]]})
    S.append({"t": "table", "header": OP_HEADER, "rows": _op_rows(val)})
    S.append({"t": "h2", "x": "Charts (validation)"})
    S.extend(_figs(run_dir, VAL_ORDER))

    fz = diag.get("fusion", {})
    full = "+".join(fz.get("core", []))
    if fz.get("configs", {}).get(full):
        c = fz["configs"][full]
        S.append({"t": "h2", "x": "Fusion coefficients (full V+T+B)"})
        S.append({"t": "table", "header": ["Signal", "Weight on logit", "Weight on availability flag"],
                  "rows": [[name(k), _f(c["weights"][k]), _f(c["availability_weights"][k])] for k in c["weights"]]})
    if fz.get("shap_mean_abs"):
        top = sorted(fz["shap_mean_abs"].items(), key=lambda t: -t[1])[:8]
        S.append({"t": "h2", "x": "Behavioural features by mean |SHAP|"})
        S.append({"t": "table", "header": ["Feature", "Mean |log-odds effect|"], "rows": [[a, _f(b, 3)] for a, b in top]})
    if diag.get("V", {}).get("coefficients"):
        S.append({"t": "h2", "x": "Visual head coefficients (standardised inputs)"})
        S.append({"t": "table", "header": ["Feature", "Coefficient"], "rows": [[a, _f(b)] for a, b in diag["V"]["coefficients"].items()]})
    if diag.get("T", {}).get("cue_effects"):
        S.append({"t": "h2", "x": "Text-cue effects in signal T (standardised coefficients)"})
        S.append({"t": "table", "header": ["Cue", "Coefficient"], "rows": [[a, _f(b)] for a, b in list(diag["T"]["cue_effects"].items())[:10]]})
    if diag.get("text_baseline", {}).get("top_terms"):
        t = diag["text_baseline"]["top_terms"]
        S.append({"t": "h2", "x": "Terms the TF-IDF text baseline associates with each class"})
        S.append({"t": "p", "x": "**Risky:** " + ", ".join(t["risky"]) + "  \n**Legitimate:** " + ", ".join(t["legitimate"])})
    if (run_dir / "explanations_sample.md").exists():
        S.append({"t": "p", "x": "Example buyer-facing explanations generated from SHAP + CLIP/SSCD + XLM-R: `explanations_sample.md`."})

    if test:
        S.append({"t": "h1", "x": "Held-out test results"})
        S.append({"t": "p", "x": f"Scored once with the frozen models, fusion, calibrators and bands ({test['n']} listings)."})
        S.extend({"t": "li", "x": x} for x in _verdict(test, "test"))
        tcfg = [k for k in test["models"] if k.startswith("cfg_")]
        S.append({"t": "table", "header": MODEL_HEADER, "rows": _rows_models(test, tcfg)})
        S.append({"t": "table", "header": BAND_HEADER,
                  "rows": [[b["band"], b["n"], b["risky"], _f(b["risky_rate"], 2), f"{b['share_of_listings']:.0%}", f"{b['share_of_risky_caught']:.0%}"] for b in test["bands"]]})
        S.append({"t": "table", "header": OP_HEADER, "rows": _op_rows(test)})
        S.extend(_figs(run_dir, TEST_ORDER, "_test"))

    S.append({"t": "h2", "x": "Protocol and limits"})
    for x in [
        "Splits are frozen and grouped: listings in the same duplicate group never cross train/validation/test or out-of-fold folds (verified on every run).",
        "Every signal, the fusion, the calibrator and the band cut-offs are fitted using training data (grouped cross-validation) or chosen on validation. The calibrator uses out-of-fold train scores only. The test set is scored once per run (`evaluations/test_ledger.json`).",
        "XLM-R early stopping uses an inner slice of each fold's training data, so out-of-fold and validation scores are not tuned on their own labels.",
        "SSCD similarity measures reuse inside the declared reference corpus (the train split's photos, same-group photos excluded). It cannot show that a photo is universally original or that a listing is fraudulent.",
        "CLIP text understanding is mostly English; Malay-language titles weaken the photo-title consistency score.",
        "Labels are AI-annotated risk judgements from text, images and seller behaviour, not confirmed fraud outcomes. Scores are risk estimates, not fraud probabilities.",
        "With a few hundred validation listings, confidence intervals are wide. Differences smaller than the CI width are not evidence that one configuration is better.",
    ]:
        S.append({"t": "li", "x": x})
    (run_dir / "REPORT.md").write_text(_to_md(S), encoding="utf-8")
    (run_dir / "report.html").write_text(_to_html(S, run["run_id"]), encoding="utf-8")


def _to_md(S) -> str:
    out = []
    for b in S:
        t = b["t"]
        if t in ("h1", "h2"):
            out.append(("# " if t == "h1" else "## ") + b["x"] + "\n")
        elif t in ("p", "small"):
            out.append(b["x"] + "\n")
        elif t == "li":
            out.append("- " + b["x"])
        elif t == "table":
            out.append("\n| " + " | ".join(b["header"]) + " |\n|" + "---|" * len(b["header"]))
            out.extend("| " + " | ".join(str(c) for c in r) + " |" for r in b["rows"])
            out.append("")
        elif t == "img":
            out.append(f"\n![{b['cap']}]({b['file']})\n\n*{b['cap']}*\n")
    return "\n".join(out) + "\n"


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s).replace("  \n", "<br>")


CSS = """
:root{--bg:#fff;--fg:#1c2530;--mut:#5b6673;--line:#dfe4ea;--card:#f6f8fa}
@media (prefers-color-scheme:dark){:root{--bg:#12161b;--fg:#e6ebf0;--mut:#9aa6b2;--line:#2b333c;--card:#1a2027}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,Segoe UI,sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.7rem;margin:1.6em 0 .4em}h2{font-size:1.2rem;margin:1.8em 0 .5em;border-bottom:1px solid var(--line);padding-bottom:.25em}
li{margin:.35em 0}.small{color:var(--mut);font-size:.85rem}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.86rem}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}th{background:var(--card)}
figure{margin:1.2em 0;background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px}
figure img{max-width:100%;height:auto;display:block;margin:0 auto}
figcaption{color:#444;font-size:.85rem;margin-top:6px}code{background:var(--card);padding:1px 5px;border-radius:4px}
"""


def _to_html(S, title: str) -> str:
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>GuardianLens report {html.escape(title)}</title><style>{CSS}</style></head><body><main>"]
    in_ul = False
    for b in S:
        t = b["t"]
        if t != "li" and in_ul:
            out.append("</ul>")
            in_ul = False
        if t in ("h1", "h2"):
            out.append(f"<{t}>{_inline(b['x'])}</{t}>")
        elif t == "p":
            out.append(f"<p>{_inline(b['x'])}</p>")
        elif t == "small":
            out.append(f"<p class='small'>{_inline(b['x'])}</p>")
        elif t == "li":
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(b['x'])}</li>")
        elif t == "table":
            out.append("<div class='tw'><table><tr>" + "".join(f"<th>{html.escape(str(h))}</th>" for h in b["header"]) + "</tr>")
            out.extend("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in b["rows"])
            out.append("</table></div>")
        elif t == "img":
            data = base64.b64encode(b["path"].read_bytes()).decode()
            out.append(f"<figure><img alt='{html.escape(b['cap'])}' src='data:image/png;base64,{data}'>"
                       f"<figcaption>{html.escape(b['cap'])}</figcaption></figure>")
    if in_ul:
        out.append("</ul>")
    out.append("</main></body></html>")
    return "".join(out)
