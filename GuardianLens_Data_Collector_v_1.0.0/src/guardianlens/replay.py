from __future__ import annotations

import csv
import io
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from .capture import ALLOWED_HOSTS, LISTING_PATHS
from .config import settings
from .db import connect, now_iso, transaction
from .dedupe import canonicalize_url, url_hash
from .errors import classify_error
from .processor import process_listing


URL_COLUMNS = ("url", "source_url", "listing_url", "product_url")
ACTIVE_ITEM_STATUSES = ("opening", "capturing", "captured", "processing")
REVIEW_STATUSES = (
    "ready_for_review",
    "needs_attention",
    "under_review",
    "approved",
    "rejected",
    "skipped",
    "flagged",
)
FAILURE_STATUSES = (
    "failed",
    "capture_failed",
    "capture_timeout",
    "invalid_listing_page",
    "blocked",
    "login_required",
    "captcha",
    "access_denied",
    "listing_unavailable",
)
RETRYABLE_FAILURE_STATUSES = tuple(
    status for status in FAILURE_STATUSES if status != "listing_unavailable"
)
CLIENT_RESULT_STATUSES = {
    "capturing",
    "captured",
    "duplicate",
    *FAILURE_STATUSES,
}
TERMINAL_CAPTURE_STATUSES = {
    "duplicate",
    "invalid",
    *FAILURE_STATUSES,
    *REVIEW_STATUSES,
}
_CONTROL_ACTIVE = ("running", "paused", "stopping")


class CSVImportError(ValueError):
    """The supplied upload cannot be turned into an auditable replay batch."""


def _clean_text(value: object, limit: int) -> str | None:
    text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
    return text[:limit] or None


def _safe_filename(value: str | None) -> str | None:
    if not value:
        return None
    name = Path(value.replace("\\", "/")).name
    return _clean_text(name, 255)


def _decode_csv(data: bytes) -> str:
    if not data:
        raise CSVImportError("The CSV file is empty.")
    if len(data) > settings.csv_import_max_bytes:
        raise CSVImportError(
            f"CSV exceeds the {settings.csv_import_max_bytes:,}-byte upload limit."
        )
    if b"\x00" in data:
        raise CSVImportError("CSV contains binary NUL bytes and is not readable text.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1252")
        except UnicodeDecodeError as exc:  # pragma: no cover - every byte decodes as cp1252
            raise CSVImportError("CSV must be UTF-8 or Windows-1252 text.") from exc


def parse_csv_rows(data: bytes) -> list[dict]:
    """Read a CSV without silently dropping malformed or duplicate data rows."""
    text = _decode_csv(data)
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    try:
        reader = csv.reader(io.StringIO(text, newline=""), dialect)
        header = next(reader, None)
        if not header:
            raise CSVImportError("CSV has no header row.")
        normalized = [str(value or "").strip().casefold() for value in header]
        url_index = next((normalized.index(name) for name in URL_COLUMNS if name in normalized), None)
        if url_index is None:
            raise CSVImportError(
                "CSV needs a URL column named url, source_url, listing_url, or product_url."
            )
        platform_index = normalized.index("platform") if "platform" in normalized else None
        category_index = normalized.index("category") if "category" in normalized else None
        rows: list[dict] = []
        for values in reader:
            if not any(str(value or "").strip() for value in values):
                continue
            if len(rows) >= settings.csv_import_max_rows:
                raise CSVImportError(
                    f"CSV exceeds the {settings.csv_import_max_rows:,}-row import limit."
                )

            def at(index: int | None) -> str:
                return str(values[index] if index is not None and index < len(values) else "").strip()

            rows.append(
                {
                    "row_number": reader.line_num,
                    "source_url": at(url_index),
                    "platform": at(platform_index),
                    "category": at(category_index),
                }
            )
    except CSVImportError:
        raise
    except csv.Error as exc:
        raise CSVImportError(f"CSV could not be read: {exc}") from exc
    if not rows:
        raise CSVImportError("CSV contains no non-blank data rows.")
    return rows


def parse_manual_rows(text: str) -> list[dict]:
    rows = []
    for row_number, value in enumerate(str(text or "").splitlines(), start=1):
        value = value.strip()
        if not value:
            continue
        if len(rows) >= settings.csv_import_max_rows:
            raise CSVImportError(
                f"Manual input exceeds the {settings.csv_import_max_rows:,}-URL import limit."
            )
        rows.append(
            {"row_number": row_number, "source_url": value, "platform": "", "category": ""}
        )
    if not rows:
        raise CSVImportError("Paste at least one listing URL.")
    return rows


def validate_import_url(value: str) -> tuple[str, str, str | None]:
    """Return canonical HTTPS URL, platform, and marketplace identifier when recognizable."""
    try:
        parsed = urlsplit(value.strip())
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid URL") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        raise ValueError("URL must be a plain HTTP or HTTPS marketplace URL")
    platform = next(
        (name for name, hosts in ALLOWED_HOSTS.items() if host in hosts),
        None,
    )
    if platform is None:
        raise ValueError("unsupported marketplace domain")
    path = unquote(parsed.path)
    if "\\" in path or any(ord(character) < 32 for character in path):
        raise ValueError("URL path is malformed")
    normalized = canonicalize_url(
        urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    )
    match = LISTING_PATHS[platform].fullmatch(path)
    marketplace_listing_id = match.group("listing_id") if match else None
    return normalized, platform, marketplace_listing_id


def _existing_listing(con, source_hash: str, platform: str, marketplace_listing_id: str | None):
    row = con.execute(
        """SELECT listing_id,status,capture_source,capture_batch_id,csv_row
           FROM listings WHERE source_url_hash=? ORDER BY captured_at LIMIT 1""",
        (source_hash,),
    ).fetchone()
    if row or not marketplace_listing_id:
        return row
    return con.execute(
        """SELECT listing_id,status,capture_source,capture_batch_id,csv_row FROM listings
           WHERE platform=? AND marketplace_listing_id=? ORDER BY captured_at LIMIT 1""",
        (platform, marketplace_listing_id),
    ).fetchone()


def _owned_capture(con, item):
    """Find evidence already committed for this exact queue row."""
    return con.execute(
        """SELECT listing_id,status FROM listings
           WHERE capture_source='csv_batch' AND capture_batch_id=? AND csv_row=?
           ORDER BY captured_at LIMIT 1""",
        (item["batch_id"], item["row_number"]),
    ).fetchone()


def _reconcile_owned_capture(con, item, message: str, reconciled_at: str) -> bool:
    """Resume a committed capture whose browser acknowledgement was lost."""
    listing = _owned_capture(con, item)
    if not listing:
        return False
    if listing["status"] in REVIEW_STATUSES:
        target = listing["status"]
    elif listing["status"] == "duplicate_blocked":
        target = "duplicate"
    else:
        target = "captured"
    completed_at = reconciled_at if target != "captured" else None
    con.execute(
        """UPDATE capture_batch_items
           SET status=?,status_message=?,listing_id=?,completed_at=?,updated_at=?,
               last_error_type=NULL,last_error_message=NULL,last_error_at=NULL
           WHERE batch_item_id=?""",
        (
            target,
            message,
            listing["listing_id"],
            completed_at,
            reconciled_at,
            item["batch_item_id"],
        ),
    )
    con.execute(
        """UPDATE capture_batch_attempts
           SET status='captured',finished_at=?,error_type=NULL,error_message=NULL
           WHERE batch_item_id=? AND finished_at IS NULL""",
        (reconciled_at, item["batch_item_id"]),
    )
    return True


def create_replay_batch(
    rows: list[dict],
    *,
    name: str | None,
    source_type: str,
    original_filename: str | None = None,
) -> dict:
    if source_type not in {"csv", "manual"}:
        raise ValueError("source_type must be csv or manual")
    batch_id = str(uuid.uuid4())
    created_at = now_iso()
    filename = _safe_filename(original_filename)
    fallback_name = Path(filename).stem if filename else "Pasted URLs"
    batch_name = _clean_text(name, 120) or fallback_name
    prepared: list[dict] = []
    seen_hashes: set[str] = set()
    counts = {
        "total_rows": len(rows),
        "valid_urls": 0,
        "invalid_rows": 0,
        "duplicate_rows": 0,
        "already_captured": 0,
        "queued_count": 0,
    }
    with transaction() as con:
        active_batch = con.execute(
            "SELECT batch_id FROM capture_batches WHERE status IN ('running','paused','stopping') LIMIT 1"
        ).fetchone()
        if active_batch:
            raise CSVImportError("Finish or stop the active CSV replay batch before importing another.")
        for source in rows:
            raw_url = _clean_text(source.get("source_url"), 4096) or "(missing URL)"
            supplied_platform = (_clean_text(source.get("platform"), 20) or "").casefold()
            category = _clean_text(source.get("category"), 300)
            item = {
                "batch_item_id": str(uuid.uuid4()),
                "batch_id": batch_id,
                "row_number": int(source["row_number"]),
                "source_url": raw_url,
                "source_url_hash": None,
                "platform": supplied_platform or None,
                "category": category,
                "status": "pending",
                "status_message": "Queued for browser capture",
                "listing_id": None,
                "last_error_type": None,
                "last_error_message": None,
            }
            try:
                normalized, detected_platform, marketplace_listing_id = validate_import_url(raw_url)
                if not marketplace_listing_id:
                    raise ValueError("URL is not an individual Carousell or Mudah listing page")
                if supplied_platform and supplied_platform not in ALLOWED_HOSTS:
                    raise ValueError(f"unsupported platform value: {supplied_platform}")
                if supplied_platform and supplied_platform != detected_platform:
                    raise ValueError(
                        f"platform {supplied_platform} does not match URL host ({detected_platform})"
                    )
                item["source_url"] = normalized
                item["source_url_hash"] = url_hash(normalized)
                item["platform"] = detected_platform
                counts["valid_urls"] += 1
                if item["source_url_hash"] in seen_hashes:
                    item.update(
                        status="duplicate",
                        status_message="Duplicate URL inside this import",
                        last_error_type="duplicate_in_import",
                        last_error_message="A previous row in this import has the same normalized URL.",
                    )
                    counts["duplicate_rows"] += 1
                else:
                    seen_hashes.add(item["source_url_hash"])
                    existing = _existing_listing(
                        con,
                        item["source_url_hash"],
                        detected_platform,
                        marketplace_listing_id,
                    )
                    if existing:
                        item.update(
                            status="duplicate",
                            status_message="Already captured by GuardianLens",
                            listing_id=existing["listing_id"],
                            last_error_type="already_captured",
                            last_error_message=f"Existing listing status: {existing['status']}",
                        )
                        counts["already_captured"] += 1
                    else:
                        counts["queued_count"] += 1
            except ValueError as exc:
                item.update(
                    status="invalid",
                    status_message="Invalid import row",
                    last_error_type="invalid_row",
                    last_error_message=str(exc),
                )
                counts["invalid_rows"] += 1
            prepared.append(item)

        con.execute(
            """INSERT INTO capture_batches(
                   batch_id,name,source_type,original_filename,status,total_rows,valid_urls,
                   invalid_rows,duplicate_rows,already_captured,queued_count,max_attempts,
                   created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                batch_id,
                batch_name,
                source_type,
                filename,
                "draft",
                counts["total_rows"],
                counts["valid_urls"],
                counts["invalid_rows"],
                counts["duplicate_rows"],
                counts["already_captured"],
                counts["queued_count"],
                settings.max_capture_attempts,
                created_at,
                created_at,
            ),
        )
        for item in prepared:
            terminal_at = created_at if item["status"] in {"invalid", "duplicate"} else None
            error_at = created_at if item["last_error_type"] else None
            con.execute(
                """INSERT INTO capture_batch_items(
                       batch_item_id,batch_id,row_number,source_url,source_url_hash,platform,
                       category,status,status_message,listing_id,created_at,completed_at,updated_at,
                       last_error_type,last_error_message,last_error_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item["batch_item_id"],
                    batch_id,
                    item["row_number"],
                    item["source_url"],
                    item["source_url_hash"],
                    item["platform"],
                    item["category"],
                    item["status"],
                    item["status_message"],
                    item["listing_id"],
                    created_at,
                    terminal_at,
                    created_at,
                    item["last_error_type"],
                    item["last_error_message"],
                    error_at,
                ),
            )
    return replay_snapshot(batch_id)


def create_csv_batch(data: bytes, filename: str, name: str | None = None) -> dict:
    return create_replay_batch(
        parse_csv_rows(data),
        name=name,
        source_type="csv",
        original_filename=filename,
    )


def create_manual_batch(text: str, name: str | None = None) -> dict:
    return create_replay_batch(parse_manual_rows(text), name=name, source_type="manual")


def _sync_review_outcomes(con, batch_id: str | None = None) -> None:
    params: tuple = ()
    clause = ""
    if batch_id:
        clause = " AND capture_batch_items.batch_id=?"
        params = (batch_id,)
    placeholders = ",".join("?" for _ in REVIEW_STATUSES)
    con.execute(
        f"""UPDATE capture_batch_items
            SET status=(SELECT status FROM listings WHERE listings.listing_id=capture_batch_items.listing_id),
                status_message='Human review status updated',updated_at=?
            WHERE listing_id IS NOT NULL
              AND EXISTS(
                  SELECT 1 FROM listings
                  WHERE listings.listing_id=capture_batch_items.listing_id
                    AND listings.status IN ({placeholders})
                    AND listings.status<>capture_batch_items.status
              ){clause}""",
        (now_iso(), *REVIEW_STATUSES, *params),
    )


def replay_snapshot(batch_id: str | None = None) -> dict:
    with transaction() as con:
        if batch_id:
            batch = con.execute(
                "SELECT * FROM capture_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
        else:
            batch = con.execute(
                """SELECT * FROM capture_batches
                   ORDER BY CASE WHEN status IN ('running','paused','stopping') THEN 0 ELSE 1 END,
                            created_at DESC,rowid DESC LIMIT 1"""
            ).fetchone()
        if not batch:
            return {"batch": None, "progress": None, "current": None, "recent_failures": []}
        batch_id = batch["batch_id"]
        _sync_review_outcomes(con, batch_id)
        batch = con.execute(
            "SELECT * FROM capture_batches WHERE batch_id=?", (batch_id,)
        ).fetchone()
        grouped = {
            row["status"]: row["n"]
            for row in con.execute(
                "SELECT status,COUNT(*) AS n FROM capture_batch_items WHERE batch_id=? GROUP BY status",
                (batch_id,),
            )
        }
        current = con.execute(
            """SELECT * FROM capture_batch_items
               WHERE batch_id=? AND status IN ('opening','capturing','captured','processing')
               ORDER BY row_number LIMIT 1""",
            (batch_id,),
        ).fetchone()
        failure_placeholders = ",".join("?" for _ in (*FAILURE_STATUSES, "invalid"))
        failures = con.execute(
            f"""SELECT * FROM capture_batch_items
                WHERE batch_id=? AND (status IN ({failure_placeholders}) OR last_error_type IS NOT NULL)
                ORDER BY COALESCE(last_error_at,updated_at) DESC,row_number DESC LIMIT 10""",
            (batch_id, *FAILURE_STATUSES, "invalid"),
        ).fetchall()
        total = int(batch["total_rows"])
        active = sum(grouped.get(status, 0) for status in ACTIVE_ITEM_STATUSES)
        remaining = grouped.get("pending", 0) + active
        successful = sum(grouped.get(status, 0) for status in REVIEW_STATUSES)
        failed = sum(grouped.get(status, 0) for status in FAILURE_STATUSES)
        blocked = sum(
            grouped.get(status, 0)
            for status in ("blocked", "login_required", "captcha", "access_denied")
        )
        processed = max(0, total - remaining)
        return {
            "batch": dict(batch),
            "import_summary": {
                "rows": batch["total_rows"],
                "valid_urls": batch["valid_urls"],
                "invalid_rows": batch["invalid_rows"],
                "duplicates_in_import": batch["duplicate_rows"],
                "already_captured": batch["already_captured"],
                "queued": batch["queued_count"],
            },
            "progress": {
                "total": total,
                "processed": processed,
                "attempted": sum(
                    row["n"]
                    for row in con.execute(
                        """SELECT attempt_count,COUNT(*) AS n FROM capture_batch_items
                           WHERE batch_id=? AND attempt_count>0 GROUP BY attempt_count""",
                        (batch_id,),
                    )
                ),
                "successful": successful,
                "failed": failed,
                "blocked": blocked,
                "duplicates": grouped.get("duplicate", 0),
                "invalid": grouped.get("invalid", 0),
                "remaining": remaining,
                "by_status": grouped,
            },
            "current": dict(current) if current else None,
            "recent_failures": [dict(row) for row in failures],
        }


def _finish_batch_if_possible(con, batch_id: str) -> None:
    batch = con.execute(
        "SELECT status FROM capture_batches WHERE batch_id=?", (batch_id,)
    ).fetchone()
    if not batch:
        return
    active = con.execute(
        """SELECT 1 FROM capture_batch_items
           WHERE batch_id=? AND status IN ('opening','capturing','captured','processing') LIMIT 1""",
        (batch_id,),
    ).fetchone()
    if batch["status"] == "stopping" and not active:
        completed_at = now_iso()
        con.execute(
            """UPDATE capture_batch_items
               SET status='skipped',status_message='Stopped before capture',completed_at=?,updated_at=?
               WHERE batch_id=? AND status='pending'""",
            (completed_at, completed_at, batch_id),
        )
        con.execute(
            "UPDATE capture_batches SET status='stopped',completed_at=?,updated_at=? WHERE batch_id=?",
            (completed_at, completed_at, batch_id),
        )
        return
    remaining = con.execute(
        """SELECT 1 FROM capture_batch_items
           WHERE batch_id=? AND status IN ('pending','opening','capturing','captured','processing') LIMIT 1""",
        (batch_id,),
    ).fetchone()
    if batch["status"] == "running" and not remaining:
        completed_at = now_iso()
        con.execute(
            "UPDATE capture_batches SET status='completed',completed_at=?,updated_at=? WHERE batch_id=?",
            (completed_at, completed_at, batch_id),
        )


class ReplayManager:
    """Persistent orchestration only; evidence and processing stay on the existing pipeline."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()

    def recover(self) -> None:
        recovered_at = now_iso()
        with transaction() as con:
            interrupted = con.execute(
                """SELECT item.*,batch.max_attempts
                   FROM capture_batch_items item
                   JOIN capture_batches batch ON batch.batch_id=item.batch_id
                   WHERE item.status IN ('opening','capturing')"""
            ).fetchall()
            for item in interrupted:
                if _reconcile_owned_capture(
                    con,
                    item,
                    "Recovered listing evidence committed before browser acknowledgement",
                    recovered_at,
                ):
                    continue
                retry = item["attempt_count"] < item["max_attempts"]
                target = "pending" if retry else "capture_failed"
                con.execute(
                    """UPDATE capture_batch_items
                       SET status=?,status_message='Recovered after interrupted browser capture',
                           completed_at=?,updated_at=?,last_error_type='interrupted_capture',
                           last_error_message='Backend or browser stopped during capture',last_error_at=?
                       WHERE batch_item_id=?""",
                    (
                        target,
                        None if retry else recovered_at,
                        recovered_at,
                        recovered_at,
                        item["batch_item_id"],
                    ),
                )
                con.execute(
                    """UPDATE capture_batch_attempts
                       SET status='interrupted',finished_at=?,error_type='interrupted_capture',
                           error_message='Backend or browser stopped during capture'
                       WHERE batch_item_id=? AND finished_at IS NULL""",
                    (recovered_at, item["batch_item_id"]),
                )
            processing = con.execute(
                "SELECT batch_item_id,batch_id,listing_id FROM capture_batch_items WHERE status='processing'"
            ).fetchall()
            for item in processing:
                listing = con.execute(
                    "SELECT status FROM listings WHERE listing_id=?", (item["listing_id"],)
                ).fetchone()
                if listing and listing["status"] in REVIEW_STATUSES:
                    target = listing["status"]
                elif listing and listing["status"] == "duplicate_blocked":
                    target = "duplicate"
                elif listing:
                    target = "captured"
                else:
                    target = "capture_failed"
                con.execute(
                    """UPDATE capture_batch_items SET status=?,status_message=?,updated_at=?,
                           completed_at=CASE WHEN ?='capture_failed' THEN ? ELSE completed_at END,
                           last_error_type=CASE WHEN ?='capture_failed' THEN 'missing_listing' ELSE last_error_type END,
                           last_error_message=CASE WHEN ?='capture_failed' THEN 'Captured listing no longer exists' ELSE last_error_message END,
                           last_error_at=CASE WHEN ?='capture_failed' THEN ? ELSE last_error_at END
                       WHERE batch_item_id=?""",
                    (
                        target,
                        "Recovered interrupted processing",
                        recovered_at,
                        target,
                        recovered_at,
                        target,
                        target,
                        target,
                        recovered_at,
                        item["batch_item_id"],
                    ),
                )
            for batch in con.execute(
                "SELECT batch_id FROM capture_batches WHERE status IN ('running','stopping')"
            ):
                _finish_batch_if_possible(con, batch["batch_id"])
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="guardianlens-replay-processing",
            )
            self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def start(self, batch_id: str) -> dict:
        with transaction() as con:
            batch = con.execute(
                "SELECT * FROM capture_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if not batch:
                raise KeyError(batch_id)
            if batch["status"] != "draft":
                raise RuntimeError(f"batch cannot start from {batch['status']}")
            active = con.execute(
                """SELECT batch_id FROM capture_batches
                   WHERE batch_id<>? AND status IN ('running','paused','stopping') LIMIT 1""",
                (batch_id,),
            ).fetchone()
            if active:
                raise RuntimeError("another CSV replay batch is already active")
            pending = con.execute(
                "SELECT COUNT(*) AS n FROM capture_batch_items WHERE batch_id=? AND status='pending'",
                (batch_id,),
            ).fetchone()["n"]
            if not pending:
                raise RuntimeError("batch has no queued URLs to capture")
            started_at = now_iso()
            con.execute(
                """UPDATE capture_batches
                   SET status='running',started_at=COALESCE(started_at,?),completed_at=NULL,updated_at=?
                   WHERE batch_id=?""",
                (started_at, started_at, batch_id),
            )
        self._ensure_worker()
        self._wake.set()
        return replay_snapshot(batch_id)

    def command(self, batch_id: str, command: str) -> dict:
        with transaction() as con:
            batch = con.execute(
                "SELECT status FROM capture_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if not batch:
                raise KeyError(batch_id)
            status = batch["status"]
            if command == "pause":
                if status != "running":
                    raise RuntimeError(f"batch cannot pause from {status}")
                target = "paused"
            elif command == "resume":
                if status != "paused":
                    raise RuntimeError(f"batch cannot resume from {status}")
                target = "running"
            elif command == "stop":
                if status not in {"running", "paused"}:
                    raise RuntimeError(f"batch cannot stop from {status}")
                target = "stopping"
            else:
                raise ValueError("unknown replay batch command")
            con.execute(
                "UPDATE capture_batches SET status=?,updated_at=? WHERE batch_id=?",
                (target, now_iso(), batch_id),
            )
            if target == "stopping":
                _finish_batch_if_possible(con, batch_id)
        self._wake.set()
        return replay_snapshot(batch_id)

    def retry_failed(self, batch_id: str) -> dict:
        with transaction() as con:
            batch = con.execute(
                "SELECT status,max_attempts FROM capture_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if not batch:
                raise KeyError(batch_id)
            if batch["status"] in _CONTROL_ACTIVE:
                raise RuntimeError("pause or finish the batch before retrying failures")
            placeholders = ",".join("?" for _ in RETRYABLE_FAILURE_STATUSES)
            eligible = con.execute(
                f"""SELECT batch_item_id,listing_id,attempt_count FROM capture_batch_items
                    WHERE batch_id=? AND status IN ({placeholders})
                      AND (listing_id IS NOT NULL OR attempt_count<max(?,1))""",
                (batch_id, *RETRYABLE_FAILURE_STATUSES, batch["max_attempts"]),
            ).fetchall()
            if not eligible:
                raise RuntimeError("no retryable failed URLs remain within the attempt limit")
            retried_at = now_iso()
            retried_count = 0
            for row in eligible:
                target = "pending"
                message = "Queued for explicit browser retry"
                if row["listing_id"]:
                    listing = con.execute(
                        "SELECT status FROM listings WHERE listing_id=?", (row["listing_id"],)
                    ).fetchone()
                    if listing and listing["status"] in {
                        "captured", "ai_failed", "image_failed", "processing_failed"
                    }:
                        target = "captured"
                        message = "Queued existing capture for pipeline retry"
                    elif listing and listing["status"] == "duplicate_blocked":
                        target = "duplicate"
                        message = "Existing pipeline already marked this listing duplicate"
                    elif row["attempt_count"] >= batch["max_attempts"]:
                        continue
                con.execute(
                    """UPDATE capture_batch_items
                       SET status=?,status_message=?,completed_at=NULL,updated_at=?
                       WHERE batch_item_id=?""",
                    (target, message, retried_at, row["batch_item_id"]),
                )
                if target != "duplicate":
                    retried_count += 1
            if not retried_count:
                raise RuntimeError("no retryable failed URLs remain within the attempt limit")
            con.execute(
                """UPDATE capture_batches
                   SET status='running',completed_at=NULL,updated_at=? WHERE batch_id=?""",
                (retried_at, batch_id),
            )
        self._ensure_worker()
        self._wake.set()
        result = replay_snapshot(batch_id)
        result["retried"] = retried_count
        return result

    def claim_next(self) -> dict | None:
        with transaction() as con:
            batch = con.execute(
                """SELECT * FROM capture_batches WHERE status='running'
                   ORDER BY started_at,created_at LIMIT 1"""
            ).fetchone()
            if not batch:
                return None
            lease_seconds = settings.capture_page_timeout_seconds * 3 + 60
            stale_before = (datetime.now(timezone.utc) - timedelta(seconds=lease_seconds)).isoformat()
            stale = con.execute(
                """SELECT * FROM capture_batch_items
                   WHERE batch_id=? AND status IN ('opening','capturing') AND updated_at<?""",
                (batch["batch_id"], stale_before),
            ).fetchall()
            for stale_item in stale:
                recovered_at = now_iso()
                if _reconcile_owned_capture(
                    con,
                    stale_item,
                    "Recovered listing evidence after browser capture lease expired",
                    recovered_at,
                ):
                    continue
                retry = stale_item["attempt_count"] < batch["max_attempts"]
                target = "pending" if retry else "capture_failed"
                con.execute(
                    """UPDATE capture_batch_items
                       SET status=?,status_message='Browser capture lease expired',completed_at=?,
                           updated_at=?,last_error_type='capture_timeout',
                           last_error_message='Chrome stopped reporting this capture',last_error_at=?
                       WHERE batch_item_id=?""",
                    (
                        target,
                        None if retry else recovered_at,
                        recovered_at,
                        recovered_at,
                        stale_item["batch_item_id"],
                    ),
                )
                con.execute(
                    """UPDATE capture_batch_attempts
                       SET status='capture_timeout',finished_at=?,error_type='capture_timeout',
                           error_message='Chrome stopped reporting this capture'
                       WHERE batch_item_id=? AND finished_at IS NULL""",
                    (recovered_at, stale_item["batch_item_id"]),
                )
            active = con.execute(
                """SELECT 1 FROM capture_batch_items
                   WHERE batch_id=? AND status IN ('opening','capturing','captured','processing') LIMIT 1""",
                (batch["batch_id"],),
            ).fetchone()
            if active:
                return None
            while True:
                item = con.execute(
                    """SELECT * FROM capture_batch_items
                       WHERE batch_id=? AND status='pending' AND attempt_count<?
                       ORDER BY row_number LIMIT 1""",
                    (batch["batch_id"], batch["max_attempts"]),
                ).fetchone()
                if not item:
                    _finish_batch_if_possible(con, batch["batch_id"])
                    return None
                if _reconcile_owned_capture(
                    con,
                    item,
                    "Recovered listing evidence committed before queue acknowledgement",
                    now_iso(),
                ):
                    return None
                try:
                    _normalized, _platform, marketplace_listing_id = validate_import_url(item["source_url"])
                except ValueError:
                    marketplace_listing_id = None
                existing = _existing_listing(
                    con,
                    item["source_url_hash"],
                    item["platform"],
                    marketplace_listing_id,
                )
                if existing:
                    completed_at = now_iso()
                    con.execute(
                        """UPDATE capture_batch_items
                           SET status='duplicate',status_message='Already captured before replay',
                               listing_id=?,completed_at=?,updated_at=?,last_error_type='already_captured',
                               last_error_message=?,last_error_at=? WHERE batch_item_id=?""",
                        (
                            existing["listing_id"],
                            completed_at,
                            completed_at,
                            f"Existing listing status: {existing['status']}",
                            completed_at,
                            item["batch_item_id"],
                        ),
                    )
                    continue
                attempt = item["attempt_count"] + 1
                started_at = now_iso()
                con.execute(
                    """UPDATE capture_batch_items
                       SET status='opening',status_message='Opening listing in Chrome',attempt_count=?,
                           started_at=COALESCE(started_at,?),completed_at=NULL,updated_at=?,
                           last_error_type=NULL,last_error_message=NULL,last_error_at=NULL
                       WHERE batch_item_id=? AND status='pending'""",
                    (attempt, started_at, started_at, item["batch_item_id"]),
                )
                con.execute(
                    """INSERT INTO capture_batch_attempts(
                           attempt_id,batch_item_id,attempt_number,started_at,status
                       ) VALUES(?,?,?,?,?)""",
                    (str(uuid.uuid4()), item["batch_item_id"], attempt, started_at, "opening"),
                )
                claimed = con.execute(
                    "SELECT * FROM capture_batch_items WHERE batch_item_id=?",
                    (item["batch_item_id"],),
                ).fetchone()
                return {
                    **dict(claimed),
                    "batch_name": batch["name"],
                    "original_filename": batch["original_filename"],
                    "page_timeout_seconds": settings.capture_page_timeout_seconds,
                }

    def update_item(
        self,
        batch_item_id: str,
        *,
        status: str,
        status_message: str | None = None,
        listing_id: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> dict:
        if status not in CLIENT_RESULT_STATUSES:
            raise ValueError("unsupported replay item status")
        message = _clean_text(status_message, 500)
        error_kind = _clean_text(error_type, 100)
        error_text = _clean_text(error_message, 2000)
        updated_at = now_iso()
        with transaction() as con:
            item = con.execute(
                """SELECT item.*,batch.status AS batch_status
                   FROM capture_batch_items item
                   JOIN capture_batches batch ON batch.batch_id=item.batch_id
                   WHERE item.batch_item_id=?""",
                (batch_item_id,),
            ).fetchone()
            if not item:
                raise KeyError(batch_item_id)
            if item["status"] not in {"opening", "capturing"}:
                raise RuntimeError(f"item cannot update from {item['status']}")
            if status == "capturing" and item["status"] != "opening":
                raise RuntimeError("item is already capturing")
            if status not in {"capturing", "captured"} and _reconcile_owned_capture(
                con,
                item,
                "Listing evidence was stored before the browser reported a failure",
                updated_at,
            ):
                batch_id = item["batch_id"]
                reconciled = True
            else:
                reconciled = False
            if not reconciled and status == "captured":
                if not listing_id:
                    raise ValueError("captured replay item needs a listing_id")
                listing = con.execute(
                    """SELECT listing_id FROM listings
                       WHERE listing_id=? AND capture_source='csv_batch' AND capture_batch_id=?""",
                    (listing_id, item["batch_id"]),
                ).fetchone()
                if not listing:
                    raise ValueError("listing does not belong to this replay batch")
            if not reconciled:
                terminal = status != "capturing"
                completed_at = updated_at if terminal and status != "captured" else None
                con.execute(
                    """UPDATE capture_batch_items
                       SET status=?,status_message=?,listing_id=COALESCE(?,listing_id),completed_at=?,
                           updated_at=?,last_error_type=?,last_error_message=?,last_error_at=?
                       WHERE batch_item_id=?""",
                    (
                        status,
                        message or status.replace("_", " ").title(),
                        listing_id,
                        completed_at,
                        updated_at,
                        error_kind,
                        error_text,
                        updated_at if error_kind or error_text else None,
                        batch_item_id,
                    ),
                )
                if terminal:
                    con.execute(
                        """UPDATE capture_batch_attempts
                           SET status=?,finished_at=?,error_type=?,error_message=?
                           WHERE attempt_id=(
                               SELECT attempt_id FROM capture_batch_attempts
                               WHERE batch_item_id=? AND finished_at IS NULL
                               ORDER BY attempt_number DESC LIMIT 1
                           )""",
                        (status, updated_at, error_kind, error_text, batch_item_id),
                    )
                else:
                    con.execute(
                        """UPDATE capture_batch_attempts SET status='capturing'
                           WHERE batch_item_id=? AND finished_at IS NULL""",
                        (batch_item_id,),
                    )
                batch_id = item["batch_id"]
                _finish_batch_if_possible(con, batch_id)
        self._wake.set()
        return replay_snapshot(batch_id)

    def _next_captured(self) -> dict | None:
        with transaction() as con:
            item = con.execute(
                """SELECT item.* FROM capture_batch_items item
                   JOIN capture_batches batch ON batch.batch_id=item.batch_id
                   WHERE item.status='captured' AND batch.status IN ('running','paused','stopping')
                   ORDER BY item.updated_at,item.row_number LIMIT 1"""
            ).fetchone()
            if not item:
                return None
            con.execute(
                """UPDATE capture_batch_items
                   SET status='processing',status_message='Running existing GuardianLens pipeline',updated_at=?
                   WHERE batch_item_id=? AND status='captured'""",
                (now_iso(), item["batch_item_id"]),
            )
            con.execute(
                """UPDATE capture_batch_attempts SET status='processing'
                   WHERE batch_item_id=? AND finished_at IS NULL""",
                (item["batch_item_id"],),
            )
            return dict(item)

    def _process(self, item: dict) -> None:
        try:
            result = process_listing(item["listing_id"])
            target = result["status"]
            queue_status = "duplicate" if target == "duplicate_blocked" else target
            finished_at = now_iso()
            with transaction() as con:
                con.execute(
                    """UPDATE capture_batch_items
                       SET status=?,status_message=?,completed_at=?,updated_at=?
                       WHERE batch_item_id=?""",
                    (
                        queue_status,
                        "Ready for human review" if queue_status in REVIEW_STATUSES else "Duplicate blocked by existing pipeline",
                        finished_at,
                        finished_at,
                        item["batch_item_id"],
                    ),
                )
                con.execute(
                    """UPDATE capture_batch_attempts SET status=?,finished_at=?
                       WHERE batch_item_id=? AND finished_at IS NULL""",
                    (queue_status, finished_at, item["batch_item_id"]),
                )
                _finish_batch_if_possible(con, item["batch_id"])
        except Exception as exc:
            classification = classify_error(exc)
            c = connect()
            try:
                listing = c.execute(
                    "SELECT status FROM listings WHERE listing_id=?", (item["listing_id"],)
                ).fetchone()
            finally:
                c.close()
            error_kind = listing["status"] if listing else classification.kind
            message = _clean_text(classification.user_message or str(exc), 2000) or "Processing failed"
            finished_at = now_iso()
            with transaction() as con:
                con.execute(
                    """UPDATE capture_batch_items
                       SET status='failed',status_message='Existing GuardianLens pipeline failed',
                           completed_at=?,updated_at=?,last_error_type=?,last_error_message=?,last_error_at=?
                       WHERE batch_item_id=?""",
                    (
                        finished_at,
                        finished_at,
                        error_kind,
                        message,
                        finished_at,
                        item["batch_item_id"],
                    ),
                )
                con.execute(
                    """UPDATE capture_batch_attempts
                       SET status='failed',finished_at=?,error_type=?,error_message=?
                       WHERE batch_item_id=? AND finished_at IS NULL""",
                    (finished_at, error_kind, message, item["batch_item_id"]),
                )
                _finish_batch_if_possible(con, item["batch_id"])

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._next_captured()
            if item:
                self._process(item)
                continue
            self._wake.wait(0.5)
            self._wake.clear()

    def status(self, batch_id: str | None = None) -> dict:
        return replay_snapshot(batch_id)


replay_manager = ReplayManager()
