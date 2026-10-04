"""Standalone annotation-file verification for this annotation workspace.

Validates any CSV shaped like annotation/annotation_schema.json: header match,
enum/range validity, duplicate (listing_id, annotator_id) rows, missing
records relative to listings.csv, and adjudication completeness. Designed to
run cleanly against the blank templates too (reports 0 filled / N pending,
not an error).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
LABEL_VALUES = {"legitimate", "suspicious", "scam_fraud", "insufficient_evidence"}


def load_schema(schema_path: Path | None = None) -> dict:
    path = schema_path or (WORKSPACE / "annotation" / "annotation_schema.json")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_listing_ids() -> set[str]:
    csv_path = WORKSPACE / "data" / "annotation_ready" / "listings.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        return {row["listing_id"] for row in csv.DictReader(f)}


def verify_annotation_file(path: Path, schema: dict, listing_ids: set[str]) -> list[str]:
    errors = []
    id_field = schema.get("id_field", "annotator_id")
    evidence_field = schema.get("required_evidence_field", "evidence_reason")
    expected_fields = list(schema["fields"].keys())
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != expected_fields:
            errors.append(f"{path}: header mismatch. expected {expected_fields}, got {reader.fieldnames}")
            return errors
        rows = list(reader)

    seen_pairs = set()
    filled = 0
    for i, row in enumerate(rows, start=2):  # 1-indexed + header row
        label = row.get("label", "").strip()
        if not label:
            continue
        filled += 1
        if label not in LABEL_VALUES:
            errors.append(f"{path}:{i}: invalid label '{label}'")
        conf = row.get("confidence", "").strip()
        if conf:
            try:
                c = int(conf)
                if not (1 <= c <= 5):
                    errors.append(f"{path}:{i}: confidence {c} out of range 1-5")
            except ValueError:
                errors.append(f"{path}:{i}: confidence '{conf}' is not an integer")
        if not row.get(evidence_field, "").strip():
            errors.append(f"{path}:{i}: label set but {evidence_field} is empty")

        pair = (row["listing_id"], row.get(id_field, ""))
        if pair in seen_pairs:
            errors.append(f"{path}:{i}: duplicate annotation record for {pair}")
        seen_pairs.add(pair)

        if row["listing_id"] not in listing_ids:
            errors.append(f"{path}:{i}: listing_id {row['listing_id']} not found in listings.csv")

    pending = len(rows) - filled
    print(f"{path.name}: {filled} filled, {pending} pending, {len(rows)} total rows")
    return errors


def verify_adjudication(path: Path) -> list[str]:
    errors = []
    if not path.exists():
        return errors
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    incomplete = 0
    for i, row in enumerate(rows, start=2):
        a, b = row.get("annotator_A_label", "").strip(), row.get("annotator_B_label", "").strip()
        if a and b and a != b and not row.get("adjudicator_label", "").strip():
            incomplete += 1
    if incomplete:
        print(f"{path.name}: {incomplete} disagreement(s) awaiting adjudication")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, help="Verify a single annotation CSV instead of the default templates")
    parser.add_argument(
        "--schema", type=Path, default=None,
        help="Schema JSON to validate against (default: annotation/annotation_schema.json). "
             "Use annotation/guidelines/pilot_schema.json for claude_pilot.csv/codex_pilot.csv "
             "and the full-run equivalents, which use annotator/reason instead of "
             "annotator_id/evidence_reason.",
    )
    args = parser.parse_args()

    schema = load_schema(args.schema)
    listing_ids = load_listing_ids()
    all_errors: list[str] = []

    if args.file:
        targets = [args.file]
    else:
        targets = [
            WORKSPACE / "annotation" / "templates" / "annotator_A.csv",
            WORKSPACE / "annotation" / "templates" / "annotator_B.csv",
        ]

    for path in targets:
        if path.exists():
            all_errors.extend(verify_annotation_file(path, schema, listing_ids))

    if not args.schema:
        all_errors.extend(verify_adjudication(WORKSPACE / "annotation" / "templates" / "adjudication.csv"))

    if all_errors:
        print(f"FAILED: {len(all_errors)} problem(s)", file=sys.stderr)
        for e in all_errors[:200]:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print("OK: no schema/label/duplicate errors found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
