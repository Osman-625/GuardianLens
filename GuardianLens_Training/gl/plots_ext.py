"""Charts specific to the methodology: seven configurations, calibration, bands, SHAP, visual inputs."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .plots import C, _save


def config_comparison(rows: list[dict], out: Path, base_rate: float, split: str = "validation"):
    """The seven V/T/B configurations. rows: {name, roc_auc:{point,lo,hi}, pr_auc:{...}}"""
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 0.5 * len(rows) + 2.6))
    for ax, key in zip(axes, ("roc_auc", "pr_auc")):
        pts = np.array([r[key]["point"] for r in rows])
        lo = np.clip(pts - np.array([r[key]["lo"] for r in rows]), 0, None)
        hi = np.clip(np.array([r[key]["hi"] for r in rows]) - pts, 0, None)
        best = int(np.argmax(pts))
        ax.barh([r["name"] for r in rows], pts, xerr=[lo, hi], capsize=3,
                color=[C["red"] if i == best else C["blue"] for i in range(len(rows))], alpha=0.9)
        ax.axvline(0.5 if key == "roc_auc" else base_rate, ls="--", color=C["grey"], lw=1.2)
        for i, v in enumerate(pts):
            ax.text(min(v + hi[i] + 0.012, 0.93), i, f"{v:.3f}", va="center", fontsize=8)
        ax.set(title=("ROC AUC" if key == "roc_auc" else "PR AUC") + f", 95% CI ({split})", xlim=(0, 1))
        ax.invert_yaxis()
    fig.suptitle("Seven-configuration ablation: V, T, B, V+T, V+B, T+B, V+T+B (best in red)",
                 fontsize=10, fontweight="bold", y=1.02)
    return _save(fig, out)


def calibration_compare(y, p_cal, cal_raw: dict, cal_cal: dict, out: Path, split="validation"):
    y = np.asarray(y)
    p_cal = np.asarray(p_cal)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    for ax, cal, lab, col in ((axes[0], cal_raw, "Before calibration (stacker)", C["orange"]),
                              (axes[1], cal_cal, "After sigmoid calibration", C["blue"])):
        ax.plot([0, 1], [0, 1], ls="--", color=C["grey"])
        ax.plot([r["mean_prob"] for r in cal["bins"]], [r["frac_pos"] for r in cal["bins"]], "o-", color=col)
        ax.set(title=f"{lab}\nECE {cal['ece']:.3f}  Brier {cal['brier']:.3f}", xlabel="Predicted risk",
               ylabel="Observed fraction risky", xlim=(0, 1), ylim=(0, 1))
    bins = np.linspace(0, 1, 21)
    axes[2].hist(p_cal[y == 0], bins=bins, alpha=0.6, color=C["blue"], label="Legitimate")
    axes[2].hist(p_cal[y == 1], bins=bins, alpha=0.6, color=C["red"], label="Risky")
    axes[2].set(title="Calibrated score distribution", xlabel="Calibrated risk score")
    axes[2].legend(fontsize=8)
    fig.suptitle(f"Fusion reliability ({split})", fontweight="bold", y=1.03)
    return _save(fig, out)


def band_chart(rows: list[dict], bands: dict, out: Path, split="validation"):
    names = [r["band"] for r in rows]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    legit = [r["n"] - r["risky"] for r in rows]
    risky = [r["risky"] for r in rows]
    axes[0].bar(names, legit, color=C["blue"], label="Legitimate")
    axes[0].bar(names, risky, bottom=legit, color=C["red"], label="Risky")
    for i, r in enumerate(rows):
        axes[0].text(i, r["n"] + 2, f"n={r['n']}", ha="center", fontsize=9)
    axes[0].set(title=f"Listings per band ({split})", ylabel="Listings")
    axes[0].legend(fontsize=8)
    rate = [r["risky_rate"] for r in rows]
    axes[1].bar(names, [0 if v != v else v for v in rate], color=[C["green"], C["orange"], C["red"]])
    for i, v in enumerate(rate):
        axes[1].text(i, (0 if v != v else v) + 0.02, "n/a" if v != v else f"{v:.0%}", ha="center", fontsize=10, fontweight="bold")
    axes[1].set(title="Share risky within each band (should rise Low to High)", ylim=(0, 1.1))
    fig.suptitle(f"Moderate from {bands['low_moderate']:.3f}  |  High from {bands['moderate_high']:.3f}", fontsize=10, y=1.02)
    return _save(fig, out)


def shap_summary(shap_df, X, out: Path, top: int = 12):
    """Beeswarm-style TreeSHAP summary: x = effect on log-odds of risk, colour = feature value (low to high)."""
    cols = [c for c in shap_df.columns if c != "_base"]
    order = sorted(cols, key=lambda c: -np.abs(shap_df[c]).mean())[:top][::-1]
    rng = np.random.default_rng(0)
    fig, axes = plt.subplots(1, 2, figsize=(13, 0.42 * len(order) + 2.4), gridspec_kw={"width_ratios": [1, 1.4]})
    axes[0].barh(order, [np.abs(shap_df[c]).mean() for c in order], color=C["green"])
    axes[0].set(title="Mean |SHAP| (importance)", xlabel="mean absolute log-odds effect")
    for i, c in enumerate(order):
        r = X[c].astype(float).rank(pct=True).fillna(0.5).to_numpy()
        axes[1].scatter(shap_df[c], i + rng.uniform(-0.28, 0.28, len(r)), c=r, cmap="coolwarm", s=8, alpha=0.7)
    axes[1].set_yticks(range(len(order)), order)
    axes[1].axvline(0, color="black", lw=0.8)
    axes[1].set(title="TreeSHAP per listing (red = high value, blue = low)", xlabel="effect on log-odds of risk")
    return _save(fig, out)


def visual_feature_dists(F, y, out: Path):
    """Distribution of the V inputs by true class: the evidence behind the visual signal."""
    cols = [("clip_title_mean", "CLIP photo-title similarity"), ("clip_category_mean", "CLIP photo-category similarity"),
            ("sscd_max", "SSCD: max similarity to another\nlisting's photo"), ("sscd_mean_max", "SSCD: mean of per-photo max")]
    cols = [c for c in cols if c[0] in F.columns]
    fig, axes = plt.subplots(1, len(cols), figsize=(4.2 * len(cols), 3.8), squeeze=False)
    y = np.asarray(y)
    for ax, (c, t) in zip(axes[0], cols):
        v = F[c].to_numpy(dtype=float)
        ok = ~np.isnan(v)
        bins = np.linspace(np.nanmin(v), np.nanmax(v), 26)
        ax.hist(v[ok & (y == 0)], bins=bins, alpha=0.6, color=C["blue"], density=True, label="Legitimate")
        ax.hist(v[ok & (y == 1)], bins=bins, alpha=0.6, color=C["red"], density=True, label="Risky")
        ax.set_title(t, fontsize=9)
    axes[0][0].legend(fontsize=8)
    fig.suptitle("Visual signal inputs by true class (train + validation)", fontweight="bold", y=1.04)
    return _save(fig, out)
