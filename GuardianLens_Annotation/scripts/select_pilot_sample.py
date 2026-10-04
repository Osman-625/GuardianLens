"""Validate the recovered 120-listing Claude/Codex pilot sample against the live dataset.

The sample itself (annotation/pilot/pilot_listing_ids.csv) was recovered from
GuardianLens_Annotation.zip's original dual-human pilot design (105 proportionally stratified by
platform/category + 15 deliberately drawn reused-image stress cases) -- see
reports/annotation_workflow_audit.md and archive/legacy_annotation_workflows/README.md. This
script does not generate a new sample; it confirms the recovered one is still valid against the
current data/annotation_ready/listings.csv before it's used for annotation dispatch.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent


def validate_pilot_sample(pilot_csv_path: Path, listings_csv_path: Path) -> list[str]:
    errors: list[str] = []
    with Path(listings_csv_path).open(encoding="utf-8-sig", newline="") as f:
        live_ids = {row["listing_id"] for row in csv.DictReader(f)}

    with Path(pilot_csv_path).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if len(rows) != 120:
        errors.append(f"expected 120 pilot rows, found {len(rows)}")

    missing = [r["listing_id"] for r in rows if r["listing_id"] not in live_ids]
    if missing:
        errors.append(
            f"{len(missing)} pilot listing_ids no longer exist in live listings.csv: {missing[:5]}..."
        )

    reused = sum(
        1 for r in rows if r.get("reused_image_indicator", "").strip().lower() == "true"
    )
    if reused < 15:
        errors.append(f"expected >=15 reused-image stress cases, found {reused}")

    return errors


def main() -> int:
    errs = validate_pilot_sample(
        WORKSPACE / "annotation" / "pilot" / "pilot_listing_ids.csv",
        WORKSPACE / "data" / "annotation_ready" / "listings.csv",
    )
    if errs:
        for e in errs:
            print(f"FAIL: {e}")
        return 1
    print("Pilot sample valid: 120 rows, all listing_ids live, reused-image stress cases present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
