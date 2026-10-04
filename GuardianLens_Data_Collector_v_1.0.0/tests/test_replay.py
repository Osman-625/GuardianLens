from __future__ import annotations

import csv
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from conftest import data_url, image_bytes
from guardianlens.app import app
from guardianlens.audit import data_integrity_report
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
    stage_file_path,
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


def test_import_creates_viewable_stage_file_used_by_capture(isolated):
    result = create_csv_batch(
        f"category,url\nPhones,{CAROUSELL}\nCameras,{MUDAH}\n".encode(),
        "two-platforms.csv",
        "Stage file fixture",
    )
    batch_id = result["batch"]["batch_id"]
    path = stage_file_path(batch_id)
    assert path.is_file()
    assert result["stage_file"] == {
        "exists": True,
        "filename": "stage_1_urls.csv",
        "relative_path": f"data/private/replay_batches/{batch_id}/stage_1_urls.csv",
        "view_url": f"/asset/replay-stage/{batch_id}",
        "download_url": f"/asset/replay-stage/{batch_id}?download=true",
        "size_bytes": path.stat().st_size,
    }
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["platform"], row["category"], row["source_url"]) for row in rows] == [
        ("carousell", "Phones", CAROUSELL.rstrip("/")),
        ("mudah", "Cameras", MUDAH),
    ]
    assert [row["capture_ready"] for row in rows] == ["yes", "yes"]

    manager = ReplayManager()
    manager.start(batch_id)
    claimed = manager.claim_next()
    assert claimed["source_url"] == rows[0]["source_url"]
    assert claimed["platform"] == rows[0]["platform"]
    assert claimed["category"] == rows[0]["category"]


def test_capture_refuses_a_changed_stage_file(isolated):
    snapshot = create_manual_batch(CAROUSELL, "Tamper guard")
    batch_id = snapshot["batch"]["batch_id"]
    path = stage_file_path(batch_id)
    contents = path.read_text(encoding="utf-8-sig")
    path.write_text(contents.replace(CAROUSELL.rstrip("/"), MUDAH), encoding="utf-8-sig")
    with pytest.raises(RuntimeError, match="was changed"):
        ReplayManager().start(batch_id)


def test_multiple_captured_queue_checkpoints_pass_integrity_audit(isolated):
    snapshot = create_manual_batch(f"{CAROUSELL}\n{MUDAH}", "Captured checkpoints")
    manager = ReplayManager()
    manager.start(snapshot["batch"]["batch_id"])
    for _ in range(2):
        item = manager.claim_next()
        manager.update_item(item["batch_item_id"], status="capturing")
        capture = create_capture(_capture_payload(item["source_url"], item["batch_item_id"]))
        manager.update_item(
            item["batch_item_id"], status="captured", listing_id=capture["listing_id"]
        )
    report = data_integrity_report()
    assert report["pass"], report
    assert report["checks"]["replay_stage_file_count"] == 1


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
        assert item["status"] == "capture_failed"
        assert item["last_error_type"] == "interrupted_capture"
        assert attempt["status"] == "interrupted"
        assert recovered.status(batch_id)["batch"]["status"] == "completed"
        assert recovered.claim_next() is None
        assert recovered.retry_failed(batch_id)["retried"] == 1
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
    assert manager.claim_next() is None
    assert manager.status(batch_id)["batch"]["status"] == "completed"
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
    assert attempts == [{"status": "capture_timeout", "error_type": "capture_timeout"}]
    assert manager.retry_failed(batch_id)["retried"] == 1
    second = manager.claim_next()
    assert second["batch_item_id"] == first["batch_item_id"]
    assert second["attempt_count"] == 2
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


def test_capture_start_and_retry_wait_for_active_processing_run(isolated):
    snapshot = create_manual_batch(CAROUSELL, "Sequential phases")
    batch_id = snapshot["batch"]["batch_id"]
    manager = ReplayManager()
    with transaction() as con:
        con.execute(
            "UPDATE processor_control SET command='running',updated_at=? WHERE control_id=1",
            (now_iso(),),
        )
    with pytest.raises(RuntimeError, match="processing run"):
        manager.start(batch_id)

    with transaction() as con:
        con.execute(
            "UPDATE processor_control SET command='idle',updated_at=? WHERE control_id=1",
            (now_iso(),),
        )
    manager.start(batch_id)
    item = manager.claim_next()
    manager.update_item(item["batch_item_id"], status="capture_failed", error_message="one")
    with transaction() as con:
        con.execute(
            "UPDATE processor_control SET command='paused',updated_at=? WHERE control_id=1",
            (now_iso(),),
        )
    with pytest.raises(RuntimeError, match="processing run"):
        manager.retry_failed(batch_id)


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


def test_committed_capture_survives_lost_browser_acknowledgement(isolated):
    snapshot = create_manual_batch(CAROUSELL, "Lost acknowledgement")
    batch_id = snapshot["batch"]["batch_id"]

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
        final = manager.status(batch_id)
        assert final["batch"]["status"] == "completed"
        assert final["progress"]["captured"] == 1
        assert final["progress"]["failed"] == 0
        assert final["processing"]["queued"] == 1
        assert final["current"] is None
        con = connect()
        try:
            linked = con.execute(
                "SELECT status,listing_id,last_error_type FROM capture_batch_items WHERE batch_item_id=?",
                (item["batch_item_id"],),
            ).fetchone()
        finally:
            con.close()
        assert linked["status"] == "captured"
        assert linked["listing_id"] == capture["listing_id"]
        assert linked["last_error_type"] is None
    finally:
        manager.shutdown()


def test_restart_recovers_capture_committed_before_queue_ack(isolated):
    snapshot = create_manual_batch(CAROUSELL, "Committed capture recovery")
    batch_id = snapshot["batch"]["batch_id"]
    first = ReplayManager()
    first.start(batch_id)
    item = first.claim_next()
    first.update_item(item["batch_item_id"], status="capturing")
    create_capture(_capture_payload(CAROUSELL, item["batch_item_id"]))
    first.shutdown()

    recovered = ReplayManager()
    recovered.recover()
    try:
        final = recovered.status(batch_id)
        assert final["batch"]["status"] == "completed"
        assert final["progress"]["captured"] == 1
        assert final["progress"]["failed"] == 0
        assert final["processing"]["queued"] == 1
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
    with pytest.raises(RuntimeError, match="no captured records are awaiting preprocessing"):
        processor.start(None, 1)
    assert calls == []
    replay.shutdown()


def test_processing_failure_does_not_stop_next_replay_item(isolated, monkeypatch):
    snapshot = create_manual_batch(f"{CAROUSELL}\n{MUDAH}", "Isolation")
    batch_id = snapshot["batch"]["batch_id"]
    calls = []

    def fake_process(listing_id, **_kwargs):
        calls.append(listing_id)
        if len(calls) == 1:
            with transaction() as con:
                con.execute(
                    "UPDATE listings SET status='processing_failed',updated_at=? WHERE listing_id=?",
                    (now_iso(), listing_id),
                )
            raise RuntimeError("one listing failed")
        with transaction() as con:
            con.execute(
                "UPDATE listings SET status='ready_for_review',updated_at=? WHERE listing_id=?",
                (now_iso(), listing_id),
            )
        return {"listing_id": listing_id, "status": "ready_for_review"}

    monkeypatch.setattr("guardianlens.batch.process_listing", fake_process)
    manager = ReplayManager()
    manager.start(batch_id)
    try:
        first = manager.claim_next()
        first_capture = create_capture(_capture_payload(first["source_url"], first["batch_item_id"]))
        manager.update_item(
            first["batch_item_id"], status="captured", listing_id=first_capture["listing_id"]
        )
        second = manager.claim_next()
        assert second and second["row_number"] == 2
        second_capture = create_capture(_capture_payload(second["source_url"], second["batch_item_id"]))
        manager.update_item(
            second["batch_item_id"], status="captured", listing_id=second_capture["listing_id"]
        )
        final = manager.status(batch_id)
        assert final["batch"]["status"] == "completed"
        assert calls == []

        processor = BatchManager()
        processor.start(None, 2)
        for _ in range(100):
            run = processor.status()["latest_run"]
            if run["status"] == "completed":
                break
            time.sleep(0.02)
        assert len(calls) == 2
        final = manager.status(batch_id)
        assert final["progress"]["captured"] == 2
        assert final["processing"]["failed"] == 1
        assert final["processing"]["successful"] == 1
    finally:
        manager.shutdown()


def test_csv_capture_enters_same_processing_and_human_review_ui(isolated, monkeypatch):
    from guardianlens.openai_extractor import MockExtractor

    monkeypatch.setattr(
        "guardianlens.processor.download_image",
        lambda _url: image_bytes((400, 300), value=126),
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
        final = manager.status(batch_id)
        assert final["batch"]["status"] == "completed"
        assert final["progress"]["captured"] == 1
        assert final["processing"]["queued"] == 1

        processor = BatchManager()
        processor.start(
            None,
            1,
            extractor_factory=MockExtractor,
        )
        for _ in range(100):
            run = processor.status()["latest_run"]
            if run["status"] == "completed":
                break
            time.sleep(0.02)
        assert manager.status(batch_id)["processing"]["successful"] == 1

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
        batch_id = response.json()["batch"]["batch_id"]
        stage_view = client.get(f"/asset/replay-stage/{batch_id}")
        assert stage_view.status_code == 200
        assert stage_view.headers["content-type"].startswith("text/csv")
        assert stage_view.headers["content-disposition"].startswith("inline")
        assert CAROUSELL.rstrip("/") in stage_view.text
        stage_download = client.get(f"/asset/replay-stage/{batch_id}?download=true")
        assert stage_download.headers["content-disposition"].startswith("attachment")
        page = client.get("/").text
        assert "Keep using the extension" in page
        assert "Choose or drop a CSV" in page
        assert "Paste URLs instead" in page
        for control in (
            "Start capture pass",
            "Pause",
            "Resume",
            "Stop",
            "Retry capture failures",
            "Start selected run",
            "Prepared URL file",
            "Open CSV",
        ):
            assert control in page


def test_capture_pass_needs_no_ai_but_unified_processing_uses_safe_defaults(
    isolated, monkeypatch
):
    import importlib

    app_module = importlib.import_module("guardianlens.app")
    snapshot = create_manual_batch(CAROUSELL, "Provider boundary")
    batch_id = snapshot["batch"]["batch_id"]
    token = ensure_local_token()
    monkeypatch.setattr(app_module, "provider_configured", lambda _provider: False)

    with TestClient(app) as client:
        started = client.post(
            f"/api/replay/{batch_id}/start",
            headers={"X-GuardianLens-Token": token},
        )
        assert started.status_code == 200

        manager = ReplayManager()
        item = manager.claim_next()
        capture = create_capture(_capture_payload(CAROUSELL, item["batch_item_id"]))
        manager.update_item(
            item["batch_item_id"], status="captured", listing_id=capture["listing_id"]
        )

        assert client.post("/api/batch/start", json={}).status_code == 401
        missing_provider = client.post(
            "/api/batch/start",
            json={},
            headers={"X-GuardianLens-Token": token},
        )
        assert missing_provider.status_code == 409

        calls = []

        def fake_start(duration_minutes, item_limit, extractor_factory=None):
            calls.append((duration_minutes, item_limit))
            return "unified-run"

        monkeypatch.setattr(app_module, "provider_configured", lambda _provider: True)
        monkeypatch.setattr(app_module.batch_manager, "start", fake_start)
        processing = client.post(
            "/api/batch/start",
            json={},
            headers={"X-GuardianLens-Token": token},
        )
        assert processing.status_code == 200
        assert processing.json()["run_id"] == "unified-run"
        assert calls == [(60, 50)]
