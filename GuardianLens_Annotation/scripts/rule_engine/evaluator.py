from __future__ import annotations

from dataclasses import dataclass, field

from scripts.rule_engine.config import Rule, ThresholdConfig

TRUST_CATEGORY = "trust"


@dataclass
class EvaluationResult:
    listing_id: str
    risk_score: float
    trust_score: float
    critical_rule_count: int
    strong_rule_count: int
    matched_rule_ids: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    rule_label: str = "insufficient_evidence"
    label_confidence: str = "rough"
    label_reason: str = ""


def _rule_fires(rule: Rule, feature_row: dict) -> tuple[bool, str | None]:
    """Boolean-feature-flag rules only; keyword_combo/url/price/image rules are evaluated by
    the same convention: extract_annotation_features.py precomputes a matching boolean/derived
    field per rule family (has_credential_request, price_anomaly_score, cross_listing_duplicate_count,
    etc.) so the evaluator stays declarative and never re-parses text."""
    method = rule.matching_method
    if method.startswith("keyword_group:credential_request"):
        return bool(feature_row.get("has_credential_request")), feature_row.get("description")
    if method == "keyword_group:advance_payment:weak":
        fired = bool(feature_row.get("has_advance_payment_weak"))
        return fired, feature_row.get("description") if fired else None
    if method == "keyword_group:advance_payment:strong":
        fired = bool(feature_row.get("has_advance_payment_strong"))
        return fired, feature_row.get("description") if fired else None
    if method.startswith("keyword_group:agent_courier_release_fee"):
        fired = bool(feature_row.get("has_agent_fee_language"))
        return fired, feature_row.get("description") if fired else None
    if method.startswith("keyword_group:fake_payment_confirmation"):
        fired = bool(feature_row.get("has_fake_payment_language"))
        return fired, feature_row.get("description") if fired else None
    if method.startswith("keyword_group:off_platform_contact"):
        fired = bool(feature_row.get("has_whatsapp")) or bool(feature_row.get("has_external_contact"))
        return fired, feature_row.get("description") if fired else None
    if method.startswith("keyword_group:impersonation"):
        fired = bool(feature_row.get("has_impersonation_language"))
        return fired, feature_row.get("description") if fired else None
    if method == "price_ratio_tiered":
        # bool(), not `is not None`: after a CSV round-trip a blank cell reads back as "" (an
        # empty string), which "is not None" but is still falsy - the actual bug that made this
        # rule fire on all 2,209 listings during the first real run of this pipeline.
        return bool(feature_row.get("price_anomaly_score")), feature_row.get("price_ratio")
    if method == "image_cross_listing_group":
        count = feature_row.get("cross_listing_duplicate_count") or 0
        return count >= 1, feature_row.get("cross_listing_related_ids")
    if method == "image_cross_listing_group_large":
        count = feature_row.get("cross_listing_duplicate_count") or 0
        return count >= 5, feature_row.get("cross_listing_related_ids")
    if method == "description_similarity":
        count = feature_row.get("description_duplicate_count") or 0
        return count >= 1, feature_row.get("description_related_ids")
    if method.startswith("numeric_threshold:account_age_days<=7"):
        v = feature_row.get("account_age_days")
        return (v is not None and v <= 7), v
    if method.startswith("numeric_threshold:account_age_days>=365"):
        v = feature_row.get("account_age_days")
        return (v is not None and v >= 365), v
    if method.startswith("numeric_range:account_age_days:8:30"):
        v = feature_row.get("account_age_days")
        return (v is not None and 8 <= v <= 30), v
    if method.startswith("numeric_range:account_age_days:180:364"):
        v = feature_row.get("account_age_days")
        return (v is not None and 180 <= v <= 364), v
    if method == "field_equals_zero_confirmed":
        v = feature_row.get("review_count")
        return v == 0, v
    if method.startswith("numeric_threshold_pair:seller_rating<2.5"):
        r, c = feature_row.get("seller_rating"), feature_row.get("review_count")
        return (r is not None and c is not None and r < 2.5 and c >= 5), r
    if method.startswith("numeric_threshold_pair:seller_rating>=4.5"):
        r, c = feature_row.get("seller_rating"), feature_row.get("review_count")
        return (r is not None and c is not None and r >= 4.5 and c >= 10), r
    if method.startswith("numeric_range:price_ratio:0.85:1.5"):
        v = feature_row.get("price_ratio")
        return (v is not None and 0.85 <= v <= 1.5), v
    if method == "field_equals_true":
        # Semak Mule rules - always False while the field is NULL/unchecked (never guessed).
        return False, None
    if method == "category_keyword_conflict":
        return False, None  # conservative: no hand-curated conflict pairs shipped yet
    if method == "url_suspicious":
        return False, None  # URL-domain heuristics land in a follow-up task, not fabricated here
    if method.startswith("keyword_combo:"):
        return False, None  # combo rules require multi-category text re-check, deferred
    raise ValueError(f"unknown matching_method: {method}")


def _confidence_tier(label: str, trust_score: float, critical_count: int, strong_count: int,
                      matched_count: int, thresholds: ThresholdConfig) -> str:
    """Confidence describes how much corroborating evidence stacked up behind the label -
    it is never "weak"; a critical rule (e.g. an OTP request) is always high-confidence even
    though the overall system is still a rule-based heuristic, not verified ground truth."""
    if critical_count >= 1:
        return "high"
    if label == "likely_scam":
        return "high" if strong_count >= 2 else "moderate"
    if label == "suspicious":
        return "moderate" if matched_count >= 2 else "rough"
    if label == "likely_legitimate":
        return "moderate" if trust_score >= thresholds.legitimate_trust_score_min + 2 else "rough"
    return "rough"  # insufficient_evidence is rough by definition - that IS the label's meaning


def _build_reason(label: str, matched_rules: list[Rule], risk_score: float, trust_score: float) -> str:
    if not matched_rules:
        if label == "likely_legitimate":
            return ("Likely legitimate on absence of evidence only: no risk signal fired and "
                    "some trust signal(s) present, but this is a rough call - no strong positive "
                    "confirmation exists beyond 'nothing looked wrong'.")
        return ("Insufficient evidence: no seller, price, text, or image rule fired in either "
                "direction - there is simply not enough signal here to call it either way.")
    fired_desc = "; ".join(f"{r.rule_id} \"{r.name}\" [{r.severity}]" for r in matched_rules)
    return f"{label} (risk_score={risk_score:.1f}, trust_score={trust_score:.1f}). Matched rules: {fired_desc}."


def evaluate_listing(feature_row: dict, rules: list[Rule], thresholds: ThresholdConfig) -> EvaluationResult:
    risk_score = 0.0
    trust_score = 0.0
    critical_count = 0
    strong_count = 0
    matched_ids: list[str] = []
    matched_rules: list[Rule] = []
    evidence: dict = {}

    for rule in rules:
        if not rule.enabled:
            continue
        fired, ev = _rule_fires(rule, feature_row)
        if not fired:
            continue
        matched_ids.append(rule.rule_id)
        matched_rules.append(rule)
        evidence[rule.rule_id] = ev
        if rule.severity == TRUST_CATEGORY:
            trust_score += rule.weight
        else:
            risk_score += rule.weight
            if rule.severity == "critical":
                critical_count += 1
            elif rule.severity == "strong":
                strong_count += 1

    if critical_count >= thresholds.critical_rule_min:
        label = "likely_scam"
    elif risk_score >= thresholds.strong_risk_score_min and strong_count >= thresholds.strong_rule_count_min:
        label = "likely_scam"
    elif risk_score >= thresholds.suspicious_risk_score_min:
        label = "suspicious"
    elif (risk_score <= thresholds.legitimate_risk_score_max
          and trust_score >= thresholds.legitimate_trust_score_min
          and strong_count == 0 and critical_count == 0):
        label = "likely_legitimate"
    else:
        label = "insufficient_evidence"

    confidence = _confidence_tier(label, trust_score, critical_count, strong_count, len(matched_ids), thresholds)
    non_trust = [r for r in matched_rules if r.severity != TRUST_CATEGORY]
    reason = _build_reason(label, non_trust or matched_rules, risk_score, trust_score)

    return EvaluationResult(
        listing_id=feature_row["listing_id"], risk_score=risk_score, trust_score=trust_score,
        critical_rule_count=critical_count, strong_rule_count=strong_count,
        matched_rule_ids=matched_ids, evidence=evidence, rule_label=label,
        label_confidence=confidence, label_reason=reason,
    )
