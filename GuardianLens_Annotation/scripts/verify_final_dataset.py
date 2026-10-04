"""Final integrity checklist before freezing the labeled dataset (this task's spec section 14)."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
VALID_LABELS = {"legitimate", "suspicious", "scam_fraud", "insufficient_evidence"}


def run_checks(final_rows: list[dict], listing_ids: set[str]) -> list[str]:
    errors: list[str] = []

    ids_seen = [r["listing_id"] for r in final_rows]
    dupes = [lid for lid, count in Counter(ids_seen).items() if count > 1]
    if dupes:
        errors.append(f"duplicate listing_id rows found: {dupes}")

    for r in final_rows:
        label = r.get("final_label")
        if label and label not in VALID_LABELS:
            errors.append(f"{r['listing_id']}: invalid final_label {label!r}")

    final_ids = set(ids_seen)
    missing_from_final = listing_ids - final_ids
    extra_in_final = final_ids - listing_ids
    if missing_from_final:
        errors.append(
            f"{len(missing_from_final)} listing_ids missing from final dataset: {sorted(missing_from_final)[:5]}..."
        )
    if extra_in_final:
        errors.append(
            f"{len(extra_in_final)} listing_ids in final dataset not in source listings.csv: {sorted(extra_in_final)[:5]}..."
        )

    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", required=True, type=Path)
    parser.add_argument("--listings", default=str(WORKSPACE / "data" / "annotation_ready" / "listings.csv"), type=Path)
    args = parser.parse_args()

    with args.final.open(encoding="utf-8-sig", newline="") as f:
        final_rows = list(csv.DictReader(f))
    with args.listings.open(encoding="utf-8-sig", newline="") as f:
        listing_ids = {row["listing_id"] for row in csv.DictReader(f)}

    errors = run_checks(final_rows, listing_ids)
    unresolved = sum(1 for r in final_rows if r.get("final_label_source") == "unresolved")
    print(f"Checked {len(final_rows)} rows. Unresolved (pending Pass 3): {unresolved}.")
    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        raise SystemExit(1)
    print("All integrity checks passed.")


if __name__ == "__main__":
    main()
