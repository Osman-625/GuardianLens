"""All evaluation charts. One PNG per figure, colour-blind-safe palette, no display needed."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score, roc_curve

# Okabe-Ito colour-blind-safe palette
C = {"blue": "#0072B2", "orange": "#E69F00", "green": "#009E73", "red": "#D55E00",
     "purple": "#CC79A7", "sky": "#56B4E9", "grey": "#666666"}
CYCLE = [C["blue"], C["orange"], C["green"], C["red"], C["purple"], C["sky"], C["grey"]]
NICE = {"V": "V Visual (CLIP+SSCD)", "T": "T Textual", "B": "B Behavioural (XGBoost)",
        "text_baseline": "Text baseline (TF-IDF)", "tabular_ext": "Exploratory: extended tabular",
        "fusion": "FUSION"}

plt.rcParams.update({
    "figure.dpi": 110, "savefig.dpi": 140, "font.size": 10, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.25, "axes.titleweight": "bold",
})


def _save(fig, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out.name


def name(k: str) -> str:
    if k in NICE:
        return NICE[k]
    return f"config {k[4:]} (calibrated alone)" if k.startswith("cfg_") else k


def _color(i: int, k: str) -> str:
    return C["red"] if k == "fusion" else CYCLE[i % len(CYCLE)]


def roc(y, scores: dict, out: Path, title="ROC curves (validation)"):
    fig, ax = plt.subplots(figsize=(6, 5.5))
    ax.plot([0, 1], [0, 1], ls="--", color=C["grey"], lw=1, label="Chance (AUC 0.50)")
    y = np.asarray(y)
    for i, (k, p) in enumerate(scores.items()):
        p = np.asarray(p, float)
        m = ~np.isnan(p)
        fpr, tpr, _ = roc_curve(y[m], p[m])
        ax.plot(fpr, tpr, color=_color(i, k), lw=2.8 if k == "fusion" else 1.5,
                label=f"{name(k)} (AUC {roc_auc_score(y[m], p[m]):.3f})")
    ax.set(xlabel="False positive rate", ylabel="True positive rate (recall)", title=title, xlim=(0, 1), ylim=(0, 1.01))
    ax.legend(loc="lower right", fontsize=8)
    return _save(fig, out)


def pr(y, scores: dict, out: Path, title="Precision-recall curves (validation)"):
    y = np.asarray(y)
    fig, ax = plt.subplots(figsize=(6, 5.5))
    ax.axhline(y.mean(), ls="--", color=C["grey"], lw=1, label=f"Base rate ({y.mean():.2f})")
    for i, (k, p) in enumerate(scores.items()):
        p = np.asarray(p, float)
        m = ~np.isnan(p)
        prec, rec, _ = precision_recall_curve(y[m], p[m])
        ax.plot(rec, prec, color=_color(i, k), lw=2.8 if k == "fusion" else 1.5,
                label=f"{name(k)} (AP {average_precision_score(y[m], p[m]):.3f})")
    ax.set(xlabel="Recall", ylabel="Precision", title=title, xlim=(0, 1), ylim=(0, 1.01))
    ax.legend(loc="upper right", fontsize=8)
    return _save(fig, out)


def confusion_matrix(cm: dict, out: Path, title: str):
    m = np.array([[cm["tn"], cm["fp"]], [cm["fn"], cm["tp"]]])
    norm = m / m.sum(axis=1, keepdims=True).clip(min=1)
    fig, ax = plt.subplots(figsize=(5, 4.4))
    ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
    ax.grid(False)
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{m[i, j]}\n{norm[i, j]:.0%}", ha="center", va="center",
                    color="white" if norm[i, j] > 0.55 else "black", fontsize=13, fontweight="bold")
    ax.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["Predicted\nlegitimate", "Predicted\nrisky"],
           yticklabels=["Actual\nlegitimate", "Actual\nrisky"], title=title)
    return _save(fig, out)


def score_distributions(y, scores: dict, out: Path, thresholds: dict | None = None, split: str = "validation"):
    """Score histogram per class. A collapsed model shows up as one narrow spike."""
    y = np.asarray(y)
    n = len(scores)
    cols = min(3, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 3.3 * rows), squeeze=False)
    bins = np.linspace(0, 1, 26)
    for ax, (k, p) in zip(axes.ravel(), scores.items()):
        p = np.asarray(p, float)
        m = ~np.isnan(p)
        p, y_k = p[m], y[m]
        ax.hist(p[y_k == 0], bins=bins, alpha=0.6, color=C["blue"], label="Legitimate", density=True)
        ax.hist(p[y_k == 1], bins=bins, alpha=0.6, color=C["red"], label="Risky", density=True)
        if thresholds and k in thresholds:
            ax.axvline(thresholds[k], color="black", ls="--", lw=1)
        ax.set_title(f"{name(k)}  (std {p.std():.3f})", fontsize=10)
        ax.set_xlabel("Predicted risk score")
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    axes.ravel()[0].legend(fontsize=8)
    fig.suptitle(f"Score distributions by true class ({split})", fontweight="bold", y=1.02)
    return _save(fig, out)


def calibration_plot(p, cal: dict, out: Path, title="Calibration (validation)"):
    fig, (a, b) = plt.subplots(2, 1, figsize=(5.4, 6.4), gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
    a.plot([0, 1], [0, 1], ls="--", color=C["grey"], label="Perfect")
    a.plot([r["mean_prob"] for r in cal["bins"]], [r["frac_pos"] for r in cal["bins"]], "o-", color=C["blue"],
           label=f"Model (ECE {cal['ece']:.3f}, Brier {cal['brier']:.3f})")
    a.set(ylabel="Observed fraction risky", title=title, xlim=(0, 1), ylim=(0, 1))
    a.legend(fontsize=8)
    b.hist(np.asarray(p), bins=np.linspace(0, 1, 21), color=C["sky"])
    b.set(xlabel="Predicted risk score", ylabel="Count")
    return _save(fig, out)


def threshold_sweep(tt: dict, chosen: dict, out: Path, title="Threshold sweep"):
    fig, ax = plt.subplots(figsize=(7, 4.5))
    t = np.asarray(tt["threshold"])
    ax.plot(t, tt["precision"], color=C["blue"], label="Precision")
    ax.plot(t, tt["recall"], color=C["orange"], label="Recall")
    ax.plot(t, tt["f1"], color=C["green"], lw=2.4, label="F1")
    ax.plot(t, tt["flagged_fraction"], color=C["grey"], ls=":", label="Fraction flagged")
    for i, (label, th) in enumerate(chosen.items()):
        ax.axvline(th, color="black", ls="--", lw=1)
        ax.text(th, 1.02 + 0.05 * (i % 2), label, ha="center", fontsize=8)
    ax.set(xlabel="Decision threshold", ylabel="Metric", title=title, ylim=(0, 1.15))
    ax.legend(fontsize=8, loc="center right")
    return _save(fig, out)


def model_comparison(rows: list[dict], out: Path, base_rate: float, split: str = "validation"):
    """Horizontal bars with bootstrap CI whiskers. rows: {model, roc_auc:{point,lo,hi}, pr_auc:{...}}"""
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 0.55 * len(rows) + 2.6))
    for ax, key in zip(axes, ("roc_auc", "pr_auc")):
        labs = [name(r["model"]) for r in rows]
        pts = np.array([r[key]["point"] for r in rows])
        lo = np.clip(pts - np.array([r[key]["lo"] for r in rows]), 0, None)
        hi = np.clip(np.array([r[key]["hi"] for r in rows]) - pts, 0, None)
        ax.barh(labs, pts, xerr=[lo, hi], color=[C["red"] if r["model"] == "fusion" else C["blue"] for r in rows],
                capsize=3, alpha=0.9)
        ax.axvline(0.5 if key == "roc_auc" else base_rate, ls="--", color=C["grey"], lw=1.2)
        for i, v in enumerate(pts):
            ax.text(min(v + hi[i] + 0.012, 0.93), i, f"{v:.3f}", va="center", fontsize=8)
        ax.set(title=("ROC AUC" if key == "roc_auc" else "PR AUC") + f" with 95% CI ({split})", xlim=(0, 1))
        ax.invert_yaxis()
    return _save(fig, out)


def group_performance(rows_by_dim: dict[str, list[dict]], out: Path, overall_auc: float):
    dims = list(rows_by_dim)
    fig, axes = plt.subplots(1, len(dims), figsize=(5.4 * len(dims), 5), squeeze=False)
    for ax, dim in zip(axes[0], dims):
        rows = sorted([r for r in rows_by_dim[dim] if not np.isnan(r["roc_auc"])], key=lambda r: r["roc_auc"])
        ax.barh([f"{r['group']} (n={r['n']})" for r in rows], [r["roc_auc"] for r in rows], color=C["blue"])
        ax.axvline(0.5, ls="--", color=C["grey"], lw=1)
        ax.axvline(overall_auc, ls=":", color=C["red"], lw=1.3)
        ax.set(title=f"ROC AUC by {dim}", xlim=(0, 1))
    fig.suptitle("Where does the fused model work? (dashed = chance, dotted red = overall)", fontsize=10, y=1.03)
    return _save(fig, out)


def feature_importance(names: list[str], means: list[float], stds: list[float], out: Path, top: int = 20):
    order = np.argsort(means)[::-1][:top][::-1]
    fig, ax = plt.subplots(figsize=(6.6, 0.32 * len(order) + 1.6))
    ax.barh([names[i] for i in order], [means[i] for i in order], xerr=[stds[i] for i in order],
            color=C["green"], capsize=2)
    ax.axvline(0, color="black", lw=0.8)
    ax.set(xlabel="Drop in validation ROC AUC when the feature is shuffled",
           title="Tabular feature importance (permutation)")
    return _save(fig, out)


def signal_ablation(rows: list[dict], full_auc: float, out: Path):
    rows = sorted(rows, key=lambda r: r["delta"])
    fig, ax = plt.subplots(figsize=(6.6, 0.55 * len(rows) + 1.8))
    ax.barh([f"without {name(r['dropped'])}" for r in rows], [r["delta"] for r in rows],
            color=[C["red"] if r["delta"] < 0 else C["green"] for r in rows])
    ax.axvline(0, color="black", lw=0.8)
    ax.set(xlabel=f"Change in validation AUC vs full fusion ({full_auc:.3f})",
           title="Which signals matter? (drop-one ablation)")
    return _save(fig, out)


def stacker_weights(weights: dict, out: Path):
    ks = list(weights)
    fig, ax = plt.subplots(figsize=(6, 0.55 * len(ks) + 1.6))
    ax.barh([name(k) for k in ks], [weights[k] for k in ks], color=C["purple"])
    ax.axvline(0, color="black", lw=0.8)
    ax.set(xlabel="Stacker coefficient on each signal's logit", title="Fusion weights")
    return _save(fig, out)


def dataset_overview(dfs: dict, out: Path):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    sp = list(dfs)
    risky = [int(d["target"].sum()) for d in dfs.values()]
    legit = [len(d) - r for d, r in zip(dfs.values(), risky)]
    axes[0].bar(sp, legit, color=C["blue"], label="Legitimate")
    axes[0].bar(sp, risky, bottom=legit, color=C["red"], label="Risky")
    for i, (a, b) in enumerate(zip(legit, risky)):
        axes[0].text(i, a + b + 8, f"{b / (a + b):.1%} risky", ha="center", fontsize=9)
    axes[0].set(title="Train / validation sizes and class balance (test sealed)", ylabel="Listings")
    axes[0].legend(fontsize=8)
    al = pd.concat(dfs.values())
    pt = al.groupby("platform")["target"].agg(["mean", "size"])
    axes[1].bar(pt.index, pt["mean"], color=[C["orange"], C["sky"]][: len(pt)])
    for i, (m, s) in enumerate(zip(pt["mean"], pt["size"])):
        axes[1].text(i, m + 0.01, f"{m:.1%}\n(n={s})", ha="center", fontsize=9)
    axes[1].set(title="Risky rate by platform (train + validation)", ylim=(0, float(pt["mean"].max()) * 1.4))
    ct = al.groupby("category")["target"].mean().sort_values()
    axes[2].barh(ct.index, ct.values, color=C["green"])
    axes[2].set(title="Risky rate by category (train + validation)")
    return _save(fig, out)


def training_history(hist: dict, out: Path, title="XLM-R fine-tuning, one line per fold"):
    """hist: {fold: [epoch dicts]}. Train loss, early-stopping-set AUC and score spread per epoch."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    for i, (fold, h) in enumerate(sorted(hist.items())):
        ep = [e["epoch"] for e in h]
        col = CYCLE[i % len(CYCLE)]
        axes[0].plot(ep, [e["train_loss"] for e in h], "o-", color=col, label=f"fold {int(fold) + 1}")
        axes[1].plot(ep, [e["val_auc"] for e in h], "o-", color=col)
        axes[2].plot(ep, [e["val_score_std"] for e in h], "o-", color=col)
    axes[0].set(title="Train loss", xlabel="Epoch")
    axes[0].legend(fontsize=8)
    axes[1].axhline(0.5, ls="--", color=C["grey"], lw=1)
    axes[1].set(title="Early-stopping set ROC AUC", xlabel="Epoch", ylim=(0, 1))
    axes[2].axhline(0.02, ls="--", color=C["grey"], lw=1)
    axes[2].set(title="Score spread (std); ~0 = collapsed", xlabel="Epoch")
    fig.suptitle(title, fontweight="bold", y=1.03)
    return _save(fig, out)
