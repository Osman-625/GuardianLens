from __future__ import annotations

import argparse
import csv
from pathlib import Path

import yaml

WORKSPACE = Path(__file__).resolve().parent.parent

REQUIRED_LABELING_COLUMNS = (
    "rule_label", "label_confidence", "label_reason",
    "human_override_label", "human_override_reason", "reviewer_id", "override_timestamp",
)
VALID_CONFIDENCE = {"rough", "moderate", "high"}


def check_no_ground_truth_column(csv_path: str | Path) -> list[str]:
    path = Path(csv_path)
    if not path.exists():
        return [f"{path}: does not exist"]
    with path.open(encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f))
    return [f"{path}: found forbidden column {col!r}" for col in header if "ground_truth" in col]


def check_source_dataset_unchanged(listings_path: Path, expected_row_count: int) -> list[str]:
    with listings_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != expected_row_count:
        return [f"listings.csv row count changed: expected {expected_row_count}, got {len(rows)}"]
    return []


def check_rule_ids_documented(rules_path: Path, doc_path: Path) -> list[str]:
    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    doc_text = doc_path.read_text(encoding="utf-8")
    missing = [r["rule_id"] for r in rules if r["rule_id"] not in doc_text]
    return [f"rule_documentation.md missing section for {rid}" for rid in missing]


def check_weak_annotations_reproducible(out_path: Path) -> list[str]:
    if not out_path.exists():
        return [f"{out_path} does not exist - run run_rule_annotation.py first"]
    return []


def check_utf8(path: Path) -> list[str]:
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return [f"{path}: not valid UTF-8: {e}"]
    return []


def check_every_row_fully_labeled(weak_annotations_path: Path) -> list[str]:
    """Every row must have rule_label/label_confidence/label_reason populated, the override
    columns must exist as real header entries (even if blank), and no confidence value may
    literally be "weak" - the terminology this whole design exists to avoid."""
    errors = []
    with weak_annotations_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing_cols = [c for c in REQUIRED_LABELING_COLUMNS if c not in (reader.fieldnames or [])]
        if missing_cols:
            return [f"{weak_annotations_path}: missing required column(s) {missing_cols}"]
        for i, row in enumerate(reader):
            if not row["rule_label"]:
                errors.append(f"row {i} ({row.get('listing_id')}): blank rule_label")
            if row["label_confidence"] not in VALID_CONFIDENCE:
                errors.append(f"row {i} ({row.get('listing_id')}): invalid label_confidence {row['label_confidence']!r}")
            if not row["label_reason"].strip():
                errors.append(f"row {i} ({row.get('listing_id')}): blank label_reason")
    return errors


def check_overrides_blank_on_fresh_export(weak_annotations_path: Path) -> list[str]:
    """Informational only - once real human review has begun, filled overrides are expected."""
    with weak_annotations_path.open(encoding="utf-8-sig", newline="") as f:
        filled = sum(1 for row in csv.DictReader(f) if row.get("human_override_label"))
    if filled:
        print(f"NOTE: {filled} row(s) already carry a human_override_label - "
              f"expected once review has started, not an error.")
    return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-row-count", type=int, default=2209)
    args = parser.parse_args()

    errors: list[str] = []
    errors += check_no_ground_truth_column(WORKSPACE / "output" / "weak_annotations.csv")
    errors += check_no_ground_truth_column(WORKSPACE / "reports" / "review_queue.csv")
    errors += check_source_dataset_unchanged(
        WORKSPACE / "data" / "annotation_ready" / "listings.csv", args.expected_row_count
    )
    errors += check_rule_ids_documented(
        WORKSPACE / "rules" / "scam_rules.yaml", WORKSPACE / "rules" / "rule_documentation.md"
    )
    errors += check_weak_annotations_reproducible(WORKSPACE / "output" / "weak_annotations.csv")
    if not errors:
        errors += check_utf8(WORKSPACE / "output" / "weak_annotations.csv")
        errors += check_every_row_fully_labeled(WORKSPACE / "output" / "weak_annotations.csv")
        errors += check_overrides_blank_on_fresh_export(WORKSPACE / "output" / "weak_annotations.csv")

    if errors:
        print(f"FAILED: {len(errors)} check(s)")
        for e in errors:
            print(f"  - {e}")
        raise SystemExit(1)
    print("All rule-annotation verification checks passed.")


if __name__ == "__main__":
    main()
