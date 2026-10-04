from __future__ import annotations

import json
import re
import secrets
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlsplit

from .capture import _validate_seller_url
from .config import settings
from .db import connect, transaction
from .states import transition
from .attention_lock import ensure_attention_idle


DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MIN_INTERVAL_SECONDS = 90
DEFAULT_JITTER_SECONDS = 60
DEFAULT_BACKOFF_BASE_SECONDS = 900
DEFAULT_BACKOFF_MAX_SECONDS = 3600
DEFAULT_BLOCK_BACKOFF_BASE_SECONDS = 900
DEFAULT_BLOCK_BACKOFF_MAX_SECONDS = 3600

ACTIVE_BATCH_STATUSES = ("running", "paused", "stopping")
ACTIVE_ITEM_STATUSES = ("opening_listing", "opening_seller")
WAITING_ITEM_STATUSES = ("pending", "retry_wait")
TERMINAL_ITEM_STATUSES = ("succeeded", "failed", "skipped", "ineligible")
BLOCK_ERROR_TYPES = {"access_denied", "blocked", "captcha"}
NON_RETRYABLE_ERROR_TYPES = {
    "ineligible",
    "invalid_listing_page",
    "invalid_seller_url",
    "listing_unavailable",
}

ELIGIBLE_LISTING_SQL = """
    listing.platform='mudah'
    AND listing.status='needs_attention'
    AND EXISTS (
        SELECT 1
        FROM capture_batch_items capture_item
        WHERE capture_item.listing_id=listing.listing_id
          AND capture_item.last_error_type='seller_capture_incomplete'
    )
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value))
    except (TypeError, ValueError):
        return None


def _clean_text(value: object, limit: int) -> str | None:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    return text[:limit] or None


class SellerRetryManager:
    """Durable, globally paced browser queue for seller-only recapture.

    Queue creation is deliberately separate from ``start``. Merely starting the
    GuardianLens server therefore cannot enqueue or run the historical repair.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        jitter: Callable[[int], int] | None = None,
    ) -> None:
        self._clock = clock or _utc_now
        self._jitter = jitter or self._secure_jitter

    @staticmethod
    def _secure_jitter(maximum: int) -> int:
        return secrets.randbelow(maximum + 1) if maximum > 0 else 0

    def _now(self) -> datetime:
        return _as_utc(self._clock())

    def _sample_jitter(self, maximum: int) -> int:
        maximum = max(0, int(maximum))
        sampled = int(self._jitter(maximum)) if maximum else 0
        if sampled < 0 or sampled > maximum:
            raise ValueError("jitter sampler returned a value outside its requested range")
        return sampled

    @staticmethod
    def _validate_prepare_options(
        *,
        max_attempts: int,
        min_interval_seconds: int,
        jitter_seconds: int,
        backoff_base_seconds: int,
        backoff_max_seconds: int,
        block_backoff_base_seconds: int,
        block_backoff_max_seconds: int,
    ) -> None:
        values = {
            "max_attempts": max_attempts,
            "min_interval_seconds": min_interval_seconds,
            "jitter_seconds": jitter_seconds,
            "backoff_base_seconds": backoff_base_seconds,
            "backoff_max_seconds": backoff_max_seconds,
            "block_backoff_base_seconds": block_backoff_base_seconds,
            "block_backoff_max_seconds": block_backoff_max_seconds,
        }
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values.values()):
            raise ValueError("seller retry pacing options must be integers")
        if not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if min_interval_seconds < 0 or jitter_seconds < 0:
            raise ValueError("seller retry interval and jitter cannot be negative")
        if backoff_base_seconds < 0 or backoff_max_seconds < backoff_base_seconds:
            raise ValueError("seller retry backoff base cannot exceed its maximum")
        if (
            block_backoff_base_seconds < 0
            or block_backoff_max_seconds < block_backoff_base_seconds
        ):
            raise ValueError("seller block backoff base cannot exceed its maximum")

    def prepare(
        self,
        name: str | None = None,
        *,
        listing_ids: list[str] | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        min_interval_seconds: int = DEFAULT_MIN_INTERVAL_SECONDS,
        jitter_seconds: int = DEFAULT_JITTER_SECONDS,
        backoff_base_seconds: int = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_max_seconds: int = DEFAULT_BACKOFF_MAX_SECONDS,
        block_backoff_base_seconds: int = DEFAULT_BLOCK_BACKOFF_BASE_SECONDS,
        block_backoff_max_seconds: int = DEFAULT_BLOCK_BACKOFF_MAX_SECONDS,
    ) -> dict:
        self._validate_prepare_options(
            max_attempts=max_attempts,
            min_interval_seconds=min_interval_seconds,
            jitter_seconds=jitter_seconds,
            backoff_base_seconds=backoff_base_seconds,
            backoff_max_seconds=backoff_max_seconds,
            block_backoff_base_seconds=block_backoff_base_seconds,
            block_backoff_max_seconds=block_backoff_max_seconds,
        )
        selected_ids = None
        if listing_ids is not None:
            if (not isinstance(listing_ids, list) or not listing_ids
                    or len(listing_ids) > 10000
                    or any(not isinstance(value, str) or not value.strip()
                           or len(value) > 64 for value in listing_ids)):
                raise ValueError("listing_ids must contain 1 to 10000 nonempty listing IDs")
            selected_ids = list(dict.fromkeys(value.strip() for value in listing_ids))
        retry_batch_id = str(uuid.uuid4())
        created_at = self._now().isoformat()
        batch_name = _clean_text(name, 120) or "Mudah seller behaviour recovery"
        with transaction() as con:
            ensure_attention_idle(con)
            processor = con.execute(
                "SELECT command FROM processor_control WHERE control_id=1"
            ).fetchone()
            if processor and processor["command"] in {"running", "paused", "stopping"}:
                raise RuntimeError(
                    "finish the current processing run before preparing seller retries"
                )
            replay = con.execute(
                """SELECT batch_id FROM capture_batches
                   WHERE status IN ('running','paused','stopping') LIMIT 1"""
            ).fetchone()
            if replay:
                raise RuntimeError(
                    "finish the active URL capture pass before preparing seller retries"
                )
            existing = con.execute(
                """SELECT retry_batch_id FROM seller_retry_batches
                   WHERE status IN ('draft','running','paused','stopping') LIMIT 1"""
            ).fetchone()
            if existing:
                raise RuntimeError("finish or stop the prepared seller retry batch first")

            selection_sql = ""
            parameters = [max_attempts]
            if selected_ids is not None:
                selection_sql = " AND listing.listing_id IN (" + ",".join("?" for _ in selected_ids) + ")"
                parameters.extend(selected_ids)
            candidates = con.execute(
                f"""SELECT DISTINCT listing.listing_id,listing.source_url,listing.seller_url,
                            listing.captured_at
                     FROM listings listing
                     WHERE {ELIGIBLE_LISTING_SQL}
                       AND (SELECT COALESCE(SUM(prior.attempt_count),0)
                            FROM seller_retry_items prior
                            WHERE prior.listing_id=listing.listing_id) < ?
                       {selection_sql}
                       AND NOT EXISTS (
                           SELECT 1
                           FROM seller_retry_items queued
                           JOIN seller_retry_batches queued_batch
                             ON queued_batch.retry_batch_id=queued.retry_batch_id
                           WHERE queued.listing_id=listing.listing_id
                             AND queued_batch.status IN ('draft','running','paused','stopping')
                       )
                     ORDER BY listing.captured_at,listing.listing_id""",
                parameters,
            ).fetchall()
            if not candidates:
                raise RuntimeError("no eligible Mudah seller capture failures were found")

            con.execute(
                """INSERT INTO seller_retry_batches(
                       retry_batch_id,name,status,total_items,max_attempts,
                       min_interval_seconds,jitter_seconds,backoff_base_seconds,
                       backoff_max_seconds,block_backoff_base_seconds,
                       block_backoff_max_seconds,block_streak,next_claim_at,
                       created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    retry_batch_id,
                    batch_name,
                    "draft",
                    len(candidates),
                    max_attempts,
                    min_interval_seconds,
                    jitter_seconds,
                    backoff_base_seconds,
                    backoff_max_seconds,
                    block_backoff_base_seconds,
                    block_backoff_max_seconds,
                    0,
                    created_at,
                    created_at,
                    created_at,
                ),
            )
            for candidate in candidates:
                seller_url = self._normalized_seller_url(candidate["seller_url"])
                con.execute(
                    """INSERT INTO seller_retry_items(
                           retry_item_id,retry_batch_id,listing_id,source_url,seller_url,
                           status,status_message,attempt_count,next_attempt_at,
                           created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        str(uuid.uuid4()),
                        retry_batch_id,
                        candidate["listing_id"],
                        candidate["source_url"],
                        seller_url,
                        "pending",
                        "Queued for paced seller behaviour capture",
                        0,
                        created_at,
                        created_at,
                        created_at,
                    ),
                )
        return self.status(retry_batch_id)

    def start(self, retry_batch_id: str) -> dict:
        with transaction() as con:
            ensure_attention_idle(con)
            batch = con.execute(
                "SELECT * FROM seller_retry_batches WHERE retry_batch_id=?",
                (retry_batch_id,),
            ).fetchone()
            if not batch:
                raise KeyError(retry_batch_id)
            if batch["status"] != "draft":
                raise RuntimeError(f"seller retry batch cannot start from {batch['status']}")
            active = con.execute(
                """SELECT retry_batch_id FROM seller_retry_batches
                   WHERE retry_batch_id<>? AND status IN ('running','paused','stopping')
                   LIMIT 1""",
                (retry_batch_id,),
            ).fetchone()
            if active:
                raise RuntimeError("another seller retry batch is already active")
            replay = con.execute(
                """SELECT batch_id FROM capture_batches
                   WHERE status IN ('running','paused','stopping') LIMIT 1"""
            ).fetchone()
            if replay:
                raise RuntimeError("finish the active URL capture pass before seller retries")
            processor = con.execute(
                "SELECT command FROM processor_control WHERE control_id=1"
            ).fetchone()
            if processor and processor["command"] in {"running", "paused", "stopping"}:
                raise RuntimeError("finish the current processing run before seller retries")
            eligible = con.execute(
                f"""SELECT 1
                     FROM seller_retry_items item
                     JOIN listings listing ON listing.listing_id=item.listing_id
                     WHERE item.retry_batch_id=? AND item.status='pending'
                       AND {ELIGIBLE_LISTING_SQL}
                     LIMIT 1""",
                (retry_batch_id,),
            ).fetchone()
            if not eligible:
                raise RuntimeError("seller retry batch has no eligible queued listings")
            started_at = self._now().isoformat()
            con.execute(
                """UPDATE seller_retry_batches
                   SET status='running',started_at=COALESCE(started_at,?),
                       completed_at=NULL,next_claim_at=?,updated_at=?
                   WHERE retry_batch_id=?""",
                (started_at, started_at, started_at, retry_batch_id),
            )
        return self.status(retry_batch_id)

    def command(self, retry_batch_id: str, command: str) -> dict:
        with transaction() as con:
            batch = con.execute(
                "SELECT status FROM seller_retry_batches WHERE retry_batch_id=?",
                (retry_batch_id,),
            ).fetchone()
            if not batch:
                raise KeyError(retry_batch_id)
            current = batch["status"]
            if command == "pause":
                if current != "running":
                    raise RuntimeError(f"seller retry batch cannot pause from {current}")
                target = "paused"
            elif command == "resume":
                if current != "paused":
                    raise RuntimeError(f"seller retry batch cannot resume from {current}")
                target = "running"
            elif command == "stop":
                if current not in {"running", "paused"}:
                    raise RuntimeError(f"seller retry batch cannot stop from {current}")
                target = "stopping"
            else:
                raise ValueError("unknown seller retry command")
            changed_at = self._now().isoformat()
            con.execute(
                "UPDATE seller_retry_batches SET status=?,updated_at=? WHERE retry_batch_id=?",
                (target, changed_at, retry_batch_id),
            )
            if target == "stopping":
                self._finish_batch_if_possible(con, retry_batch_id, self._now())
        return self.status(retry_batch_id)

    def claim_next(self) -> dict | None:
        now = self._now()
        now_iso = now.isoformat()
        with transaction() as con:
            self._recover_active_items(con, now, expired_only=True)
            batch = con.execute(
                """SELECT * FROM seller_retry_batches WHERE status='running'
                   ORDER BY started_at,created_at LIMIT 1"""
            ).fetchone()
            if not batch:
                return None
            self._finish_batch_if_possible(con, batch["retry_batch_id"], now)
            batch = con.execute(
                "SELECT * FROM seller_retry_batches WHERE retry_batch_id=?",
                (batch["retry_batch_id"],),
            ).fetchone()
            if not batch or batch["status"] != "running":
                return None

            active = con.execute(
                """SELECT 1 FROM seller_retry_items
                   WHERE status IN ('opening_listing','opening_seller') LIMIT 1"""
            ).fetchone()
            if active:
                return None
            next_claim_at = _parse_timestamp(batch["next_claim_at"])
            if next_claim_at and next_claim_at > now:
                return None

            exhausted_at = now_iso
            con.execute(
                """UPDATE seller_retry_items
                   SET status='failed',status_message='Seller capture attempt limit reached',
                       completed_at=?,updated_at=?,last_error_type='attempt_limit',
                       last_error_message='No automatic seller capture attempts remain',
                       last_error_at=?,lease_token=NULL,lease_expires_at=NULL
                   WHERE retry_batch_id=? AND status IN ('pending','retry_wait')
                     AND attempt_count>=?""",
                (
                    exhausted_at,
                    exhausted_at,
                    exhausted_at,
                    batch["retry_batch_id"],
                    batch["max_attempts"],
                ),
            )

            while True:
                item_row = con.execute(
                    """SELECT * FROM seller_retry_items
                       WHERE retry_batch_id=? AND status IN ('pending','retry_wait')
                         AND attempt_count<? AND COALESCE(next_attempt_at,created_at)<=?
                       ORDER BY COALESCE(next_attempt_at,created_at),created_at,retry_item_id
                       LIMIT 1""",
                    (batch["retry_batch_id"], batch["max_attempts"], now_iso),
                ).fetchone()
                if not item_row:
                    self._finish_batch_if_possible(con, batch["retry_batch_id"], now)
                    return None
                item = dict(item_row)
                if self._attempts_used(con, item["listing_id"]) >= int(batch["max_attempts"]):
                    con.execute(
                        """UPDATE seller_retry_items SET status='failed',
                           status_message='Seller capture attempt limit reached across recovery batches',
                           completed_at=?,updated_at=?,next_attempt_at=NULL,
                           last_error_type='attempt_limit',
                           last_error_message='Cumulative seller capture attempt limit reached',
                           last_error_at=? WHERE retry_item_id=?""",
                        (now_iso, now_iso, now_iso, item["retry_item_id"]),
                    )
                    continue
                if not self._eligible_listing(con, item["listing_id"]):
                    self._mark_ineligible(
                        con,
                        item,
                        now,
                        "Listing is no longer an eligible Mudah seller capture failure",
                    )
                    continue

                attempt_number = int(item["attempt_count"]) + 1
                lease_token = str(uuid.uuid4())
                lease_seconds = settings.capture_page_timeout_seconds * 3 + 60
                lease_expires_at = (now + timedelta(seconds=lease_seconds)).isoformat()
                opening_status = "opening_seller" if item["seller_url"] else "opening_listing"
                opening_message = (
                    "Opening cached Mudah seller page"
                    if item["seller_url"]
                    else "Opening Mudah listing to derive the seller page"
                )
                updated = con.execute(
                    """UPDATE seller_retry_items
                       SET status=?,status_message=?,attempt_count=?,
                           started_at=COALESCE(started_at,?),completed_at=NULL,updated_at=?,
                           lease_token=?,lease_expires_at=?,last_error_type=NULL,
                           last_error_message=NULL,last_error_at=NULL
                       WHERE retry_item_id=? AND status IN ('pending','retry_wait')""",
                    (
                        opening_status,
                        opening_message,
                        attempt_number,
                        now_iso,
                        now_iso,
                        lease_token,
                        lease_expires_at,
                        item["retry_item_id"],
                    ),
                )
                if updated.rowcount != 1:  # pragma: no cover - BEGIN IMMEDIATE serializes claims
                    continue
                con.execute(
                    """INSERT INTO seller_retry_attempts(
                           attempt_id,retry_item_id,attempt_number,started_at,status,seller_url
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        str(uuid.uuid4()),
                        item["retry_item_id"],
                        attempt_number,
                        now_iso,
                        opening_status,
                        item["seller_url"],
                    ),
                )
                claimed = con.execute(
                    "SELECT * FROM seller_retry_items WHERE retry_item_id=?",
                    (item["retry_item_id"],),
                ).fetchone()
                return {
                    **dict(claimed),
                    "platform": "mudah",
                    "max_attempts": batch["max_attempts"],
                    "page_timeout_seconds": settings.capture_page_timeout_seconds,
                    "navigation_delay_seconds": 5 + self._sample_jitter(10),
                }

    def update_item(
        self,
        retry_item_id: str,
        *,
        lease_token: str,
        status: str,
        seller_url: str | None = None,
        status_message: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> dict:
        if status not in {"opening_seller", "captured", "failed"}:
            raise ValueError("unsupported seller retry item status")
        if not _clean_text(lease_token, 100):
            raise ValueError("seller retry update needs its lease token")
        message = _clean_text(status_message, 500)
        error_kind = _clean_text(error_type, 100)
        error_text = _clean_text(error_message, 2000)
        normalized_seller_url = None
        if seller_url is not None:
            normalized_seller_url = self._normalized_seller_url(seller_url, required=True)
        now = self._now()
        now_iso = now.isoformat()

        with transaction() as con:
            item_row = con.execute(
                """SELECT item.*,batch.status AS batch_status,
                          batch.max_attempts,batch.min_interval_seconds,
                          batch.jitter_seconds,batch.backoff_base_seconds,
                          batch.backoff_max_seconds,batch.block_backoff_base_seconds,
                          batch.block_backoff_max_seconds,batch.block_streak,
                          batch.next_claim_at
                   FROM seller_retry_items item
                   JOIN seller_retry_batches batch
                     ON batch.retry_batch_id=item.retry_batch_id
                   WHERE item.retry_item_id=?""",
                (retry_item_id,),
            ).fetchone()
            if not item_row:
                raise KeyError(retry_item_id)
            item = dict(item_row)
            if item["status"] not in ACTIVE_ITEM_STATUSES:
                raise RuntimeError(f"seller retry item cannot update from {item['status']}")
            if item["lease_token"] != lease_token:
                raise RuntimeError("seller retry lease is stale")
            if not self._eligible_listing(con, item["listing_id"]):
                self._mark_ineligible(
                    con,
                    item,
                    now,
                    "Listing changed state or no longer matches the seller retry scope",
                )
                self._finish_batch_if_possible(con, item["retry_batch_id"], now)
                batch_id = item["retry_batch_id"]
            elif status == "opening_seller":
                if not normalized_seller_url:
                    raise ValueError("opening_seller update needs a validated seller_url")
                lease_seconds = settings.capture_page_timeout_seconds * 2 + 60
                con.execute(
                    """UPDATE seller_retry_items
                       SET status='opening_seller',seller_url=?,status_message=?,updated_at=?,
                           lease_expires_at=?
                       WHERE retry_item_id=? AND lease_token=?""",
                    (
                        normalized_seller_url,
                        message or "Seller URL derived; opening the paced seller capture",
                        now_iso,
                        (now + timedelta(seconds=lease_seconds)).isoformat(),
                        retry_item_id,
                        lease_token,
                    ),
                )
                con.execute(
                    """UPDATE seller_retry_attempts
                       SET status='opening_seller',seller_url=?
                       WHERE retry_item_id=? AND attempt_number=? AND finished_at IS NULL""",
                    (normalized_seller_url, retry_item_id, item["attempt_count"]),
                )
                batch_id = item["retry_batch_id"]
            else:
                if normalized_seller_url:
                    con.execute(
                        "UPDATE seller_retry_items SET seller_url=? WHERE retry_item_id=?",
                        (normalized_seller_url, retry_item_id),
                    )
                    item["seller_url"] = normalized_seller_url
                if status == "captured":
                    evidence = self._committed_seller_evidence(con, item)
                    if evidence:
                        self._complete_success(con, item, evidence, now)
                    else:
                        self._schedule_failure(
                            con,
                            item,
                            now,
                            error_type="seller_evidence_incomplete",
                            error_message=(
                                "Seller capture acknowledgement had no new URL, screenshot, "
                                "and non-empty staged seller text"
                            ),
                            status_message="Seller evidence was incomplete; retry scheduled",
                        )
                else:
                    evidence = self._committed_seller_evidence(con, item)
                    if evidence:
                        self._complete_success(con, item, evidence, now)
                    else:
                        self._schedule_failure(
                            con,
                            item,
                            now,
                            error_type=error_kind or "seller_capture_failed",
                            error_message=error_text or message or "Seller behaviour capture failed",
                            status_message=message or "Seller behaviour capture failed",
                        )
                self._finish_batch_if_possible(con, item["retry_batch_id"], now)
                batch_id = item["retry_batch_id"]
        return self.status(batch_id)

    def recover(self) -> None:
        now = self._now()
        with transaction() as con:
            self._recover_active_items(con, now, expired_only=False)
            batch_ids = [
                row["retry_batch_id"]
                for row in con.execute(
                    """SELECT retry_batch_id FROM seller_retry_batches
                       WHERE status IN ('running','stopping')"""
                )
            ]
            for retry_batch_id in batch_ids:
                self._finish_batch_if_possible(con, retry_batch_id, now)

    def shutdown(self) -> None:
        return None

    def status(self, retry_batch_id: str | None = None) -> dict:
        with closing(connect()) as con:
            if retry_batch_id:
                batch = con.execute(
                    "SELECT * FROM seller_retry_batches WHERE retry_batch_id=?",
                    (retry_batch_id,),
                ).fetchone()
            else:
                batch = con.execute(
                    """SELECT * FROM seller_retry_batches
                       ORDER BY CASE WHEN status IN ('running','paused','stopping') THEN 0 ELSE 1 END,
                                created_at DESC,rowid DESC LIMIT 1"""
                ).fetchone()
            if not batch:
                return {
                    "batch": None,
                    "progress": None,
                    "current": None,
                    "recent_attempts": [],
                    "recent_failures": [],
                    "retry_after_seconds": None,
                }
            batch_id = batch["retry_batch_id"]
            grouped = {
                row["status"]: row["n"]
                for row in con.execute(
                    """SELECT status,COUNT(*) AS n FROM seller_retry_items
                       WHERE retry_batch_id=? GROUP BY status""",
                    (batch_id,),
                )
            }
            current = con.execute(
                """SELECT * FROM seller_retry_items
                   WHERE retry_batch_id=? AND status IN ('opening_listing','opening_seller')
                   ORDER BY started_at,retry_item_id LIMIT 1""",
                (batch_id,),
            ).fetchone()
            attempts = con.execute(
                """SELECT attempt.*,item.listing_id,item.status AS item_status
                   FROM seller_retry_attempts attempt
                   JOIN seller_retry_items item ON item.retry_item_id=attempt.retry_item_id
                   WHERE item.retry_batch_id=?
                   ORDER BY attempt.started_at DESC,attempt.attempt_number DESC LIMIT 12""",
                (batch_id,),
            ).fetchall()
            failures = con.execute(
                """SELECT * FROM seller_retry_items
                   WHERE retry_batch_id=? AND last_error_type IS NOT NULL
                   ORDER BY COALESCE(last_error_at,updated_at) DESC,retry_item_id LIMIT 10""",
                (batch_id,),
            ).fetchall()
            total = int(batch["total_items"])
            active = sum(grouped.get(value, 0) for value in ACTIVE_ITEM_STATUSES)
            waiting = sum(grouped.get(value, 0) for value in WAITING_ITEM_STATUSES)
            terminal = sum(grouped.get(value, 0) for value in TERMINAL_ITEM_STATUSES)
            next_times = [
                value
                for value in (
                    _parse_timestamp(batch["next_claim_at"]),
                    _parse_timestamp(
                        con.execute(
                            """SELECT MIN(next_attempt_at) AS next_attempt_at
                               FROM seller_retry_items
                               WHERE retry_batch_id=? AND status IN ('pending','retry_wait')""",
                            (batch_id,),
                        ).fetchone()["next_attempt_at"]
                    ),
                )
                if value is not None
            ]
            retry_after = None
            if batch["status"] == "running" and next_times and not current:
                due_at = max(next_times)
                retry_after = max(0, int((due_at - self._now()).total_seconds() + 0.999))
            return {
                "batch": dict(batch),
                "progress": {
                    "total": total,
                    "processed": terminal,
                    "succeeded": grouped.get("succeeded", 0),
                    "failed": grouped.get("failed", 0),
                    "skipped": grouped.get("skipped", 0) + grouped.get("ineligible", 0),
                    "waiting": waiting,
                    "active": active,
                    "remaining": waiting + active,
                    "by_status": grouped,
                },
                "current": dict(current) if current else None,
                "recent_attempts": [dict(row) for row in attempts],
                "recent_failures": [dict(row) for row in failures],
                "retry_after_seconds": retry_after,
            }

    @staticmethod
    def _eligible_listing(con, listing_id: str | None):
        if not listing_id:
            return None
        return con.execute(
            f"""SELECT listing.* FROM listings listing
                WHERE listing.listing_id=? AND {ELIGIBLE_LISTING_SQL}""",
            (listing_id,),
        ).fetchone()

    @staticmethod
    def _normalized_seller_url(value: str | None, *, required: bool = False) -> str | None:
        if not value:
            if required:
                raise ValueError("seller_url is required")
            return None
        try:
            return _validate_seller_url("mudah", str(value))
        except ValueError:
            if required:
                raise
            return None

    @classmethod
    def _seller_url_identity(cls, value: str | None) -> tuple[str, str] | None:
        normalized = cls._normalized_seller_url(value)
        if not normalized:
            return None
        parsed = urlsplit(normalized)
        host = (parsed.hostname or "").removeprefix("www.")
        path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
        return host, path

    def _committed_seller_evidence(self, con, item: dict) -> dict | None:
        listing = con.execute(
            """SELECT platform,status,seller_url,seller_screenshot_path,staging_text_path,updated_at
               FROM listings WHERE listing_id=?""",
            (item["listing_id"],),
        ).fetchone()
        if not listing or listing["platform"] != "mudah" or listing["status"] != "needs_attention":
            return None
        seller_url = self._normalized_seller_url(listing["seller_url"])
        expected_url = self._normalized_seller_url(item.get("seller_url"))
        if not seller_url or (
            expected_url
            and self._seller_url_identity(seller_url)
            != self._seller_url_identity(expected_url)
        ):
            return None
        if not listing["seller_screenshot_path"]:
            return None
        screenshot = settings.root / listing["seller_screenshot_path"]
        if not screenshot.is_file():
            return None
        if not listing["staging_text_path"]:
            return None
        staging_path = settings.root / listing["staging_text_path"]
        try:
            staging = json.loads(staging_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        seller_text = staging.get("seller_visible_text")
        if not isinstance(seller_text, str) or not seller_text.strip():
            return None
        attempt = con.execute(
            """SELECT started_at FROM seller_retry_attempts
               WHERE retry_item_id=? AND attempt_number=?
               ORDER BY rowid DESC LIMIT 1""",
            (item["retry_item_id"], item["attempt_count"]),
        ).fetchone()
        attempt_started = _parse_timestamp(attempt["started_at"] if attempt else None)
        evidence_updated = _parse_timestamp(listing["updated_at"])
        if not attempt_started or not evidence_updated or evidence_updated < attempt_started:
            return None
        return {"seller_url": seller_url}

    def _complete_success(self, con, item: dict, evidence: dict, now: datetime) -> None:
        if not self._eligible_listing(con, item["listing_id"]):
            self._mark_ineligible(
                con,
                item,
                now,
                "Listing left the seller retry scope before completion",
            )
            return
        now_iso = now.isoformat()
        transition(
            item["listing_id"],
            "captured",
            "seller behaviour evidence recovered by paced browser retry",
            con=con,
        )
        con.execute(
            """UPDATE capture_batch_items
               SET status_message='Seller behaviour evidence recovered by paced retry',
                   updated_at=?,last_error_type=NULL,last_error_message=NULL,last_error_at=NULL
               WHERE listing_id=? AND last_error_type='seller_capture_incomplete'""",
            (now_iso, item["listing_id"]),
        )
        con.execute(
            """UPDATE seller_retry_items
               SET status='succeeded',status_message='Seller behaviour evidence captured',
                   seller_url=?,completed_at=?,updated_at=?,lease_token=NULL,
                   lease_expires_at=NULL,last_error_type=NULL,last_error_message=NULL,
                   last_error_at=NULL
               WHERE retry_item_id=?""",
            (evidence["seller_url"], now_iso, now_iso, item["retry_item_id"]),
        )
        self._close_attempt(
            con,
            item,
            now,
            status="captured",
            seller_url=evidence["seller_url"],
        )
        batch = con.execute(
            "SELECT * FROM seller_retry_batches WHERE retry_batch_id=?",
            (item["retry_batch_id"],),
        ).fetchone()
        delay = int(batch["min_interval_seconds"]) + self._sample_jitter(
            int(batch["jitter_seconds"])
        )
        self._set_batch_next_claim(con, batch, now + timedelta(seconds=delay), now, block_streak=0)

    @staticmethod
    def _attempts_used(con, listing_id: str | None) -> int:
        return int(con.execute(
            "SELECT COALESCE(SUM(attempt_count),0) FROM seller_retry_items WHERE listing_id=?",
            (listing_id,),
        ).fetchone()[0])

    def _schedule_failure(
        self,
        con,
        item: dict,
        now: datetime,
        *,
        error_type: str,
        error_message: str,
        status_message: str,
    ) -> None:
        now_iso = now.isoformat()
        batch = con.execute(
            "SELECT * FROM seller_retry_batches WHERE retry_batch_id=?",
            (item["retry_batch_id"],),
        ).fetchone()
        if not batch:
            raise RuntimeError("seller retry batch disappeared")
        clean_error_type = _clean_text(error_type, 100) or "seller_capture_failed"
        clean_error_message = _clean_text(error_message, 2000) or "Seller behaviour capture failed"
        retryable = (
            clean_error_type not in NON_RETRYABLE_ERROR_TYPES
            and int(item["attempt_count"]) < int(batch["max_attempts"])
            and self._attempts_used(con, item["listing_id"]) < int(batch["max_attempts"])
        )
        if retryable:
            exponent = max(0, int(item["attempt_count"]) - 1)
            item_delay = min(
                int(batch["backoff_max_seconds"]),
                int(batch["backoff_base_seconds"]) * (2**exponent),
            ) + self._sample_jitter(int(batch["jitter_seconds"]))
            item_status = "retry_wait"
            item_message = status_message + "; retry scheduled with backoff"
            next_attempt_at = (now + timedelta(seconds=item_delay)).isoformat()
            completed_at = None
        else:
            item_status = "failed"
            item_message = (
                "Seller capture attempt limit reached"
                if self._attempts_used(con, item["listing_id"]) >= int(batch["max_attempts"])
                else status_message
            )
            next_attempt_at = None
            completed_at = now_iso
        con.execute(
            """UPDATE seller_retry_items
               SET status=?,status_message=?,next_attempt_at=?,completed_at=?,updated_at=?,
                   lease_token=NULL,lease_expires_at=NULL,last_error_type=?,
                   last_error_message=?,last_error_at=?
               WHERE retry_item_id=?""",
            (
                item_status,
                item_message[:500],
                next_attempt_at,
                completed_at,
                now_iso,
                clean_error_type,
                clean_error_message,
                now_iso,
                item["retry_item_id"],
            ),
        )
        self._close_attempt(
            con,
            item,
            now,
            status="failed",
            seller_url=item.get("seller_url"),
            error_type=clean_error_type,
            error_message=clean_error_message,
        )

        normal_delay = int(batch["min_interval_seconds"]) + self._sample_jitter(
            int(batch["jitter_seconds"])
        )
        block_streak = int(batch["block_streak"])
        global_delay = normal_delay
        if clean_error_type in BLOCK_ERROR_TYPES:
            block_streak += 1
            block_delay = min(
                int(batch["block_backoff_max_seconds"]),
                int(batch["block_backoff_base_seconds"]) * (2 ** (block_streak - 1)),
            ) + self._sample_jitter(int(batch["jitter_seconds"]))
            global_delay = max(global_delay, block_delay)
        self._set_batch_next_claim(
            con,
            batch,
            now + timedelta(seconds=global_delay),
            now,
            block_streak=block_streak,
        )

    @staticmethod
    def _close_attempt(
        con,
        item: dict,
        now: datetime,
        *,
        status: str,
        seller_url: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        con.execute(
            """UPDATE seller_retry_attempts
               SET status=?,seller_url=COALESCE(?,seller_url),finished_at=?,
                   error_type=?,error_message=?
               WHERE retry_item_id=? AND attempt_number=? AND finished_at IS NULL""",
            (
                status,
                seller_url,
                now.isoformat(),
                error_type,
                error_message,
                item["retry_item_id"],
                item["attempt_count"],
            ),
        )

    @staticmethod
    def _set_batch_next_claim(
        con,
        batch,
        candidate: datetime,
        now: datetime,
        *,
        block_streak: int,
    ) -> None:
        existing = _parse_timestamp(batch["next_claim_at"])
        target = max(candidate, existing) if existing else candidate
        con.execute(
            """UPDATE seller_retry_batches
               SET next_claim_at=?,block_streak=?,updated_at=?
               WHERE retry_batch_id=?""",
            (target.isoformat(), block_streak, now.isoformat(), batch["retry_batch_id"]),
        )

    def _mark_ineligible(self, con, item: dict, now: datetime, message: str) -> None:
        now_iso = now.isoformat()
        con.execute(
            """UPDATE seller_retry_items
               SET status='ineligible',status_message=?,completed_at=?,updated_at=?,
                   lease_token=NULL,lease_expires_at=NULL,last_error_type='ineligible',
                   last_error_message=?,last_error_at=?
               WHERE retry_item_id=?""",
            (message[:500], now_iso, now_iso, message[:2000], now_iso, item["retry_item_id"]),
        )
        self._close_attempt(
            con,
            item,
            now,
            status="ineligible",
            error_type="ineligible",
            error_message=message,
        )
        # An active item may already have reached its seller page before a concurrent
        # review/state change made it ineligible. Keep the global visit spacing even
        # though this row itself must no longer be retried.
        if item.get("status") in ACTIVE_ITEM_STATUSES:
            batch = con.execute(
                "SELECT * FROM seller_retry_batches WHERE retry_batch_id=?",
                (item["retry_batch_id"],),
            ).fetchone()
            if batch:
                delay = int(batch["min_interval_seconds"]) + self._sample_jitter(
                    int(batch["jitter_seconds"])
                )
                self._set_batch_next_claim(
                    con,
                    batch,
                    now + timedelta(seconds=delay),
                    now,
                    block_streak=int(batch["block_streak"]),
                )

    def _recover_active_items(self, con, now: datetime, *, expired_only: bool) -> None:
        active = con.execute(
            """SELECT item.* FROM seller_retry_items item
               WHERE item.status IN ('opening_listing','opening_seller')"""
        ).fetchall()
        for row in active:
            item = dict(row)
            lease_expires_at = _parse_timestamp(item["lease_expires_at"])
            if expired_only and lease_expires_at and lease_expires_at > now:
                continue
            if not self._eligible_listing(con, item["listing_id"]):
                self._mark_ineligible(
                    con,
                    item,
                    now,
                    "Listing left the seller retry scope while its browser lease was active",
                )
                continue
            evidence = self._committed_seller_evidence(con, item)
            if evidence:
                self._complete_success(con, item, evidence, now)
                continue
            self._schedule_failure(
                con,
                item,
                now,
                error_type="capture_timeout" if expired_only else "interrupted_capture",
                error_message=(
                    "Chrome stopped reporting this seller capture"
                    if expired_only
                    else "Backend or browser stopped during seller capture"
                ),
                status_message="Seller capture lease ended before evidence was acknowledged",
            )

    @staticmethod
    def _finish_batch_if_possible(con, retry_batch_id: str, now: datetime) -> None:
        batch = con.execute(
            "SELECT status FROM seller_retry_batches WHERE retry_batch_id=?",
            (retry_batch_id,),
        ).fetchone()
        if not batch:
            return
        active = con.execute(
            """SELECT 1 FROM seller_retry_items
               WHERE retry_batch_id=? AND status IN ('opening_listing','opening_seller') LIMIT 1""",
            (retry_batch_id,),
        ).fetchone()
        now_iso = now.isoformat()
        if batch["status"] == "stopping" and not active:
            con.execute(
                """UPDATE seller_retry_items
                   SET status='skipped',status_message='Stopped before seller capture',
                       completed_at=?,updated_at=?,lease_token=NULL,lease_expires_at=NULL
                   WHERE retry_batch_id=? AND status IN ('pending','retry_wait')""",
                (now_iso, now_iso, retry_batch_id),
            )
            con.execute(
                """UPDATE seller_retry_batches
                   SET status='stopped',completed_at=?,updated_at=? WHERE retry_batch_id=?""",
                (now_iso, now_iso, retry_batch_id),
            )
            return
        remaining = con.execute(
            """SELECT 1 FROM seller_retry_items
               WHERE retry_batch_id=?
                 AND status IN ('pending','retry_wait','opening_listing','opening_seller') LIMIT 1""",
            (retry_batch_id,),
        ).fetchone()
        if batch["status"] == "running" and not remaining:
            con.execute(
                """UPDATE seller_retry_batches
                   SET status='completed',completed_at=?,updated_at=? WHERE retry_batch_id=?""",
                (now_iso, now_iso, retry_batch_id),
            )


seller_retry_manager = SellerRetryManager()
