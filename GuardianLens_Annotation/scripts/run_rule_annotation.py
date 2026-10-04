from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
# Running this file directly (`python scripts/run_rule_annotation.py`) makes Python put
# scripts/ itself on sys.path, not the workspace root - so `from scripts.rule_engine...`
# would fail. Insert the workspace root explicitly so the absolute import always resolves,
# whether invoked as a script or via `python -m scripts.run_rule_annotation`.
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from scripts.rule_engine.config import load_rules, load_thresholds  # noqa: E402
from scripts.rule_engine.evaluator import evaluate_listing  # noqa: E402
RULE_VERSION = "rule_based_v1"

BOOL_FIELDS = (
    "has_whatsapp", "has_telegram", "has_external_contact", "has_advance_payment_language",
    "has_advance_payment_weak", "has_advance_payment_strong",
    "has_direct_transfer_language", "has_agent_fee_language", "has_fake_payment_language",
    "has_credential_request", "has_impersonation_language", "has_urgency_language",
)
INT_FIELDS = (
    "account_age_days", "review_count", "image_count", "cross_listing_duplicate_count",
    "description_duplicate_count", "active_listing_count", "external_url_count",
)
FLOAT_FIELDS = ("seller_rating", "price", "price_ratio", "category_price_median")
LIST_FIELDS = ("cross_listing_related_ids", "description_related_ids")

OVERRIDE_COLUMNS = ("human_override_label", "human_override_reason", "reviewer_id", "override_timestamp")


def _row_to_types(row: dict) -> dict:
    out = dict(row)
    for key in BOOL_FIELDS:
        out[key] = out.get(key) == "True"
    for key in INT_FIELDS:
        v = out.get(key)
        out[key] = int(float(v)) if v not in (None, "", "None") else None
    for key in FLOAT_FIELDS:
        v = out.get(key)
        out[key] = float(v) if v not in (None, "", "None") else None
    for key in LIST_FIELDS:
        raw = out.get(key)
        out[key] = ast.literal_eval(raw) if raw not in (None, "", "None") else []
    return out


def _preserve_existing_human_overrides(out_rows: list[dict], out_path: Path) -> None:
    """Rerunning the rule engine (new rule version, tuned thresholds, refreshed dataset) must
    NEVER silently discard a human's prior overrides. If output/weak_annotations.csv already
    exists, carry forward its human_override_* values by listing_id before the fresh rule-engine
    output is written."""
    if not out_path.exists():
        return
    with out_path.open(encoding="utf-8-sig", newline="") as f:
        existing = {row["listing_id"]: row for row in csv.DictReader(f)}
    carried_forward = 0
    for row in out_rows:
        old = existing.get(row["listing_id"])
        if old and any(old.get(col) for col in OVERRIDE_COLUMNS):
            for col in OVERRIDE_COLUMNS:
                row[col] = old.get(col, "")
            carried_forward += 1
    if carried_forward:
        print(f"Preserved {carried_forward} existing human override(s) from {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", default=str(WORKSPACE / "output" / "annotation_features.csv"))
    parser.add_argument("--rules", default=str(WORKSPACE / "rules" / "scam_rules.yaml"))
    parser.add_argument("--thresholds", default=str(WORKSPACE / "rules" / "thresholds.yaml"))
    parser.add_argument("--out", default=str(WORKSPACE / "output" / "weak_annotations.csv"))
    parser.add_argument("--reports-dir", default=str(WORKSPACE / "reports"))
    args = parser.parse_args()

    rules = load_rules(args.rules)
    thresholds = load_thresholds(args.thresholds)

    with open(args.features, encoding="utf-8-sig", newline="") as f:
        feature_rows = [_row_to_types(r) for r in csv.DictReader(f)]

    label_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {"rough": 0, "moderate": 0, "high": 0}
    rule_fire_counts: dict[str, int] = {rule.rule_id: 0 for rule in rules}
    out_rows = []
    matches_rows = []

    total = len(feature_rows)
    for index, feature_row in enumerate(feature_rows, 1):
        if index == 1 or index % 200 == 0 or index == total:
            print(f"[RULES] {index}/{total} listings evaluated", flush=True)
        result = evaluate_listing(feature_row, rules, thresholds)
        label_counts[result.rule_label] = label_counts.get(result.rule_label, 0) + 1
        confidence_counts[result.label_confidence] += 1
        for rid in result.matched_rule_ids:
            rule_fire_counts[rid] += 1
            matches_rows.append({
                "listing_id": result.listing_id, "rule_id": rid,
                "evidence": json.dumps(result.evidence[rid], ensure_ascii=False, default=str),
            })
        out_rows.append({
            "listing_id": result.listing_id,
            "rule_label": result.rule_label,
            "label_confidence": result.label_confidence,
            "label_reason": result.label_reason,
            "risk_score": result.risk_score,
            "trust_score": result.trust_score,
            "critical_rule_count": result.critical_rule_count,
            "strong_rule_count": result.strong_rule_count,
            "matched_rule_ids": json.dumps(result.matched_rule_ids),
            "evidence": json.dumps(result.evidence, ensure_ascii=False, default=str),
            "annotation_source": RULE_VERSION,
            "human_override_label": "",
            "human_override_reason": "",
            "reviewer_id": "",
            "override_timestamp": "",
        })

    out_path = Path(args.out)
    _preserve_existing_human_overrides(out_rows, out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        writer.writeheader()
        writer.writerows(out_rows)

    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    with (reports_dir / "rule_matches.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["listing_id", "rule_id", "evidence"])
        writer.writeheader()
        writer.writerows(matches_rows)

    total = len(feature_rows)
    with (reports_dir / "rule_coverage.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rule_id", "fire_count", "coverage_pct"])
        for rid, count in sorted(rule_fire_counts.items(), key=lambda kv: -kv[1]):
            writer.writerow([rid, count, round(100 * count / total, 2) if total else 0])

    summary = {
        "rule_version": RULE_VERSION,
        "total_listings": total,
        "label_counts": label_counts,
        "confidence_counts": confidence_counts,
        "most_common_rules": sorted(rule_fire_counts.items(), key=lambda kv: -kv[1])[:10],
    }
    (reports_dir / "annotation_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
