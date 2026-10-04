from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from guardianlens.app import app
from guardianlens.batch import BatchManager
from guardianlens.db import connect, transaction
from guardianlens.replay import ReplayManager, create_manual_batch
from guardianlens.security import ensure_local_token
from guardianlens.seller_retry import SellerRetryManager
from guardianlens.states import transition


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


@pytest.fixture()
def seller_retry_db(isolated):
    with transaction() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS seller_retry_batches (
                   retry_batch_id TEXT PRIMARY KEY,
                   name TEXT NOT NULL,
                   status TEXT NOT NULL,
                   total_items INTEGER NOT NULL DEFAULT 0,
                   max_attempts INTEGER NOT NULL DEFAULT 3,
                   min_interval_seconds INTEGER NOT NULL DEFAULT 90,
                   jitter_seconds INTEGER NOT NULL DEFAULT 60,
                   backoff_base_seconds INTEGER NOT NULL DEFAULT 900,
                   backoff_max_seconds INTEGER NOT NULL DEFAULT 3600,
                   block_backoff_base_seconds INTEGER NOT NULL DEFAULT 900,
                   block_backoff_max_seconds INTEGER NOT NULL DEFAULT 3600,
                   block_streak INTEGER NOT NULL DEFAULT 0,
                   next_claim_at TEXT,
                   created_at TEXT NOT NULL,
                   started_at TEXT,
                   completed_at TEXT,
                   updated_at TEXT NOT NULL
               )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS seller_retry_items (
                   retry_item_id TEXT PRIMARY KEY,
                   retry_batch_id TEXT NOT NULL
                       REFERENCES seller_retry_batches(retry_batch_id) ON DELETE CASCADE,
                   listing_id TEXT REFERENCES listings(listing_id) ON DELETE SET NULL,
                   source_url TEXT NOT NULL,
                   seller_url TEXT,
                   status TEXT NOT NULL,
                   status_message TEXT,
                   attempt_count INTEGER NOT NULL DEFAULT 0,
                   next_attempt_at TEXT,
                   lease_token TEXT,
                   lease_expires_at TEXT,
                   created_at TEXT NOT NULL,
                   started_at TEXT,
                   completed_at TEXT,
                   updated_at TEXT NOT NULL,
                   last_error_type TEXT,
                   last_error_message TEXT,
                   last_error_at TEXT,
                   UNIQUE(retry_batch_id,listing_id)
               )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS seller_retry_attempts (
                   attempt_id TEXT PRIMARY KEY,
                   retry_item_id TEXT NOT NULL
                       REFERENCES seller_retry_items(retry_item_id) ON DELETE CASCADE,
                   attempt_number INTEGER NOT NULL,
                   started_at TEXT NOT NULL,
                   finished_at TEXT,
                   status TEXT NOT NULL,
                   seller_url TEXT,
                   error_type TEXT,
                   error_message TEXT
               )"""
        )
    return isolated


def _seed_listing(
    root,
    *,
    platform: str = "mudah",
    status: str = "needs_attention",
    error_type: str | None = "seller_capture_incomplete",
    seller_url: str | None = None,
) -> str:
    listing_id = str(uuid.uuid4())
    batch_id = str(uuid.uuid4())
    now = "2026-08-28T00:00:00+00:00"
    if platform == "mudah":
        source_url = f"https://www.mudah.my/retry-fixture-{uuid.uuid4().hex[:8]}-654321.htm"
    else:
        source_url = f"https://www.carousell.com.my/p/retry-fixture-{uuid.uuid4().hex[:8]}-123456/"
    staging_relative = f"data/private/staging/{listing_id}.json"
    staging_path = root / staging_relative
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_text(json.dumps({"visible_text": "Listing fixture"}), encoding="utf-8")
    with transaction() as con:
        con.execute(
            """INSERT INTO capture_batches(
                   batch_id,name,source_type,status,total_rows,valid_urls,queued_count,
                   max_attempts,created_at,completed_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (batch_id, "Seller retry source", "manual", "completed", 1, 1, 1, 2, now, now, now),
        )
        con.execute(
            """INSERT INTO listings(
                   listing_id,platform,source_url,source_url_hash,status,seller_url,
                   staging_text_path,captured_at,capture_source,capture_batch_id,csv_row,
                   created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                listing_id,
                platform,
                source_url,
                uuid.uuid4().hex,
                status,
                seller_url,
                staging_relative,
                now,
                "csv_batch",
                batch_id,
                1,
                now,
                now,
            ),
        )
        con.execute(
            """INSERT INTO capture_batch_items(
                   batch_item_id,batch_id,row_number,source_url,source_url_hash,platform,
                   status,status_message,attempt_count,listing_id,created_at,completed_at,
                   updated_at,last_error_type,last_error_message,last_error_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()),
                batch_id,
                1,
                source_url,
                uuid.uuid4().hex,
                platform,
                "captured",
                "Listing captured; seller evidence needs attention",
                1,
                listing_id,
                now,
                now,
                now,
                error_type,
                "fixture seller capture failure" if error_type else None,
                now if error_type else None,
            ),
        )
    return listing_id


def _add_matching_capture_error(listing_id: str, source_url: str) -> None:
    batch_id = str(uuid.uuid4())
    now = "2026-08-28T00:00:00+00:00"
    with transaction() as con:
        con.execute(
            """INSERT INTO capture_batches(
                   batch_id,name,source_type,status,total_rows,valid_urls,queued_count,
                   max_attempts,created_at,completed_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (batch_id, "Duplicate source", "manual", "completed", 1, 1, 1, 2, now, now, now),
        )
        con.execute(
            """INSERT INTO capture_batch_items(
                   batch_item_id,batch_id,row_number,source_url,source_url_hash,platform,
                   status,attempt_count,listing_id,created_at,completed_at,updated_at,
                   last_error_type,last_error_message,last_error_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()),
                batch_id,
                1,
                source_url,
                uuid.uuid4().hex,
                "mudah",
                "captured",
                1,
                listing_id,
                now,
                now,
                now,
                "seller_capture_incomplete",
                "second matching source row",
                now,
            ),
        )


def _record_seller_evidence(
    root,
    listing_id: str,
    seller_url: str,
    updated_at: datetime,
) -> None:
    screenshot_relative = f"data/private/screenshots/mudah/{listing_id}/seller.jpg"
    screenshot = root / screenshot_relative
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    screenshot.write_bytes(b"seller screenshot fixture")
    with transaction() as con:
        listing = con.execute(
            "SELECT staging_text_path FROM listings WHERE listing_id=?", (listing_id,)
        ).fetchone()
        staging_path = root / listing["staging_text_path"]
        staged = json.loads(staging_path.read_text(encoding="utf-8"))
        staged["seller_visible_text"] = "Member since 2019, 4.8 rating, 17 reviews"
        staging_path.write_text(json.dumps(staged), encoding="utf-8")
        con.execute(
            """UPDATE listings
               SET seller_url=?,seller_screenshot_path=?,updated_at=? WHERE listing_id=?""",
            (seller_url, screenshot_relative, updated_at.isoformat(), listing_id),
        )


def _row(query: str, parameters=()):
    con = connect()
    try:
        result = con.execute(query, parameters).fetchone()
        return dict(result) if result else None
    finally:
        con.close()


def test_prepare_uses_only_exact_mudah_attention_error_scope_and_deduplicates(
    seller_retry_db,
):
    eligible = _seed_listing(seller_retry_db)
    eligible_row = _row("SELECT source_url FROM listings WHERE listing_id=?", (eligible,))
    _add_matching_capture_error(eligible, eligible_row["source_url"])
    captured = _seed_listing(seller_retry_db, status="captured")
    carousell = _seed_listing(seller_retry_db, platform="carousell")
    wrong_error = _seed_listing(seller_retry_db, error_type="capture_timeout")
    clock = MutableClock()

    snapshot = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0).prepare()

    assert snapshot["batch"]["total_items"] == 1
    assert snapshot["progress"]["by_status"] == {"pending": 1}
    queued = _row("SELECT listing_id,seller_url FROM seller_retry_items")
    assert queued == {"listing_id": eligible, "seller_url": None}
    for listing_id, expected in (
        (eligible, "needs_attention"),
        (captured, "captured"),
        (carousell, "needs_attention"),
        (wrong_error, "needs_attention"),
    ):
        assert _row("SELECT status FROM listings WHERE listing_id=?", (listing_id,))["status"] == expected


def test_prepare_can_select_exact_listing_ids(seller_retry_db):
    chosen = _seed_listing(seller_retry_db)
    other = _seed_listing(seller_retry_db)
    manager = SellerRetryManager()
    snapshot = manager.prepare(listing_ids=[chosen, chosen])
    assert snapshot["progress"]["by_status"] == {"pending": 1}
    assert _row("SELECT listing_id FROM seller_retry_items")["listing_id"] == chosen
    assert _row("SELECT status FROM listings WHERE listing_id=?", (other,))["status"] == "needs_attention"


@pytest.mark.parametrize("selection", [[], [""], ["x" * 65], "all"])
def test_prepare_rejects_invalid_exact_selection(seller_retry_db, selection):
    _seed_listing(seller_retry_db)
    with pytest.raises(ValueError, match="listing_ids"):
        SellerRetryManager().prepare(listing_ids=selection)
    assert _row("SELECT COUNT(*) AS n FROM seller_retry_batches")["n"] == 0


def test_new_seller_batch_cannot_reset_used_attempts(seller_retry_db):
    listing_id = _seed_listing(seller_retry_db)
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda _: 0)
    options = dict(listing_ids=[listing_id], max_attempts=2,
                   min_interval_seconds=0, jitter_seconds=0,
                   backoff_base_seconds=0, backoff_max_seconds=0)
    first_id = manager.prepare(**options)["batch"]["retry_batch_id"]
    manager.start(first_id)
    claimed = manager.claim_next()
    manager.update_item(claimed["retry_item_id"], lease_token=claimed["lease_token"],
                        status="failed", error_type="capture_timeout")
    manager.command(first_id, "stop")
    second_id = manager.prepare(**options)["batch"]["retry_batch_id"]
    manager.start(second_id)
    claimed = manager.claim_next()
    manager.update_item(claimed["retry_item_id"], lease_token=claimed["lease_token"],
                        status="failed", error_type="capture_timeout")
    assert manager.status(second_id)["progress"]["by_status"] == {"failed": 1}
    assert manager.claim_next() is None
    with pytest.raises(RuntimeError, match="no eligible"):
        manager.prepare(**options)
    assert _row("SELECT SUM(attempt_count) AS n FROM seller_retry_items")["n"] == 2


def test_start_rejects_active_processor_and_url_capture(seller_retry_db):
    _seed_listing(seller_retry_db)
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0)
    batch_id = manager.prepare()["batch"]["retry_batch_id"]
    with transaction() as con:
        con.execute(
            "UPDATE processor_control SET command='running',updated_at=? WHERE control_id=1",
            (clock().isoformat(),),
        )
    with pytest.raises(RuntimeError, match="processing run"):
        manager.start(batch_id)
    with transaction() as con:
        con.execute(
            "UPDATE processor_control SET command='idle',updated_at=? WHERE control_id=1",
            (clock().isoformat(),),
        )
        source_batch = con.execute("SELECT batch_id FROM capture_batches LIMIT 1").fetchone()
        con.execute(
            "UPDATE capture_batches SET status='running' WHERE batch_id=?",
            (source_batch["batch_id"],),
        )
    with pytest.raises(RuntimeError, match="URL capture pass"):
        manager.start(batch_id)
    with transaction() as con:
        con.execute("UPDATE capture_batches SET status='completed'")
    assert manager.start(batch_id)["batch"]["status"] == "running"


def test_prepare_makes_no_queue_writes_during_active_processor_or_url_capture(
    seller_retry_db,
):
    _seed_listing(seller_retry_db)
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0)
    with transaction() as con:
        con.execute(
            "UPDATE processor_control SET command='running',updated_at=? WHERE control_id=1",
            (clock().isoformat(),),
        )
    with pytest.raises(RuntimeError, match="processing run"):
        manager.prepare()
    assert _row("SELECT COUNT(*) AS n FROM seller_retry_batches")["n"] == 0

    with transaction() as con:
        con.execute(
            "UPDATE processor_control SET command='idle',updated_at=? WHERE control_id=1",
            (clock().isoformat(),),
        )
        con.execute("UPDATE capture_batches SET status='running'")
    with pytest.raises(RuntimeError, match="URL capture pass"):
        manager.prepare()
    assert _row("SELECT COUNT(*) AS n FROM seller_retry_batches")["n"] == 0

    with transaction() as con:
        con.execute("UPDATE capture_batches SET status='completed'")
    assert manager.prepare()["batch"]["status"] == "draft"


def test_claim_has_one_global_lease_and_url_checkpoint_requires_current_token(
    seller_retry_db,
):
    first_listing = _seed_listing(seller_retry_db)
    second_listing = _seed_listing(seller_retry_db)
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0)
    batch_id = manager.prepare()["batch"]["retry_batch_id"]
    manager.start(batch_id)

    first = manager.claim_next()
    assert first["listing_id"] in {first_listing, second_listing}
    assert first["status"] == "opening_listing"
    assert first["navigation_delay_seconds"] == 5
    assert SellerRetryManager(clock=clock, jitter=lambda _maximum: 0).claim_next() is None
    seller_url = "https://www.mudah.my/shop/example-seller"
    with pytest.raises(RuntimeError, match="lease is stale"):
        manager.update_item(
            first["retry_item_id"],
            lease_token="stale-token",
            status="opening_seller",
            seller_url=seller_url,
        )
    checkpoint = manager.update_item(
        first["retry_item_id"],
        lease_token=first["lease_token"],
        status="opening_seller",
        seller_url=seller_url,
    )
    assert checkpoint["current"]["status"] == "opening_seller"
    assert checkpoint["current"]["seller_url"] == seller_url


def test_verified_success_transitions_only_target_and_clears_matching_source_errors(
    seller_retry_db,
):
    listing_id = _seed_listing(seller_retry_db)
    source_url = _row("SELECT source_url FROM listings WHERE listing_id=?", (listing_id,))[
        "source_url"
    ]
    _add_matching_capture_error(listing_id, source_url)
    excluded = _seed_listing(seller_retry_db, platform="carousell")
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0)
    batch_id = manager.prepare()["batch"]["retry_batch_id"]
    manager.start(batch_id)
    claim = manager.claim_next()
    seller_url = "https://www.mudah.my/shop/recovered-seller"
    manager.update_item(
        claim["retry_item_id"],
        lease_token=claim["lease_token"],
        status="opening_seller",
        seller_url=seller_url,
    )
    clock.advance(1)
    _record_seller_evidence(seller_retry_db, listing_id, seller_url, clock())

    result = manager.update_item(
        claim["retry_item_id"],
        lease_token=claim["lease_token"],
        status="captured",
    )

    assert result["batch"]["status"] == "completed"
    assert result["progress"]["succeeded"] == 1
    assert _row("SELECT status FROM listings WHERE listing_id=?", (listing_id,))["status"] == "captured"
    assert _row("SELECT status FROM listings WHERE listing_id=?", (excluded,))["status"] == "needs_attention"
    con = connect()
    try:
        source_errors = con.execute(
            "SELECT last_error_type FROM capture_batch_items WHERE listing_id=?", (listing_id,)
        ).fetchall()
        history = con.execute(
            """SELECT from_status,to_status,reason FROM status_history
               WHERE listing_id=? ORDER BY timestamp DESC LIMIT 1""",
            (listing_id,),
        ).fetchone()
    finally:
        con.close()
    assert [row["last_error_type"] for row in source_errors] == [None, None]
    assert dict(history) == {
        "from_status": "needs_attention",
        "to_status": "captured",
        "reason": "seller behaviour evidence recovered by paced browser retry",
    }


def test_bare_captured_ack_without_fresh_text_and_screenshot_schedules_retry(
    seller_retry_db,
):
    listing_id = _seed_listing(
        seller_retry_db, seller_url="https://www.mudah.my/shop/incomplete-seller"
    )
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0)
    batch_id = manager.prepare(backoff_base_seconds=30, backoff_max_seconds=60)["batch"][
        "retry_batch_id"
    ]
    manager.start(batch_id)
    claim = manager.claim_next()

    snapshot = manager.update_item(
        claim["retry_item_id"],
        lease_token=claim["lease_token"],
        status="captured",
    )

    assert snapshot["progress"]["by_status"] == {"retry_wait": 1}
    item = _row("SELECT * FROM seller_retry_items WHERE retry_item_id=?", (claim["retry_item_id"],))
    assert item["last_error_type"] == "seller_evidence_incomplete"
    assert _row("SELECT status FROM listings WHERE listing_id=?", (listing_id,))["status"] == "needs_attention"


def test_success_enforces_global_minimum_interval_and_persisted_jitter(seller_retry_db):
    _seed_listing(
        seller_retry_db, seller_url="https://www.mudah.my/shop/first-seller"
    )
    _seed_listing(seller_retry_db, seller_url="https://www.mudah.my/shop/second-seller")
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda maximum: maximum)
    batch_id = manager.prepare(min_interval_seconds=10, jitter_seconds=5)["batch"][
        "retry_batch_id"
    ]
    manager.start(batch_id)
    first = manager.claim_next()
    clock.advance(1)
    _record_seller_evidence(
        seller_retry_db, first["listing_id"], first["seller_url"], clock()
    )
    manager.update_item(
        first["retry_item_id"],
        lease_token=first["lease_token"],
        status="captured",
    )

    assert manager.claim_next() is None
    clock.advance(14)
    assert manager.claim_next() is None
    clock.advance(1)
    second = manager.claim_next()
    assert second is not None
    assert second["listing_id"] != first["listing_id"]


def test_access_denied_applies_item_backoff_and_queue_wide_exponential_cooldown(
    seller_retry_db,
):
    _seed_listing(seller_retry_db, seller_url="https://www.mudah.my/shop/blocked-one")
    _seed_listing(seller_retry_db, seller_url="https://www.mudah.my/shop/blocked-two")
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0)
    batch_id = manager.prepare(
        max_attempts=2,
        min_interval_seconds=10,
        jitter_seconds=0,
        backoff_base_seconds=100,
        backoff_max_seconds=400,
        block_backoff_base_seconds=100,
        block_backoff_max_seconds=400,
    )["batch"]["retry_batch_id"]
    manager.start(batch_id)
    first = manager.claim_next()
    manager.update_item(
        first["retry_item_id"],
        lease_token=first["lease_token"],
        status="failed",
        error_type="access_denied",
        error_message="Cloudflare access denied",
    )
    first_item = _row("SELECT * FROM seller_retry_items WHERE retry_item_id=?", (first["retry_item_id"],))
    batch = _row("SELECT * FROM seller_retry_batches WHERE retry_batch_id=?", (batch_id,))
    assert first_item["status"] == "retry_wait"
    assert datetime.fromisoformat(first_item["next_attempt_at"]) - clock() == timedelta(seconds=100)
    assert datetime.fromisoformat(batch["next_claim_at"]) - clock() == timedelta(seconds=100)
    assert batch["block_streak"] == 1
    assert manager.claim_next() is None

    clock.advance(100)
    second = manager.claim_next()
    assert second["retry_item_id"] != first["retry_item_id"]
    manager.update_item(
        second["retry_item_id"],
        lease_token=second["lease_token"],
        status="failed",
        error_type="access_denied",
        error_message="still blocked",
    )
    batch = _row("SELECT * FROM seller_retry_batches WHERE retry_batch_id=?", (batch_id,))
    assert batch["block_streak"] == 2
    assert datetime.fromisoformat(batch["next_claim_at"]) - clock() == timedelta(seconds=200)


def test_attempt_limit_is_terminal_and_never_changes_listing_state(seller_retry_db):
    listing_id = _seed_listing(
        seller_retry_db, seller_url="https://www.mudah.my/shop/repeated-failure"
    )
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0)
    batch_id = manager.prepare(
        max_attempts=2,
        min_interval_seconds=0,
        jitter_seconds=0,
        backoff_base_seconds=10,
        backoff_max_seconds=10,
    )["batch"]["retry_batch_id"]
    manager.start(batch_id)
    first = manager.claim_next()
    manager.update_item(
        first["retry_item_id"],
        lease_token=first["lease_token"],
        status="failed",
        error_type="capture_timeout",
        error_message="one",
    )
    clock.advance(10)
    second = manager.claim_next()
    manager.update_item(
        second["retry_item_id"],
        lease_token=second["lease_token"],
        status="failed",
        error_type="capture_timeout",
        error_message="two",
    )

    final = manager.status(batch_id)
    assert final["batch"]["status"] == "completed"
    assert final["progress"]["failed"] == 1
    assert _row("SELECT status FROM listings WHERE listing_id=?", (listing_id,))["status"] == "needs_attention"
    assert _row(
        "SELECT last_error_type FROM capture_batch_items WHERE listing_id=?", (listing_id,)
    )["last_error_type"] == "seller_capture_incomplete"


def test_recover_reconciles_evidence_committed_before_final_ack(seller_retry_db):
    listing_id = _seed_listing(
        seller_retry_db, seller_url="https://www.mudah.my/shop/recovered-after-restart"
    )
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0)
    batch_id = manager.prepare()["batch"]["retry_batch_id"]
    manager.start(batch_id)
    claim = manager.claim_next()
    clock.advance(2)
    _record_seller_evidence(seller_retry_db, listing_id, claim["seller_url"], clock())

    recovered = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0)
    recovered.recover()

    assert recovered.status(batch_id)["progress"]["succeeded"] == 1
    assert _row("SELECT status FROM listings WHERE listing_id=?", (listing_id,))["status"] == "captured"
    with pytest.raises(RuntimeError, match="cannot update"):
        recovered.update_item(
            claim["retry_item_id"],
            lease_token=claim["lease_token"],
            status="failed",
            error_type="capture_timeout",
        )


def test_failed_browser_report_reconciles_seller_post_committed_before_response_loss(
    seller_retry_db,
):
    listing_id = _seed_listing(
        seller_retry_db, seller_url="https://www.mudah.my/shop/response-lost"
    )
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0)
    batch_id = manager.prepare()["batch"]["retry_batch_id"]
    manager.start(batch_id)
    claim = manager.claim_next()
    clock.advance(1)
    redirected_url = "https://mudah.my/shop/response-lost/"
    _record_seller_evidence(seller_retry_db, listing_id, redirected_url, clock())

    snapshot = manager.update_item(
        claim["retry_item_id"],
        lease_token=claim["lease_token"],
        status="failed",
        error_type="capture_timeout",
        error_message="seller POST response connection closed",
    )

    assert snapshot["batch"]["status"] == "completed"
    assert snapshot["progress"]["succeeded"] == 1
    assert _row("SELECT status FROM listings WHERE listing_id=?", (listing_id,))["status"] == "captured"


def test_claim_revalidates_scope_and_skips_listing_changed_after_start(seller_retry_db):
    listing_id = _seed_listing(seller_retry_db)
    clock = MutableClock()
    manager = SellerRetryManager(clock=clock, jitter=lambda _maximum: 0)
    batch_id = manager.prepare()["batch"]["retry_batch_id"]
    manager.start(batch_id)
    transition(listing_id, "under_review", "fixture operator began review")

    assert manager.claim_next() is None
    final = manager.status(batch_id)
    assert final["batch"]["status"] == "completed"
    assert final["progress"]["by_status"] == {"ineligible": 1}
    assert _row("SELECT status FROM listings WHERE listing_id=?", (listing_id,))["status"] == "under_review"


def test_seller_retry_api_is_authenticated_and_refuses_active_processing(seller_retry_db):
    _seed_listing(seller_retry_db)
    with TestClient(app) as client:
        assert client.post("/api/seller-retry/prepare", json={}).status_code == 401
        token = ensure_local_token()
        headers = {"X-GuardianLens-Token": token}
        with transaction() as con:
            con.execute(
                "UPDATE processor_control SET command='running',updated_at=? WHERE control_id=1",
                (datetime.now(timezone.utc).isoformat(),),
            )
        blocked = client.post("/api/seller-retry/prepare", json={}, headers=headers)
        assert blocked.status_code == 409
        assert "processing run" in blocked.json()["detail"]
        assert _row("SELECT COUNT(*) AS n FROM seller_retry_batches")["n"] == 0

        with transaction() as con:
            con.execute(
                "UPDATE processor_control SET command='idle',updated_at=? WHERE control_id=1",
                (datetime.now(timezone.utc).isoformat(),),
            )
        prepared = client.post("/api/seller-retry/prepare", json={}, headers=headers)
        assert prepared.status_code == 200
        batch_id = prepared.json()["batch"]["retry_batch_id"]
        assert client.get(
            "/api/seller-retry/status", params={"retry_batch_id": batch_id}
        ).json()["progress"]["total"] == 1
        assert client.post(f"/api/seller-retry/{batch_id}/start").status_code == 401
        started = client.post(
            f"/api/seller-retry/{batch_id}/start", headers=headers
        )
        assert started.status_code == 200
        assert started.json()["batch"]["status"] == "running"
        assert client.post("/api/seller-retry/claim").status_code == 401
        claimed = client.post("/api/seller-retry/claim", headers=headers)
        assert claimed.status_code == 200
        assert claimed.json()["item"]["listing_id"]


def test_seller_retry_api_maps_missing_batches_and_stale_leases(seller_retry_db):
    _seed_listing(seller_retry_db)
    with TestClient(app) as client:
        token = ensure_local_token()
        headers = {"X-GuardianLens-Token": token}
        assert client.post(
            f"/api/seller-retry/{uuid.uuid4()}/start", headers=headers
        ).status_code == 404
        prepared = client.post("/api/seller-retry/prepare", json={}, headers=headers).json()
        batch_id = prepared["batch"]["retry_batch_id"]
        client.post(f"/api/seller-retry/{batch_id}/start", headers=headers)
        item = client.post("/api/seller-retry/claim", headers=headers).json()["item"]
        stale = client.post(
            f"/api/seller-retry/items/{item['retry_item_id']}",
            headers=headers,
            json={
                "lease_token": "stale-token",
                "status": "failed",
                "error_type": "access_denied",
            },
        )
        assert stale.status_code == 409
        assert "lease is stale" in stale.json()["detail"]


def test_active_seller_retry_blocks_preprocessing_and_url_replay(seller_retry_db):
    _seed_listing(seller_retry_db)
    _seed_listing(seller_retry_db, status="captured", error_type=None)
    seller_manager = SellerRetryManager(jitter=lambda _maximum: 0)
    seller_batch_id = seller_manager.prepare()["batch"]["retry_batch_id"]
    seller_manager.start(seller_batch_id)

    with pytest.raises(RuntimeError, match="seller-capture retry"):
        BatchManager().start(None, 1)

    replay_url = f"https://www.mudah.my/new-replay-{uuid.uuid4().hex[:8]}-987704.htm"
    replay_batch_id = create_manual_batch(replay_url)["batch"]["batch_id"]
    with pytest.raises(RuntimeError, match="seller-capture retry"):
        ReplayManager().start(replay_batch_id)
