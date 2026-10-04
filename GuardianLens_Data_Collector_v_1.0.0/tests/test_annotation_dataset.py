from __future__ import annotations

import csv
import json
import logging
import runpy
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from guardianlens.config import settings
from guardianlens.db import now_iso, transaction
from guardianlens import annotation_dataset as ad

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "refresh_annotation_dataset.py"


def _uid() -> str:
    return uuid.uuid4().hex


def _insert(con, table, **cols) -> None:
    keys = list(cols)
    placeholders = ",".join("?" for _ in keys)
    con.execute(
        f"INSERT INTO {table}({','.join(keys)}) VALUES({placeholders})",
        [cols[k] for k in keys],
    )


def _write_file(relative: str, data: bytes = b"fake-bytes") -> str:
    """Write a real file under settings.root and return its project-relative path."""

    path = settings.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return relative.replace("\\", "/")


def _read_csv(root: Path, relative: str) -> list[dict]:
    with (root / relative).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _make_listing(con, listing_id: str, **overrides) -> str:
    now = now_iso()
    fields = {
        "listing_id": listing_id,
        "platform": "carousell",
        "marketplace_listing_id": listing_id,
        "source_url": f"https://carousell.com/p/{listing_id}",
        "source_url_hash": _uid(),
        "page_title": "Listing page",
        "title": "iPhone 12 Pro Max 128GB",
        "description": "Used, good condition, minor scratches on the back.",
        "category": "Phones",
        "condition": "Used",
        "price": 1200.0,
        "currency": "MYR",
        "location_state": "Selangor",
        "location_city": "Petaling Jaya",
        "account_age_days": 400,
        "seller_rating": 4.8,
        "review_count": 55,
        "active_listing_count": 3,
        "language": "en",
        "status": "captured",
        "metadata_signature": _uid(),
        "screenshot_path": None,
        "seller_url": None,
        "seller_screenshot_path": None,
        "staging_text_path": None,
        "ai_extracted": 0,
        "ai_provider": None,
        "ai_model": None,
        "ai_prompt_version": None,
        "captured_at": now,
        "processed_at": None,
        "approved_at": None,
        "rejected_at": None,
        "processing_run_id": None,
        "capture_source": "extension",
        "capture_batch_id": None,
        "csv_row": None,
        "original_csv_filename": None,
        "source_category": None,
        "created_at": now,
        "updated_at": now,
    }
    fields.update(overrides)
    _insert(con, "listings", **fields)
    return listing_id


def _make_image(
    con,
    listing_id: str,
    *,
    perceptual_hash: str,
    storage_path: str,
    is_primary: int = 1,
) -> str:
    image_id = _uid()
    _insert(
        con,
        "images",
        image_id=image_id,
        listing_id=listing_id,
        platform="carousell",
        storage_path=storage_path,
        sha256=_uid(),
        perceptual_hash=perceptual_hash,
        file_size_bytes=1024,
        width=800,
        height=600,
        source_position=0,
        is_primary=is_primary,
        source_url="https://carousell.com/img.jpg",
        created_at=now_iso(),
    )
    return image_id


def _seed(root: Path) -> SimpleNamespace:
    ids = SimpleNamespace()
    with transaction() as con:
        # --- capture batch + source rows -----------------------------------
        batch_id = _uid()
        _insert(
            con,
            "capture_batches",
            batch_id=batch_id,
            name="Test batch",
            source_type="csv",
            original_filename="urls.csv",
            status="completed",
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        ids.batch_id = batch_id

        # --- listings --------------------------------------------------------
        ids.approved_ok = _make_listing(
            con,
            _uid(),
            status="approved",
            screenshot_path=_write_file("data/private/screenshots/ok_listing.png"),
            seller_screenshot_path=_write_file("data/private/screenshots/ok_seller.png"),
        )
        _make_image(
            con,
            ids.approved_ok,
            perceptual_hash="a" * 16,
            storage_path=_write_file("data/images/carousell/approved_ok.jpg"),
        )

        ids.approved_stale = _make_listing(
            con,
            _uid(),
            status="approved",
            source_url="https://carousell.com/p/stale",
            screenshot_path=_write_file("data/private/screenshots/stale_listing.png"),
            seller_screenshot_path="data/private/screenshots/missing_seller_evidence.png",
        )

        ids.review_blocked = _make_listing(
            con,
            _uid(),
            status="ready_for_review",
            source_url="https://carousell.com/p/blocked",
        )

        ids.review_ok = _make_listing(
            con,
            _uid(),
            status="ready_for_review",
            source_url="https://carousell.com/p/ready-ok",
            title='Selipar Jepun 拖鞋, "comfy" size 42',
        )
        _make_image(
            con,
            ids.review_ok,
            perceptual_hash="b" * 16,
            storage_path=_write_file("data/images/carousell/review_ok.jpg"),
        )

        ids.null_fields = _make_listing(
            con,
            _uid(),
            status="needs_attention",
            source_url="https://carousell.com/p/nulls",
            price=None,
            seller_rating=None,
            review_count=None,
            category=None,
            source_category="Electronics",
        )

        ids.transition = _make_listing(
            con,
            _uid(),
            status="approved",
            source_url="https://carousell.com/p/transition",
        )
        _make_image(
            con,
            ids.transition,
            perceptual_hash="c" * 16,
            storage_path=_write_file("data/images/carousell/transition.jpg"),
        )
        base = now_iso()
        _insert(
            con,
            "status_history",
            history_id=_uid(),
            listing_id=ids.transition,
            from_status=None,
            to_status="needs_attention",
            timestamp="2026-01-01T00:00:00+00:00",
            reason="Captured with missing seller fields",
        )
        _insert(
            con,
            "status_history",
            history_id=_uid(),
            listing_id=ids.transition,
            from_status="needs_attention",
            to_status="under_review",
            timestamp="2026-01-01T00:00:01+00:00",
            reason="Reviewer opened the record",
        )
        _insert(
            con,
            "status_history",
            history_id=_uid(),
            listing_id=ids.transition,
            from_status="under_review",
            to_status="approved",
            timestamp="2026-01-01T00:00:02+00:00",
            reason="Approved after correction",
        )
        _insert(
            con,
            "review_actions",
            review_action_id=_uid(),
            listing_id=ids.transition,
            action="edit",
            previous_data=json.dumps({"title": "Old title", "internal_note": "must be dropped"}),
            updated_data=json.dumps({"title": "iPhone 12 Pro Max 128GB (corrected)"}),
            started_at=base,
            finished_at=base,
            duration_seconds=42,
            created_at=base,
            reason="Fixed a mis-typed title. Contact seller Bearer livesecrettoken1234567890",
        )
        _insert(
            con,
            "review_actions",
            review_action_id=_uid(),
            listing_id=ids.transition,
            action="approve",
            previous_data=None,
            updated_data=None,
            started_at=base,
            finished_at=base,
            duration_seconds=5,
            created_at=base,
            reason=None,
        )

        ids.formula = _make_listing(
            con,
            _uid(),
            status="needs_attention",
            source_url="https://carousell.com/p/formula",
            title="=2+2",
        )
        _insert(
            con,
            "warnings",
            warning_id=_uid(),
            listing_id=ids.formula,
            warning_type="seller_signal_missing",
            message="Missing seller_rating. api_key=shortfaketoken123",
            resolved=0,
            created_at=now_iso(),
        )

        ids.similar_a = _make_listing(
            con, _uid(), status="needs_attention", source_url="https://carousell.com/p/sim-a"
        )
        _make_image(
            con,
            ids.similar_a,
            perceptual_hash="0000000000000000",
            storage_path=_write_file("data/images/carousell/sim_a.jpg"),
        )
        ids.similar_b = _make_listing(
            con, _uid(), status="needs_attention", source_url="https://carousell.com/p/sim-b"
        )
        _make_image(
            con,
            ids.similar_b,
            perceptual_hash="000000000000001f",  # hamming distance 5 from all-zero
            storage_path=_write_file("data/images/carousell/sim_b.jpg"),
        )

        # a resolved warning must not count toward unresolved totals
        _insert(
            con,
            "warnings",
            warning_id=_uid(),
            listing_id=ids.approved_ok,
            warning_type="stale_note",
            message="Resolved a while ago",
            resolved=1,
            created_at=now_iso(),
        )

        # --- source rows: failures with no listing, plus a linked success ---
        for row_number, (status, error_type) in enumerate(
            (("access_denied", "access_denied"), ("captcha", "captcha")), start=1
        ):
            _insert(
                con,
                "capture_batch_items",
                batch_item_id=_uid(),
                batch_id=batch_id,
                row_number=row_number,
                source_url=f"https://carousell.com/p/{status}",
                platform="carousell",
                category="Phones",
                status=status,
                status_message=f"Blocked: {status}",
                attempt_count=2,
                listing_id=None,
                created_at=now_iso(),
                started_at=now_iso(),
                completed_at=now_iso(),
                updated_at=now_iso(),
                last_error_type=error_type,
                last_error_message="Secret leaked in error: sk-shortsecret12",
                last_error_at=now_iso(),
            )
        linked_item_id = _uid()
        _insert(
            con,
            "capture_batch_items",
            batch_item_id=linked_item_id,
            batch_id=batch_id,
            row_number=3,
            source_url="https://carousell.com/p/ready-ok",
            platform="carousell",
            category="Phones",
            status="captured",
            status_message="Captured with token api_key=shortfaketoken456",
            attempt_count=1,
            listing_id=ids.review_ok,
            created_at=now_iso(),
            started_at=now_iso(),
            completed_at=now_iso(),
            updated_at=now_iso(),
            last_error_type=None,
            last_error_message=None,
            last_error_at=None,
        )
        _insert(
            con,
            "capture_batch_attempts",
            attempt_id=_uid(),
            batch_item_id=linked_item_id,
            attempt_number=1,
            started_at=now_iso(),
            finished_at=now_iso(),
            status="captured",
            error_type=None,
            error_message=None,
        )

        _insert(
            con,
            "ai_extractions",
            extraction_id=_uid(),
            listing_id=ids.review_ok,
            provider="openai",
            model="gpt-4o-mini",
            prompt_version="v3",
            structured_output=json.dumps({"raw": "must never be exported"}),
            created_at=now_iso(),
            status="success",
            error=None,
        )
        _insert(
            con,
            "ai_extractions",
            extraction_id=_uid(),
            listing_id=ids.formula,
            provider="openai",
            model="gpt-4o-mini",
            prompt_version="v3",
            structured_output=None,
            created_at=now_iso(),
            status="error",
            error="Auth failed: Bearer anothersecrettoken1234567890",
        )

        _insert(
            con,
            "processing_runs",
            run_id=_uid(),
            capture_batch_id=batch_id,
            started_at=now_iso(),
            finished_at=now_iso(),
            duration_seconds=12,
            duration_limit_minutes=30,
            item_limit=100,
            status="completed",
            attempted=3,
            processed=3,
            successful=1,
            duplicates=0,
            ai_failures=1,
            image_failures=0,
            privacy_warnings=0,
            needs_attention=1,
            other_failures=0,
            failed=1,
        )
    return ids


@pytest.fixture()
def dataset(isolated):
    ids = _seed(isolated)
    result = ad.refresh_annotation_dataset("test_seed")
    return SimpleNamespace(ids=ids, result=result, root=ad._dataset_root())


def test_reconciles_row_counts_exactly(dataset):
    counts = dataset.result["counts"]
    source_rows = _read_csv(dataset.root, "master/source_rows.csv")
    listings = _read_csv(dataset.root, "master/listings.csv")
    images = _read_csv(dataset.root, "master/images.csv")
    assert len(source_rows) == counts["source_rows"] == 3
    assert len(listings) == counts["listings"] == 9
    assert len(images) == counts["images"] == 5

    status_total = sum(counts["by_status"].values())
    assert status_total == len(listings)


def test_by_status_files_cover_every_known_status_with_headers(dataset):
    for status, count in dataset.result["counts"]["by_status"].items():
        rows = _read_csv(dataset.root, f"by_status/{ad._status_filename(status)}")
        assert len(rows) == count
        if count == 0:
            # Header-bearing even when empty.
            with (dataset.root / f"by_status/{ad._status_filename(status)}").open(
                encoding="utf-8-sig"
            ) as handle:
                header = handle.readline().strip()
            assert header.startswith("listing_id,")

    empty_status = "flagged"
    assert dataset.result["counts"]["by_status"].get(empty_status) == 0


def test_null_values_stay_empty_and_categories_differ(dataset):
    rows = _read_csv(dataset.root, "master/listings.csv")
    row = next(r for r in rows if r["listing_id"] == dataset.ids.null_fields)
    assert row["price"] == ""
    assert row["seller_rating"] == ""
    assert row["review_count"] == ""
    assert row["category"] == ""
    assert row["source_category"] == "Electronics"
    assert "price" in row["missing_fields"].split(";")


def test_formula_injection_is_neutralised(dataset):
    rows = _read_csv(dataset.root, "master/listings.csv")
    row = next(r for r in rows if r["listing_id"] == dataset.ids.formula)
    assert row["title"] == "'=2+2"


def test_utf8_and_csv_quoting_round_trip(dataset):
    rows = _read_csv(dataset.root, "master/listings.csv")
    row = next(r for r in rows if r["listing_id"] == dataset.ids.review_ok)
    assert row["title"] == 'Selipar Jepun 拖鞋, "comfy" size 42'


def test_secrets_and_private_paths_never_appear_in_exports(dataset):
    forbidden = [
        "sk-shortsecret12",
        "shortfaketoken123",
        "shortfaketoken456",
        "livesecrettoken1234567890",
        "anothersecrettoken1234567890",
        str((settings.data_dir / "private").resolve()),
    ]
    for path in dataset.root.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig", errors="strict")
        for needle in forbidden:
            assert needle not in text, f"leaked {needle!r} into {path}"
    extraction_rows = _read_csv(dataset.root, "audit/ai_extractions.csv")
    assert "structured_output" not in extraction_rows[0].keys()


def test_no_product_image_is_copied_moved_or_deleted(dataset):
    original = settings.root / "data/images/carousell/review_ok.jpg"
    assert original.read_bytes() == b"fake-bytes"
    images = _read_csv(dataset.root, "master/images.csv")
    for row in images:
        assert row["storage_path"]
        exported_path = settings.root / row["storage_path"]
        assert exported_path.is_file()
    # The export tree itself must contain no copied binaries, only text output.
    for path in dataset.root.rglob("*"):
        if path.is_file():
            assert path.suffix in {".csv", ".json", ".md"}


def test_review_ready_approval_blockers_reported_not_repaired(dataset):
    findings = _read_csv(dataset.root, "quality/findings.csv")
    blocked_ids = {
        row["listing_id"]
        for row in findings
        if row["finding_type"] == "review_ready_approval_blocker"
    }
    assert blocked_ids == {dataset.ids.review_blocked}

    missing_image_ids = {
        row["listing_id"] for row in findings if row["finding_type"] == "missing_product_images"
    }
    assert dataset.ids.review_blocked in missing_image_ids

    listings = _read_csv(dataset.root, "master/listings.csv")
    blocked_row = next(r for r in listings if r["listing_id"] == dataset.ids.review_blocked)
    assert blocked_row["status"] == "ready_for_review"  # unchanged: reported, not fixed


def test_stale_private_evidence_reference_flagged_only_for_stale_listing(dataset):
    findings = _read_csv(dataset.root, "quality/findings.csv")
    stale_ids = {
        row["listing_id"]
        for row in findings
        if row["finding_type"] == "stale_private_evidence_reference"
    }
    assert stale_ids == {dataset.ids.approved_stale}


def test_visually_similar_image_groups_detected(dataset):
    findings = _read_csv(dataset.root, "quality/findings.csv")
    similar = [row for row in findings if row["finding_type"] == "visually_similar_image_group"]
    assert similar, "expected at least one visually similar image group"
    group_ids = {similar[0]["listing_id"]} | set(similar[0]["related_listing_ids"].split(";"))
    assert group_ids == {dataset.ids.similar_a, dataset.ids.similar_b}


def test_status_history_and_human_corrections_are_retained(dataset):
    history = _read_csv(dataset.root, "audit/status_history.csv")
    transitions = [
        (row["from_status"], row["to_status"])
        for row in history
        if row["listing_id"] == dataset.ids.transition
    ]
    assert transitions == [
        ("", "needs_attention"),
        ("needs_attention", "under_review"),
        ("under_review", "approved"),
    ]

    actions = _read_csv(dataset.root, "audit/review_actions.csv")
    edit_action = next(
        row
        for row in actions
        if row["listing_id"] == dataset.ids.transition and row["action"] == "edit"
    )
    updated = json.loads(edit_action["updated_data"])
    previous = json.loads(edit_action["previous_data"])
    assert updated == {"title": "iPhone 12 Pro Max 128GB (corrected)"}
    assert "title" in previous
    assert "internal_note" not in previous
    assert "sk-livesecretvalue1234567890" not in edit_action["reason"]


def test_annotation_test_csv_is_approved_only_and_grows(dataset):
    rows = _read_csv(dataset.root, "test/annotation_test.csv")
    ids_in_test = {row["listing_id"] for row in rows}
    assert ids_in_test == {dataset.ids.approved_ok, dataset.ids.approved_stale, dataset.ids.transition}
    assert dataset.ids.review_ok not in ids_in_test

    with transaction() as con:
        con.execute(
            "UPDATE listings SET status='approved',approved_at=? WHERE listing_id=?",
            (now_iso(), dataset.ids.review_ok),
        )
    result = ad.refresh_annotation_dataset("approval_grew_pilot")
    grown = _read_csv(ad._dataset_root(), "test/annotation_test.csv")
    assert {row["listing_id"] for row in grown} == ids_in_test | {dataset.ids.review_ok}
    assert result["counts"]["approved_annotation_test"] == len(grown)


def test_manual_csv_edits_are_overwritten_on_next_refresh(dataset):
    target = dataset.root / "master/listings.csv"
    target.write_text("tampered,by,human\n1,2,3\n", encoding="utf-8")
    ad.refresh_annotation_dataset("post_tamper")
    rows = _read_csv(ad._dataset_root(), "master/listings.csv")
    assert len(rows) == 9
    assert "tampered" not in rows[0]


def test_recovery_script_produces_a_valid_export(dataset):
    namespace = runpy.run_path(str(SCRIPT_PATH), run_name="__test_recovery_script__")
    exit_code = namespace["main"]()
    assert exit_code == 0
    manifest = json.loads((dataset.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["listings"] == 9


def test_get_status_reflects_last_refresh(dataset):
    status = ad.get_annotation_dataset_status()
    assert status["ok"] is True
    assert status["state"] == "ready"
    assert status["counts"]["listings"] == 9


def test_concurrent_refreshes_leave_a_consistent_dataset(dataset):
    errors: list[BaseException] = []

    def _run(trigger: str) -> None:
        try:
            ad.refresh_annotation_dataset(trigger)
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_run, args=(f"concurrent_{i}",)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors
    manifest = json.loads((dataset.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["listings"] == 9
    listings = _read_csv(dataset.root, "master/listings.csv")
    assert len(listings) == 9


def test_failed_refresh_leaves_previous_generation_usable(dataset, monkeypatch):
    baseline_manifest = json.loads((dataset.root / "manifest.json").read_text(encoding="utf-8"))

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated disk failure mid-export")

    monkeypatch.setattr(ad, "_write_csv", _boom)
    with pytest.raises(RuntimeError):
        ad.refresh_annotation_dataset("will_fail")
    monkeypatch.undo()

    manifest_after = json.loads((dataset.root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_after == baseline_manifest

    status = ad.get_annotation_dataset_status()
    assert status["ok"] is False
    assert status["state"] == "error"
    assert status["previous_generation_available"] is True

    # A retry after the transient failure clears must succeed again.
    result = ad.refresh_annotation_dataset("retry_after_failure")
    assert result["ok"] is True


def test_schedule_refresh_returns_immediately_without_waiting_for_rebuild(isolated, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def fake_refresh(trigger):
        calls.append(trigger)
        started.set()
        assert release.wait(timeout=5), "background refresh was never released"
        return {"ok": True}

    monkeypatch.setattr(ad, "refresh_annotation_dataset", fake_refresh)
    monkeypatch.setattr(ad, "SCHEDULE_DEBOUNCE_SECONDS", 0.05)

    try:
        before = time.monotonic()
        ad.schedule_annotation_dataset_refresh("review_started")
        elapsed = time.monotonic() - before
        assert elapsed < 0.5, "scheduling a refresh must not block the caller"

        assert started.wait(timeout=2), "debounced refresh never ran in the background"
        assert calls == ["review_started"]
    finally:
        release.set()
        ad._cancel_scheduled_refresh_for_tests()


def test_schedule_refresh_coalesces_rapid_calls_into_one_run(isolated, monkeypatch):
    calls: list[str] = []
    done = threading.Event()

    def fake_refresh(trigger):
        calls.append(trigger)
        done.set()
        return {"ok": True}

    monkeypatch.setattr(ad, "refresh_annotation_dataset", fake_refresh)
    monkeypatch.setattr(ad, "SCHEDULE_DEBOUNCE_SECONDS", 0.05)

    try:
        ad.schedule_annotation_dataset_refresh("review_started")
        ad.schedule_annotation_dataset_refresh("review_saved")
        ad.schedule_annotation_dataset_refresh("review_approved")

        assert done.wait(timeout=2), "coalesced refresh never ran"
        time.sleep(0.1)  # let any incorrectly-duplicated timer fire too, if one exists
        assert calls == ["review_approved"], "rapid calls must collapse into a single trailing run"
    finally:
        ad._cancel_scheduled_refresh_for_tests()


def test_schedule_refresh_logs_failure_instead_of_swallowing_it(isolated, monkeypatch, caplog):
    def failing_refresh(trigger):
        raise RuntimeError("simulated lock acquisition timeout")

    monkeypatch.setattr(ad, "refresh_annotation_dataset", failing_refresh)
    monkeypatch.setattr(ad, "SCHEDULE_DEBOUNCE_SECONDS", 0.02)

    try:
        with caplog.at_level(logging.ERROR, logger="guardianlens.annotation_dataset"):
            ad.schedule_annotation_dataset_refresh("review_approved")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and "simulated lock acquisition timeout" not in caplog.text:
                time.sleep(0.02)
        assert "simulated lock acquisition timeout" in caplog.text
    finally:
        ad._cancel_scheduled_refresh_for_tests()
