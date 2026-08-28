from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from conftest import data_url, image_bytes
from guardianlens.app import app
from guardianlens.batch import BatchManager
from guardianlens.capture import create_capture
from guardianlens.db import connect, now_iso, transaction
from guardianlens.models import CaptureRequest
from guardianlens.replay import (
    CSVImportError,
    ReplayManager,
    create_csv_batch,
    create_manual_batch,
    parse_csv_rows,
)
from guardianlens.security import ensure_local_token


CAROUSELL = "https://www.carousell.com.my/p/phone-case-123456/"
MUDAH = "https://www.mudah.my/camera-kit-654321.htm"


def _capture_payload(url: str, item_id: str | None = None) -> CaptureRequest:
    platform = "carousell" if "carousell" in url else "mudah"
    return CaptureRequest(
        platform=platform,
        source_url=url,
        page_title="Replay fixture listing",
        screenshot_data_url=data_url(image_bytes()),
        image_urls=["https://images.example.test/product.jpg"],
        listing_evidence={"h1_text": "Replay fixture listing", "has_price_signal": True},
        capture_source="csv_batch" if item_id else "extension",
        batch_item_id=item_id,
    )


@pytest.mark.parametrize("column", ["url", "source_url", "listing_url", "product_url"])
def test_csv_parser_supports_common_url_columns(column):
    rows = parse_csv_rows(f"{column}\n{CAROUSELL}\n".encode())
    assert rows == [
        {"row_number": 2, "source_url": CAROUSELL, "platform": "", "category": ""}
    ]


def test_csv_parser_rejects_missing_url_column_and_unreadable_input():
    with pytest.raises(CSVImportError, match="URL column"):
        parse_csv_rows(b"platform,category\ncarousell,Phones\n")
    with pytest.raises(CSVImportError, match="NUL"):
        parse_csv_rows(b"url\nhttps://example.test/\x00")


def test_csv_import_validates_blanks_invalid_domains_and_duplicates(isolated):
    csv_data = (
        "platform,category,url\n"
        f"carousell,Phones,{CAROUSELL}\n"
        ",,\n"
        "carousell,Phones,not-a-url\n"
        "other,Phones,https://example.test/item\n"
        f"carousell,Phones,{CAROUSELL}?utm_source=test\n"
    ).encode()
    result = create_csv_batch(csv_data, "crawler.csv")
    assert result["import_summary"] == {
        "rows": 4,
        "valid_urls": 2,
        "invalid_rows": 2,
        "duplicates_in_import": 1,
        "already_captured": 0,
        "queued": 1,
    }
    con = connect()
    try:
        statuses = [
            row["status"]
            for row in con.execute(
                "SELECT status FROM capture_batch_items ORDER BY row_number"
            )
        ]
    finally:
        con.close()
    assert statuses == ["pending", "invalid", "invalid", "duplicate"]


def test_url_only_csv_detects_platform_and_csv_category_is_preserved(isolated):
    result = create_csv_batch(
        f"category,url\nPhones,{CAROUSELL}\nCameras,{MUDAH}\n".encode(),
        "two-platforms.csv",
        "Mixed marketplace batch",
    )
    assert result["batch"]["name"] == "Mixed marketplace batch"
    con = connect()
    try:
        rows = [
            dict(row)
            for row in con.execute(
                "SELECT platform,category FROM capture_batch_items ORDER BY row_number"
            )
        ]
    finally:
        con.close()
    assert rows == [
        {"platform": "carousell", "category": "Phones"},
        {"platform": "mudah", "category": "Cameras"},
    ]


def test_import_marks_existing_source_as_duplicate(isolated):
    existing = create_capture(_capture_payload(CAROUSELL))
    result = create_csv_batch(f"url\n{CAROUSELL}\n".encode(), "existing.csv")
    assert result["import_summary"]["already_captured"] == 1
    assert result["import_summary"]["queued"] == 0
    con = connect()
    try:
        item = con.execute("SELECT * FROM capture_batch_items").fetchone()
    finally:
        con.close()
    assert item["status"] == "duplicate"
    assert item["listing_id"] == existing["listing_id"]


def test_queue_order_pause_resume_stop_and_failure_isolation(isolated):
    snapshot = create_manual_batch(f"{CAROUSELL}\n{MUDAH}", "Ordered")
    batch_id = snapshot["batch"]["batch_id"]
    manager = ReplayManager()
    manager.start(batch_id)
    manager.command(batch_id, "pause")
    assert manager.claim_next() is None
    manager.command(batch_id, "resume")
    first = manager.claim_next()
    assert first["row_number"] == 1
    manager.update_item(
        first["batch_item_id"],
        status="capture_failed",
        error_type="capture_failed",
        error_message="fixture failure",
    )
    second = manager.claim_next()
    assert second["row_number"] == 2
    stopping = manager.command(batch_id, "stop")
    assert stopping["batch"]["status"] == "stopping"
    final = manager.update_item(
        second["batch_item_id"],
        status="listing_unavailable",
        error_type="listing_unavailable",
        error_message="fixture unavailable",
    )
    assert final["batch"]["status"] == "stopped"
    assert final["progress"]["failed"] == 2
    manager.shutdown()


def test_recovery_checkpoints_interrupted_browser_capture(isolated):
    snapshot = create_manual_batch(CAROUSELL, "Recovery")
    batch_id = snapshot["batch"]["batch_id"]
    first = ReplayManager()
    first.start(batch_id)
    claimed = first.claim_next()
    assert claimed["status"] == "opening"
    first.shutdown()

    recovered = ReplayManager()
    recovered.recover()
    try:
        con = connect()
        try:
            item = con.execute(
                "SELECT * FROM capture_batch_items WHERE batch_item_id=?",
                (claimed["batch_item_id"],),
            ).fetchone()
            attempt = con.execute(
                "SELECT * FROM capture_batch_attempts WHERE batch_item_id=?",
                (claimed["batch_item_id"],),
            ).fetchone()
        finally:
            con.close()
        assert item["status"] == "pending"
        assert item["last_error_type"] == "interrupted_capture"
        assert attempt["status"] == "interrupted"
        assert recovered.claim_next()["attempt_count"] == 2
    finally:
        recovered.shutdown()


def test_stale_browser_claim_is_recovered_without_backend_restart(isolated):
    snapshot = create_manual_batch(CAROUSELL, "Browser restart")
    batch_id = snapshot["batch"]["batch_id"]
    manager = ReplayManager()
    manager.start(batch_id)
    first = manager.claim_next()
    stale_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with transaction() as con:
        con.execute(
            "UPDATE capture_batch_items SET updated_at=? WHERE batch_item_id=?",
            (stale_at, first["batch_item_id"]),
        )
    second = manager.claim_next()
    assert second["batch_item_id"] == first["batch_item_id"]
    assert second["attempt_count"] == 2
    con = connect()
    try:
        attempts = [
            dict(row)
            for row in con.execute(
                "SELECT status,error_type FROM capture_batch_attempts ORDER BY attempt_number"
            )
        ]
    finally:
        con.close()
    assert attempts[0] == {"status": "capture_timeout", "error_type": "capture_timeout"}
    assert attempts[1]["status"] == "opening"
    manager.shutdown()


def test_retry_failed_obeys_max_attempts(isolated):
    snapshot = create_manual_batch(CAROUSELL, "Retry")
    batch_id = snapshot["batch"]["batch_id"]
    manager = ReplayManager()
    manager.start(batch_id)
    first = manager.claim_next()
    manager.update_item(first["batch_item_id"], status="capture_failed", error_message="one")
    retried = manager.retry_failed(batch_id)
    assert retried["retried"] == 1
    second = manager.claim_next()
    assert second["attempt_count"] == 2
    manager.update_item(second["batch_item_id"], status="capture_failed", error_message="two")
    with pytest.raises(RuntimeError, match="attempt limit"):
        manager.retry_failed(batch_id)
    manager.shutdown()


def test_replay_capture_uses_existing_capture_request_and_stores_provenance(isolated):
    snapshot = create_csv_batch(
        f"platform,category,url\ncarousell,Phones,{CAROUSELL}\n".encode(),
        "provenance.csv",
    )
    batch_id = snapshot["batch"]["batch_id"]
    manager = ReplayManager()
    manager.start(batch_id)
    item = manager.claim_next()
    manager.update_item(item["batch_item_id"], status="capturing")
    capture = create_capture(_capture_payload(CAROUSELL, item["batch_item_id"]))
    con = connect()
    try:
        listing = con.execute(
            "SELECT * FROM listings WHERE listing_id=?", (capture["listing_id"],)
        ).fetchone()
    finally:
        con.close()
    assert listing["capture_source"] == "csv_batch"
    assert listing["capture_batch_id"] == batch_id
    assert listing["csv_row"] == 2
    assert listing["original_csv_filename"] == "provenance.csv"
    assert listing["source_category"] == "Phones"
    queue_item = connect()
    try:
        linked = queue_item.execute(
            "SELECT status,listing_id FROM capture_batch_items WHERE batch_item_id=?",
            (item["batch_item_id"],),
        ).fetchone()
    finally:
        queue_item.close()
    assert linked["status"] == "capturing"
    assert linked["listing_id"] == capture["listing_id"]
    manager.shutdown()


def test_committed_capture_survives_lost_browser_acknowledgement(isolated, monkeypatch):
    snapshot = create_manual_batch(CAROUSELL, "Lost acknowledgement")
    batch_id = snapshot["batch"]["batch_id"]

    def fake_process(listing_id, **_kwargs):
        with transaction() as con:
            con.execute(
                "UPDATE listings SET status='ready_for_review',updated_at=? WHERE listing_id=?",
                (now_iso(), listing_id),
            )
        return {"listing_id": listing_id, "status": "ready_for_review"}

    monkeypatch.setattr("guardianlens.replay.process_listing", fake_process)
    manager = ReplayManager()
    manager.start(batch_id)
    item = manager.claim_next()
    manager.update_item(item["batch_item_id"], status="capturing")
    capture = create_capture(_capture_payload(CAROUSELL, item["batch_item_id"]))

    # Simulate the browser losing the successful /api/capture response and reporting failure.
    manager.update_item(
        item["batch_item_id"],
        status="capture_failed",
        error_type="capture_failed",
        error_message="connection closed before acknowledgement",
    )
    try:
        for _ in range(100):
            final = manager.status(batch_id)
            if final["batch"]["status"] == "completed":
                break
            time.sleep(0.02)
        assert final["progress"]["successful"] == 1
        assert final["progress"]["failed"] == 0
        assert final["current"] is None
        con = connect()
        try:
            linked = con.execute(
                "SELECT status,listing_id,last_error_type FROM capture_batch_items WHERE batch_item_id=?",
                (item["batch_item_id"],),
            ).fetchone()
        finally:
            con.close()
        assert linked["status"] == "ready_for_review"
        assert linked["listing_id"] == capture["listing_id"]
        assert linked["last_error_type"] is None
    finally:
        manager.shutdown()


def test_restart_recovers_capture_committed_before_queue_ack(isolated, monkeypatch):
    snapshot = create_manual_batch(CAROUSELL, "Committed capture recovery")
    batch_id = snapshot["batch"]["batch_id"]
    first = ReplayManager()
    first.start(batch_id)
    item = first.claim_next()
    first.update_item(item["batch_item_id"], status="capturing")
    create_capture(_capture_payload(CAROUSELL, item["batch_item_id"]))
    first.shutdown()

    def fake_process(listing_id, **_kwargs):
        with transaction() as con:
            con.execute(
                "UPDATE listings SET status='needs_attention',updated_at=? WHERE listing_id=?",
                (now_iso(), listing_id),
            )
        return {"listing_id": listing_id, "status": "needs_attention"}

    monkeypatch.setattr("guardianlens.replay.process_listing", fake_process)
    recovered = ReplayManager()
    recovered.recover()
    try:
        for _ in range(100):
            final = recovered.status(batch_id)
            if final["batch"]["status"] == "completed":
                break
            time.sleep(0.02)
        assert final["progress"]["successful"] == 1
        assert final["progress"]["failed"] == 0
        con = connect()
        try:
            attempt = con.execute(
                "SELECT status,error_type FROM capture_batch_attempts WHERE batch_item_id=?",
                (item["batch_item_id"],),
            ).fetchone()
        finally:
            con.close()
        assert attempt["status"] == "captured"
        assert attempt["error_type"] is None
    finally:
        recovered.shutdown()


def test_manual_processing_batch_does_not_race_an_active_replay_capture(isolated, monkeypatch):
    snapshot = create_manual_batch(CAROUSELL, "No race")
    replay = ReplayManager()
    replay.start(snapshot["batch"]["batch_id"])
    item = replay.claim_next()
    create_capture(_capture_payload(item["source_url"], item["batch_item_id"]))
    calls = []

    def fake_process(listing_id, **_kwargs):
        calls.append(listing_id)
        return {"listing_id": listing_id, "status": "ready_for_review"}

    monkeypatch.setattr("guardianlens.batch.process_listing", fake_process)
    processor = BatchManager()
    processor.start(None, 1)
    for _ in range(100):
        status = processor.status()
        if status["latest_run"]["status"] == "completed":
            break
        time.sleep(0.01)
    assert calls == []
    assert status["latest_run"]["attempted"] == 0
    replay.shutdown()


def test_processing_failure_does_not_stop_next_replay_item(isolated, monkeypatch):
    snapshot = create_manual_batch(f"{CAROUSELL}\n{MUDAH}", "Isolation")
    batch_id = snapshot["batch"]["batch_id"]
    calls = []

    def fake_process(listing_id, **_kwargs):
        calls.append(listing_id)
        if len(calls) == 1:
            raise RuntimeError("one listing failed")
        with transaction() as con:
            con.execute(
                "UPDATE listings SET status='ready_for_review',updated_at=? WHERE listing_id=?",
                (now_iso(), listing_id),
            )
        return {"listing_id": listing_id, "status": "ready_for_review"}

    monkeypatch.setattr("guardianlens.replay.process_listing", fake_process)
    manager = ReplayManager()
    manager.recover()
    manager.start(batch_id)
    try:
        first = manager.claim_next()
        first_capture = create_capture(_capture_payload(first["source_url"], first["batch_item_id"]))
        manager.update_item(
            first["batch_item_id"], status="captured", listing_id=first_capture["listing_id"]
        )
        for _ in range(100):
            if manager.status(batch_id)["progress"]["failed"] == 1:
                break
            time.sleep(0.02)
        second = manager.claim_next()
        assert second and second["row_number"] == 2
        second_capture = create_capture(_capture_payload(second["source_url"], second["batch_item_id"]))
        manager.update_item(
            second["batch_item_id"], status="captured", listing_id=second_capture["listing_id"]
        )
        for _ in range(100):
            final = manager.status(batch_id)
            if final["batch"]["status"] == "completed":
                break
            time.sleep(0.02)
        assert len(calls) == 2
        assert final["progress"]["failed"] == 1
        assert final["progress"]["successful"] == 1
    finally:
        manager.shutdown()


def test_csv_capture_enters_same_processing_and_human_review_ui(isolated, monkeypatch):
    from guardianlens.openai_extractor import MockExtractor
    from guardianlens.processor import process_listing as shared_process_listing

    monkeypatch.setattr(
        "guardianlens.processor.download_image",
        lambda _url: image_bytes((400, 300), value=126),
    )
    monkeypatch.setattr(
        "guardianlens.replay.process_listing",
        lambda listing_id: shared_process_listing(listing_id, MockExtractor()),
    )
    snapshot = create_csv_batch(f"url\n{CAROUSELL}\n".encode(), "review-flow.csv")
    batch_id = snapshot["batch"]["batch_id"]
    manager = ReplayManager()
    manager.start(batch_id)
    try:
        item = manager.claim_next()
        manager.update_item(item["batch_item_id"], status="capturing")
        capture = create_capture(_capture_payload(CAROUSELL, item["batch_item_id"]))
        manager.update_item(
            item["batch_item_id"], status="captured", listing_id=capture["listing_id"]
        )
        for _ in range(100):
            final = manager.status(batch_id)
            if final["batch"]["status"] == "completed":
                break
            time.sleep(0.02)
        assert final["progress"]["successful"] == 1

        with TestClient(app) as client:
            queue = client.get("/api/review/queue").json()
            assert capture["listing_id"] in {row["listing_id"] for row in queue["rows"]}
            detail = client.post(
                f"/review/{capture['listing_id']}/begin",
                data={"token": ensure_local_token()},
                follow_redirects=True,
            )
            assert detail.status_code == 200
            for label in ("Approve", "Edit + Approve", "Reject", "Skip", "Flag"):
                assert label in detail.text
            assert "CSV batch" in detail.text
            assert "review-flow.csv" in detail.text
    finally:
        manager.shutdown()


def test_replay_import_api_is_authenticated_and_dashboard_keeps_both_inputs(isolated):
    with TestClient(app) as client:
        payload = {"file": ("urls.csv", f"url\n{CAROUSELL}\n".encode(), "text/csv")}
        assert client.post("/api/replay/import", files=payload).status_code == 401
        token = ensure_local_token()
        response = client.post(
            "/api/replay/import",
            files=payload,
            headers={"X-GuardianLens-Token": token},
        )
        assert response.status_code == 200
        assert response.json()["import_summary"]["queued"] == 1
        page = client.get("/").text
        assert "Keep using the extension" in page
        assert "Choose or drop a CSV" in page
        assert "Paste URLs instead" in page
        for control in ("Start", "Pause", "Resume", "Stop", "Retry Failed"):
            assert control in page
