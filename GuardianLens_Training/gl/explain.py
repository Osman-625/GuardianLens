"""Methodology step 8: SHAP -> buyer-facing explanation templates.

B contributes TreeSHAP values (exact for XGBoost). V contributes its CLIP/SSCD evidence. T (XLM-R) has no
token-level attribution here, so it is described only at signal level. Wording is deliberately hedged: the score
is an annotated-risk estimate, not a fraud finding.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_EFFECT = 0.20  # |log-odds| below this is not mentioned


LABELS = {"account_age_days": "account age", "seller_rating": "rating", "review_count": "number of reviews",
          "active_listing_count": "number of active listings", "price": "asking price"}


def _b_sentence(feat: str, value, shap: float, row: pd.Series) -> str | None:
    """Plain-language sentence for one behavioural feature. Wording describes what the DATA associates with risk,
    never an invented meaning (e.g. a perfect rating is only called 'typical of risky listings' if SHAP says so)."""
    up = shap > 0
    if feat == "price_ratio_category":
        r = float(value)
        if up and r < 0.7:
            return f"The price is only about {r:.0%} of the usual price in this category."
        if up and r > 1.5:
            return f"The price is about {r:.1f}x the usual price in this category."
        return None if up else "The price is in line with similar listings."
    if feat.endswith("_missing"):
        base = feat[:-8]
        return f"The seller's {LABELS.get(base, base)} could not be seen." if up else None
    if feat == "account_age_days":
        d = float(value)
        if up and d < 180:
            return f"The seller's account is new ({d:.0f} days old)."
    if feat in LABELS:
        v = float(value)
        shown = f"{v / 365:.1f} years" if feat == "account_age_days" else f"{v:g}"
        side = "risky" if up else "legitimate"
        return f"The seller's {LABELS[feat]} ({shown}) is more typical of {side} listings in past data."
    return None


def explain_listing(row: pd.Series, shap_row: pd.Series | None, visual: pd.Series | None, p_t: float | None,
                    band: str, score: int) -> dict:
    """Return {'headline', 'risk_reasons', 'reassuring', 'caveat'} for one listing."""
    risk, ok = [], []
    if shap_row is not None:
        feats = [c for c in shap_row.index if c != "_base" and abs(shap_row[c]) >= MIN_EFFECT]
        for c in sorted(feats, key=lambda c: -abs(shap_row[c]))[:4]:
            s = _b_sentence(c, row.get(c, row.get(c.replace("_missing", ""), np.nan)), float(shap_row[c]), row)
            if s:
                (risk if shap_row[c] > 0 else ok).append(s)
    if visual is not None and visual.get("v_available", False):
        if visual.get("sscd_frac_match", 0) > 0:
            other = visual.get("sscd_match_listing", "")
            risk.append("A photo in this listing is almost identical to a photo in another listing"
                        + (f" ({other[:8]}...)." if other else "."))
        if visual.get("clip_title_mean", 1) < 0.17:
            risk.append("The photos do not clearly show the item described in the title.")
        elif visual.get("clip_title_mean", 0) > 0.28:
            ok.append("The photos match the item described.")
    if p_t is not None and not np.isnan(p_t):
        if p_t >= 0.6:
            risk.append("The wording of the description resembles listings previously judged risky.")
        elif p_t <= 0.2:
            ok.append("The wording of the description looks ordinary.")
    head = {"Low": "Few risk signals were found.", "Moderate": "Some risk signals were found. Check before paying.",
            "High": "Several risk signals were found. Be careful before paying."}[band]
    return {"headline": f"{band} risk ({score}/100). {head}", "risk_reasons": risk, "reassuring": ok,
            "caveat": "This is an estimate based on patterns in past listings, not proof of fraud."}


def to_markdown(items: list[dict]) -> str:
    out = ["# Example buyer-facing explanations (validation listings)\n",
           "Generated from TreeSHAP (B), CLIP/SSCD evidence (V) and the XLM-R score (T). Reviewed wording is still required "
           "before use in the app.\n"]
    for it in items:
        out.append(f"## {it['id']} - {it['headline']}\n")
        out.append(f"*True label: {'risky' if it['target'] else 'legitimate'}*\n")
        for r in it["risk_reasons"]:
            out.append(f"- (risk) {r}")
        for r in it["reassuring"]:
            out.append(f"- (reassuring) {r}")
        out.append(f"\n_{it['caveat']}_\n")
    return "\n".join(out)
