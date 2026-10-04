from pathlib import Path

from scripts.verify_annotations import load_schema, verify_annotation_file

WORKSPACE = Path(__file__).resolve().parent.parent


def test_old_schema_still_uses_annotator_id_and_evidence_reason():
    schema = load_schema()
    assert schema.get("id_field", "annotator_id") == "annotator_id"
    assert schema.get("required_evidence_field", "evidence_reason") == "evidence_reason"


def test_pilot_schema_uses_annotator_and_reason():
    schema = load_schema(WORKSPACE / "annotation" / "guidelines" / "pilot_schema.json")
    assert schema["id_field"] == "annotator"
    assert schema["required_evidence_field"] == "reason"


def test_blank_claude_pilot_template_validates_cleanly_against_pilot_schema():
    schema = load_schema(WORKSPACE / "annotation" / "guidelines" / "pilot_schema.json")
    listing_ids = {
        "3655e11b-6ad0-4aac-8baa-343bb09dea36",
    }
    # Blank rows (no label filled) must produce zero errors -- the validator only checks
    # filled rows, matching the existing verify_annotations.py behavior on blank templates.
    errors = verify_annotation_file(
        WORKSPACE / "annotation" / "pilot" / "claude_pilot.csv", schema, listing_ids | _live_ids()
    )
    assert errors == []


def _live_ids() -> set[str]:
    import csv

    with (WORKSPACE / "data" / "annotation_ready" / "listings.csv").open(
        encoding="utf-8-sig", newline=""
    ) as f:
        return {row["listing_id"] for row in csv.DictReader(f)}
