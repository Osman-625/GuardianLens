"""Metrics, operating-point selection and grouped bootstrap confidence intervals."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (average_precision_score, balanced_accuracy_score, brier_score_loss,
                             log_loss, matthews_corrcoef, roc_auc_score)


def ranking(y, p) -> dict:
    y = np.asarray(y)
    if len(set(y.tolist())) < 2:
        return {"roc_auc": float("nan"), "pr_auc": float("nan")}
    return {"roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p))}


def confusion(y, p, threshold: float) -> dict:
    y = np.asarray(y).astype(int)
    pred = (np.asarray(p) >= threshold).astype(int)
    return {
        "tp": int(((pred == 1) & (y == 1)).sum()), "fp": int(((pred == 1) & (y == 0)).sum()),
        "tn": int(((pred == 0) & (y == 0)).sum()), "fn": int(((pred == 0) & (y == 1)).sum()),
    }


def at_threshold(y, p, threshold: float) -> dict:
    y = np.asarray(y).astype(int)
    c = confusion(y, p, threshold)
    tp, fp, tn, fn = c["tp"], c["fp"], c["tn"], c["fn"]
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    spec = tn / (tn + fp) if tn + fp else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    pred = (np.asarray(p) >= threshold).astype(int)
    two_class = len(set(y.tolist())) > 1
    return {
        **c, "threshold": float(threshold), "precision": prec, "recall": rec, "specificity": spec, "f1": f1,
        "accuracy": (tp + tn) / max(len(y), 1),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)) if two_class else float("nan"),
        "mcc": float(matthews_corrcoef(y, pred)) if len(set(pred.tolist())) > 1 else 0.0,
        "flagged_fraction": float(pred.mean()),
    }


def calibration(y, p, bins: int = 10) -> dict:
    y, p = np.asarray(y, float), np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows, ece = [], 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            conf, acc = float(p[m].mean()), float(y[m].mean())
            ece += m.mean() * abs(conf - acc)
            rows.append({"bin": b, "n": int(m.sum()), "mean_prob": conf, "frac_pos": acc})
    return {
        "ece": float(ece), "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])), "bins": rows,
        "score_std": float(p.std()), "score_range": float(p.max() - p.min()),
    }


def threshold_table(y, p) -> dict:
    """Precision/recall/F1 across thresholds, for the threshold-sweep chart."""
    y, p = np.asarray(y), np.asarray(p)
    ts = np.unique(np.quantile(p, np.linspace(0, 1, 201)))
    rows = [at_threshold(y, p, t) for t in ts]
    return {k: [r[k] for r in rows] for k in ("threshold", "precision", "recall", "f1", "flagged_fraction")}


def pick_threshold(y, p, rule: str = "max_f1", target_recall: float = 0.90) -> float:
    """Choose an operating point. Call with VALIDATION data only."""
    y, p = np.asarray(y), np.asarray(p)
    cands = np.unique(p)
    if rule == "max_f1":
        f1s = [at_threshold(y, p, t)["f1"] for t in cands]
        best = max(f1s)
        return float(cands[max(i for i, f in enumerate(f1s) if f >= best - 1e-12)])
    if rule == "recall_target":
        ok = [t for t in cands if at_threshold(y, p, t)["recall"] >= target_recall]
        return float(max(ok)) if ok else float(cands.min())
    raise ValueError(rule)


def f1_if_flag_everything(y) -> float:
    """F1 of the useless rule 'call every listing risky'. A model must clearly beat this."""
    prev = float(np.asarray(y).mean())
    return 2 * prev / (1 + prev)


def group_bootstrap(y, p, groups, fn, n: int = 1000, seed: int = 42) -> dict:
    """Bootstrap by resampling whole groups (listings sharing a group are not independent)."""
    y, p, groups = np.asarray(y), np.asarray(p, float), np.asarray(groups)
    ok = ~np.isnan(p)  # rows where the signal is unavailable are excluded from that signal's metrics
    y, p, groups = y[ok], p[ok], groups[ok]
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(groups, return_inverse=True)
    members = [np.flatnonzero(inv == i) for i in range(len(uniq))]
    vals = []
    for _ in range(n):
        pick = rng.integers(0, len(uniq), len(uniq))
        idx = np.concatenate([members[i] for i in pick])
        if len(set(y[idx].tolist())) < 2:
            continue
        vals.append(fn(y[idx], p[idx]))
    vals = np.asarray(vals, float)
    point = float(fn(y, p))
    if not len(vals):
        return {"point": point, "lo": float("nan"), "hi": float("nan"), "n": 0}
    return {"point": point, "lo": float(np.nanpercentile(vals, 2.5)), "hi": float(np.nanpercentile(vals, 97.5)), "n": int(len(vals))}


def by_group(y, p, labels_, threshold: float, min_n: int = 15) -> list[dict]:
    y, p, labels_ = np.asarray(y), np.asarray(p), np.asarray(labels_)
    rows = []
    for g in sorted(set(labels_.tolist())):
        m = labels_ == g
        r = {"group": str(g), "n": int(m.sum()), "positives": int(y[m].sum())}
        ok = len(set(y[m].tolist())) > 1 and m.sum() >= min_n
        r["roc_auc"] = float(roc_auc_score(y[m], p[m])) if ok else float("nan")
        r["recall"] = at_threshold(y[m], p[m], threshold)["recall"] if y[m].sum() else float("nan")
        r["flagged_fraction"] = float((p[m] >= threshold).mean())
        rows.append(r)
    return rows


def paired_bootstrap_diff(y, p_a, p_b, groups, fn, n: int = 1000, seed: int = 42) -> dict:
    """95% CI of fn(y, p_a) - fn(y, p_b) over group resamples. NaN scores are dropped pairwise first."""
    y, p_a, p_b, groups = np.asarray(y), np.asarray(p_a, float), np.asarray(p_b, float), np.asarray(groups)
    ok = ~(np.isnan(p_a) | np.isnan(p_b))
    y, p_a, p_b, groups = y[ok], p_a[ok], p_b[ok], groups[ok]
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(groups, return_inverse=True)
    members = [np.flatnonzero(inv == i) for i in range(len(uniq))]
    vals = []
    for _ in range(n):
        idx = np.concatenate([members[i] for i in rng.integers(0, len(uniq), len(uniq))])
        if len(set(y[idx].tolist())) < 2:
            continue
        vals.append(fn(y[idx], p_a[idx]) - fn(y[idx], p_b[idx]))
    point = float(fn(y, p_a) - fn(y, p_b))
    if not vals:
        return {"point": point, "lo": float("nan"), "hi": float("nan"), "p_better": float("nan")}
    v = np.asarray(vals)
    return {"point": point, "lo": float(np.percentile(v, 2.5)), "hi": float(np.percentile(v, 97.5)),
            "p_better": float((v > 0).mean())}
