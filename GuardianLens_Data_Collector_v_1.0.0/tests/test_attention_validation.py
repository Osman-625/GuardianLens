from __future__ import annotations

import json

import pytest

from guardianlens.capture import create_capture
from guardianlens.config import settings
from guardianlens.db import connect, now_iso, transaction
from guardianlens.models import CaptureRequest
from guardianlens.openai_extractor import MockExtractor
from guardianlens.processor import process_listing
from guardianlens.review import approve, begin_review, edit_and_approve, get_listing
from guardianlens.validation import (
    REQUIRED_FIELDS, SELLER_SIGNAL_FIELDS, evidence_availability, inspect_listing,
    validate_fields,
)
from conftest import data_url, image_bytes


def _processed(monkeypatch, suffix="810001", payload=None, image_value=116):
    capture = create_capture(CaptureRequest(
        platform="carousell",
        source_url=f"https://www.carousell.com.my/p/validation-{suffix}/",
        page_title="Validation fixture",
        screenshot_data_url=data_url(image_bytes()),
        image_urls=["https://fixture.test/product.jpg"],
        listing_evidence={"h1_text": "Validation fixture", "has_price_signal": True},
    ))
    monkeypatch.setattr(
        "guardianlens.processor.download_image", lambda _: image_bytes((400, 300), value=image_value),
    )
    result = process_listing(capture["listing_id"], MockExtractor(payload))
    return result["listing_id"]


@pytest.mark.parametrize("field", (*REQUIRED_FIELDS, *SELLER_SIGNAL_FIELDS))
def test_required_listing_and_seller_fields_share_one_gate(field):
    payload = MockExtractor().payload.copy()
    payload[field] = None
    findings = validate_fields(payload, ["Audio"])
    assert any(item["code"] == "missing_field" and item["field"] == field for item in findings)


def test_zero_is_valid_and_unknown_is_not_coerced():
    payload = MockExtractor().payload.copy()
    payload.update({field: 0 for field in ("price", *SELLER_SIGNAL_FIELDS)})
    assert validate_fields(payload, [payload["category"]]) == []
    payload["review_count"] = "unknown"
    findings = validate_fields(payload, [payload["category"]])
    assert any(item["code"] == "invalid_type" and item["field"] == "review_count" for item in findings)
    assert payload["review_count"] == "unknown"


@pytest.mark.parametrize("field,value,code", [
    ("price", -1, "invalid_range"),
    ("price", float("inf"), "invalid_range"),
    ("price", 10 ** 500, "invalid_range"),
    ("seller_rating", 5.1, "invalid_range"),
    ("account_age_days", 0.5, "invalid_type"),
    ("active_listing_count", True, "invalid_type"),
    ("title", {"value": "title"}, "invalid_type"),
    ("description", "N/A", "placeholder_value"),
    ("category", "Unconfigured", "category"),
    ("location_state", "   ", "missing_field"),
    ("currency", "seller@example.test", "pii"),
])
def test_invalid_legacy_values_have_structured_findings(field, value, code):
    payload = MockExtractor().payload.copy()
    payload[field] = value
    findings = validate_fields(payload, ["Audio"])
    assert any(item["code"] == code and item["field"] == field for item in findings)
    assert all(item["action"] in {"repair", "capture", "human"} for item in findings)
    assert "seller@example.test" not in json.dumps(findings)


@pytest.mark.parametrize("field", ["location_state", "seller_rating", "review_count"])
def test_location_and_seller_signal_nulls_do_not_block_approval(isolated, monkeypatch, field):
    """location_state and the seller/behavioural fields stay null when genuinely unresolvable
    after evidence-backed repair; the human may still approve rather than being stuck forever."""
    payload = MockExtractor().payload.copy()
    payload[field] = None
    listing_id = _processed(monkeypatch, payload=payload)
    assert get_listing(listing_id)["status"] == "needs_attention"
    with transaction() as con:
        findings = inspect_listing(con, get_listing(listing_id))
        assert any(item["code"] == "missing_field" and item["field"] == field for item in findings)
    begin_review(listing_id)
    approve(listing_id)
    listing = get_listing(listing_id)
    assert listing["status"] == "approved"
    assert listing[field] is None


def test_approval_revalidates_numeric_ranges_and_rolls_back_human_edit(isolated, monkeypatch):
    listing_id = _processed(monkeypatch)
    begin_review(listing_id)
    original = get_listing(listing_id)["seller_rating"]
    with pytest.raises(ValueError, match="seller_rating must be between"):
        edit_and_approve(listing_id, {"seller_rating": 9})
    assert get_listing(listing_id)["seller_rating"] == original


def test_inspection_rechecks_fields_preserves_human_warnings_and_does_not_write(isolated, monkeypatch):
    listing_id = _processed(monkeypatch)
    with transaction() as con:
        for warning_id, code in (("fixed", "missing_field"), ("decision", "near_duplicate_image")):
            con.execute(
                """INSERT INTO warnings(warning_id,listing_id,warning_type,message,created_at)
                   VALUES(?,?,?,?,?)""",
                (warning_id, listing_id, code, "Historical finding", now_iso()),
            )
    con = connect()
    try:
        before = con.total_changes
        findings = inspect_listing(con, get_listing(listing_id))
        assert con.total_changes == before
        assert [item["code"] for item in findings] == ["near_duplicate_image"]
        assert findings[0]["warning_id"] == "decision"
        assert findings[0]["action"] == "human"
    finally:
        con.close()
    begin_review(listing_id)
    approve(listing_id)  # A human may decide the advisory near-duplicate case.
    assert get_listing(listing_id)["status"] == "approved"


def test_seller_missing_evidence_requests_capture_and_unsafe_paths_are_ignored(isolated, monkeypatch):
    payload = MockExtractor().payload.copy()
    payload["seller_rating"] = None
    listing_id = _processed(monkeypatch, payload=payload)
    listing = get_listing(listing_id)
    staged_path = settings.root / listing["staging_text_path"]
    staged = json.loads(staged_path.read_text(encoding="utf-8"))
    staged["seller_visible_text"] = "Seller rating: 4.9"
    con = connect()
    try:
        findings = inspect_listing(con, listing)
        assert next(item for item in findings if item["field"] == "seller_rating")["action"] == "capture"
        staged_path.write_text(json.dumps(staged), encoding="utf-8")
        assert evidence_availability(listing)["seller_text"] is True
        findings = inspect_listing(con, listing)
        assert next(item for item in findings if item["field"] == "seller_rating")["action"] == "repair"
        unsafe_path = isolated / "not-owned-staging.json"
        unsafe_path.write_text(json.dumps(staged), encoding="utf-8")
        listing["staging_text_path"] = str(unsafe_path.relative_to(isolated))
        assert evidence_availability(listing)["seller_text"] is False
    finally:
        con.close()


def test_inspection_reports_image_integrity_and_new_approved_duplicate(isolated, monkeypatch):
    first = _processed(monkeypatch)
    second = _processed(monkeypatch, suffix="810002", image_value=142)
    begin_review(first)
    approve(first)
    listing = get_listing(second)
    image_path = settings.root / listing["images"][0]["storage_path"]
    image_path.write_bytes(b"broken image")
    con = connect()
    try:
        findings = inspect_listing(con, listing)
        assert any(item["code"] == "duplicate_metadata" for item in findings)
        broken = next(item for item in findings if item["code"] == "image")
        assert broken["asset_id"] == listing["images"][0]["image_id"]
        assert "unreadable or invalid" in broken["message"]
    finally:
        con.close()
