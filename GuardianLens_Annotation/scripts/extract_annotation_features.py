from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import yaml

WORKSPACE = Path(__file__).resolve().parent.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from scripts.rule_engine.image_evidence import build_listing_to_related, load_cross_listing_groups  # noqa: E402
from scripts.rule_engine.keyword_matcher import match_keywords  # noqa: E402
from scripts.rule_engine.price_stats import compute_category_medians, price_ratio_and_score  # noqa: E402
from scripts.rule_engine.text_similarity import find_near_duplicate_groups, normalize_for_comparison  # noqa: E402


def _to_float_or_none(value) -> float | None:
    return float(value) if value not in (None, "") else None


def _to_int_or_none(value) -> int | None:
    return int(float(value)) if value not in (None, "") else None


def extract_features(listings_path, image_validation_path, validation_summary_path) -> list[dict]:
    patterns = yaml.safe_load((WORKSPACE / "rules" / "keyword_patterns.yaml").read_text(encoding="utf-8"))

    with open(listings_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    medians = compute_category_medians(rows)
    groups = load_cross_listing_groups(validation_summary_path)
    related_map = build_listing_to_related(groups)

    normalized_text = {r["listing_id"]: normalize_for_comparison(r.get("description") or "") for r in rows}
    duplicate_map = find_near_duplicate_groups(normalized_text)

    features = []
    total = len(rows)
    for index, row in enumerate(rows, 1):
        if index == 1 or index % 200 == 0 or index == total:
            print(f"[FEATURES] {index}/{total} listings processed", flush=True)
        lid = row["listing_id"]
        text = f"{row.get('title', '')} {row.get('description', '')}"
        matches = match_keywords(text, patterns)
        match_categories = {m.category for m in matches}
        strengths_by_category: dict[str, set[str]] = {}
        for m in matches:
            strengths_by_category.setdefault(m.category, set()).add(m.strength)
        advance_payment_strengths = strengths_by_category.get("advance_payment", set())
        # Strong-tier advance-payment phrases (e.g. "deposit RM200 first") subsume the bare
        # "deposit" weak tier - mutually exclusive so B1/B2 in scam_rules.yaml never both fire
        # for the same signal.
        has_advance_payment_strong = "strong" in advance_payment_strengths
        has_advance_payment_weak = "weak" in advance_payment_strengths and not has_advance_payment_strong

        price = _to_float_or_none(row.get("price")) if row.get("price_missing") != "True" else None
        price_ratio, price_anomaly_score = price_ratio_and_score(
            price, row.get("category"), row.get("platform"), medians
        )

        related = related_map.get(lid, set())
        dup_related = duplicate_map.get(lid, [])

        features.append({
            "listing_id": lid,
            "platform": row.get("platform"),
            "has_phone_reference": None,  # PII type not recoverable - see Phase-1 limitation
            "has_whatsapp": "off_platform_contact" in match_categories,
            "has_telegram": any("telegram" in p.lower() for m in matches for p in m.matched_phrases),
            "has_external_contact": "off_platform_contact" in match_categories,
            "external_url_count": text.lower().count("http"),
            "suspicious_url_count": None,  # url_suspicious not implemented yet - see G1 in scam_rules.yaml
            "has_advance_payment_language": "advance_payment" in match_categories,
            "has_advance_payment_weak": has_advance_payment_weak,
            "has_advance_payment_strong": has_advance_payment_strong,
            "has_direct_transfer_language": "advance_payment" in match_categories,
            "has_agent_fee_language": "agent_courier_release_fee" in match_categories,
            "has_fake_payment_language": "fake_payment_confirmation" in match_categories,
            "has_credential_request": "credential_request" in match_categories,
            "has_impersonation_language": "impersonation" in match_categories,
            "has_urgency_language": "urgency_language" in match_categories,
            "account_age_days": _to_int_or_none(row.get("account_age_days")) if row.get("account_age_missing") != "True" else None,
            "seller_rating": _to_float_or_none(row.get("seller_rating")) if row.get("seller_rating_missing") != "True" else None,
            "review_count": _to_int_or_none(row.get("review_count")) if row.get("review_count_missing") != "True" else None,
            "active_listing_count": _to_int_or_none(row.get("active_listing_count")) if row.get("active_listing_count_missing") != "True" else None,
            "price": price,
            "category_price_median": medians.get((row.get("category"), row.get("platform"))),
            "price_ratio": price_ratio,
            "price_anomaly_score": price_anomaly_score,
            "image_count": _to_int_or_none(row.get("image_count")),
            "cross_listing_duplicate_count": len(related),
            "cross_listing_related_ids": sorted(related),
            "description_duplicate_count": len(dup_related),
            "description_related_ids": sorted(dup_related),
            "semak_mule_checked": None,
            "semak_mule_phone_hit": None,
            "semak_mule_bank_hit": None,
        })
    return features


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listings", default=str(WORKSPACE / "data" / "annotation_ready" / "listings.csv"))
    parser.add_argument("--image-validation", default=str(WORKSPACE / "reports" / "image_validation.csv"))
    parser.add_argument("--validation-summary", default=str(WORKSPACE / "reports" / "dataset_validation_summary.json"))
    parser.add_argument("--out", default=str(WORKSPACE / "output" / "annotation_features.csv"))
    args = parser.parse_args()

    features = extract_features(args.listings, args.image_validation, args.validation_summary)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(features[0].keys()))
        writer.writeheader()
        writer.writerows(features)
    print(f"Wrote {len(features)} feature rows to {out_path}")


if __name__ == "__main__":
    main()
