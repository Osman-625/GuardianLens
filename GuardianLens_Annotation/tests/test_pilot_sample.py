from pathlib import Path
import csv

from scripts.select_pilot_sample import validate_pilot_sample

WORKSPACE = Path(__file__).resolve().parent.parent


def test_recovered_pilot_sample_is_valid_against_live_listings():
    errors = validate_pilot_sample(
        WORKSPACE / "annotation" / "pilot" / "pilot_listing_ids.csv",
        WORKSPACE / "data" / "annotation_ready" / "listings.csv",
    )
    assert errors == []


def test_pilot_sample_has_120_rows_and_15_reused_image_cases():
    with (WORKSPACE / "annotation" / "pilot" / "pilot_listing_ids.csv").open(
        encoding="utf-8-sig", newline=""
    ) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 120
    reused = sum(1 for r in rows if r["reused_image_indicator"].strip().lower() == "true")
    assert reused >= 15
