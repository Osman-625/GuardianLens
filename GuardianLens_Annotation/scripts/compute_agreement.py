"""Compute inter-annotator agreement between two filled annotation CSVs.

Usage:
    python scripts/compute_agreement.py --a annotation/pilot/claude_pilot.csv --b annotation/pilot/codex_pilot.csv

Reports: raw percent agreement and Cohen's kappa on the `label` column (chance-
corrected -- the metric to actually look at, not raw agreement, since label
distribution is unlikely to be uniform). Also reports simple percent agreement
on each boolean indicator column. Rows where either annotator left `label`
blank are skipped and reported separately (not counted as disagreement).
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

LABEL_VALUES = ["legitimate", "suspicious", "scam_fraud", "insufficient_evidence"]
INDICATOR_FIELDS = [
    "suspicious_text", "suspicious_image", "suspicious_seller_behaviour",
    "reused_image_indicator", "price_anomaly_indicator",
]


def load(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return {row["listing_id"]: row for row in csv.DictReader(f)}


def cohens_kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    if n == 0:
        return float("nan")
    po = sum(1 for a, b in pairs if a == b) / n
    a_counts = Counter(a for a, _ in pairs)
    b_counts = Counter(b for _, b in pairs)
    pe = sum((a_counts.get(v, 0) / n) * (b_counts.get(v, 0) / n) for v in LABEL_VALUES)
    if pe == 1:
        return 1.0
    return (po - pe) / (1 - pe)


def confusion_matrix(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    matrix: dict[tuple[str, str], int] = {(a, b): 0 for a in LABEL_VALUES for b in LABEL_VALUES}
    for a, b in pairs:
        matrix[(a, b)] = matrix.get((a, b), 0) + 1
    return matrix


def severe_disagreements(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    severe_pair_set = {("legitimate", "scam_fraud"), ("scam_fraud", "legitimate")}
    return [(a, b) for a, b in pairs if (a, b) in severe_pair_set]


def confidence_distribution(a_rows: dict, b_rows: dict, common_ids: list[str]) -> dict:
    def stats(rows: dict, ids: list[str]) -> dict:
        vals = [float(rows[i]["confidence"]) for i in ids if rows[i].get("confidence", "").strip()]
        if not vals:
            return {"min": None, "max": None, "mean": None, "n": 0}
        return {"min": min(vals), "max": max(vals), "mean": sum(vals) / len(vals), "n": len(vals)}

    return {"a": stats(a_rows, common_ids), "b": stats(b_rows, common_ids)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True, type=Path)
    parser.add_argument("--b", required=True, type=Path)
    args = parser.parse_args()

    a_rows = load(args.a)
    b_rows = load(args.b)

    common_ids = sorted(set(a_rows) & set(b_rows))
    if set(a_rows) != set(b_rows):
        missing_in_b = set(a_rows) - set(b_rows)
        missing_in_a = set(b_rows) - set(a_rows)
        print(f"WARNING: {len(missing_in_b)} ids in A not in B, {len(missing_in_a)} ids in B not in A", file=sys.stderr)

    label_pairs = []
    skipped_blank = 0
    for lid in common_ids:
        a_label = a_rows[lid].get("label", "").strip()
        b_label = b_rows[lid].get("label", "").strip()
        if not a_label or not b_label:
            skipped_blank += 1
            continue
        label_pairs.append((a_label, b_label))

    print(f"Total shared listing_ids: {len(common_ids)}")
    print(f"Skipped (blank in at least one annotator): {skipped_blank}")
    print(f"Compared (both labeled): {len(label_pairs)}")

    if not label_pairs:
        print("No fully-labeled overlapping rows yet -- nothing to compute.")
        return 0

    agree = sum(1 for a, b in label_pairs if a == b)
    kappa = cohens_kappa(label_pairs)
    print(f"Raw percent agreement (label): {agree}/{len(label_pairs)} = {agree / len(label_pairs):.1%}")
    print(f"Cohen's kappa (label, chance-corrected): {kappa:.3f}")
    print("  (< 0.20 slight, 0.21-0.40 fair, 0.41-0.60 moderate, 0.61-0.80 substantial, > 0.80 almost perfect -- Landis & Koch)")

    print("\nDisagreements by label pair:")
    disagreement_counts = Counter((a, b) for a, b in label_pairs if a != b)
    for (a, b), c in disagreement_counts.most_common():
        print(f"  {a} vs {b}: {c}")

    severe = severe_disagreements(label_pairs)
    print(f"\nSevere (legitimate vs scam_fraud) disagreements: {len(severe)}")
    if severe:
        print("  *** THESE REQUIRE MANDATORY P0 HUMAN REVIEW ***")

    print("\nFull confusion matrix:")
    cm = confusion_matrix(label_pairs)
    header = "  a\\b".ljust(22) + "".join(v.ljust(20) for v in LABEL_VALUES)
    print(header)
    for a in LABEL_VALUES:
        row = f"  {a}".ljust(22) + "".join(str(cm[(a, b)]).ljust(20) for b in LABEL_VALUES)
        print(row)

    fully_labeled_ids = [lid for lid in common_ids if a_rows[lid].get("label", "").strip() and b_rows[lid].get("label", "").strip()]
    conf_dist = confidence_distribution(a_rows, b_rows, fully_labeled_ids)
    print(f"\nConfidence distribution: A={conf_dist['a']}, B={conf_dist['b']}")

    print("\nIndicator column agreement (raw %; only for columns present in both files):")
    present_indicator_fields = [
        f for f in INDICATOR_FIELDS
        if f in (next(iter(a_rows.values())).keys() if a_rows else []) and f in (next(iter(b_rows.values())).keys() if b_rows else [])
    ]
    for field in present_indicator_fields:
        pairs = [
            (a_rows[lid].get(field, "").strip(), b_rows[lid].get(field, "").strip())
            for lid in common_ids
            if a_rows[lid].get("label", "").strip() and b_rows[lid].get("label", "").strip()
        ]
        if not pairs:
            continue
        agree_n = sum(1 for x, y in pairs if x == y)
        print(f"  {field}: {agree_n}/{len(pairs)} = {agree_n / len(pairs):.1%}")
    if not present_indicator_fields:
        print("  (neither file has the old boolean indicator columns -- expected for the new pilot schema)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
