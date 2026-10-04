from __future__ import annotations

import csv
import io
import os
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

from .collection_handoff import refresh_annotation_dataset_safely
from .capture import ALLOWED_HOSTS, LISTING_PATHS
from .config import settings
from .db import connect, now_iso, transaction
from .dedupe import canonicalize_url, url_hash
from .attention_lock import ensure_attention_idle


URL_COLUMNS = ("url", "source_url", "listing_url", "product_url")
ACTIVE_ITEM_STATUSES = ("opening", "capturing")
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
PROCESSING_ACTIVE_STATUSES = ("processing", "ai_extracted", "validating")
PROCESSING_FAILURE_STATUSES = ("processing_failed", "ai_failed", "image_failed")
CLIENT_RESULT_STATUSES = {
    "capturing",
    "captured",
    "duplicate",
    *FAILURE_STATUSES,
}
STAGE_FILE_FIELDS = (
    "source_row",
    "platform",
    "category",
    "source_url",
    "capture_ready",
    "validation_status",
    "validation_message",
    "batch_item_id",
)


class CSVImportError(ValueError):
    """The supplied upload cannot be turned into an auditable replay batch."""


def _canonical_batch_id(batch_id: str) -> str:
    try:
        return str(uuid.UUID(str(batch_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise KeyError(batch_id) from exc


def stage_file_path(batch_id: str) -> Path:
    """Return the fixed private path for a batch's human-readable Stage 1 file."""
    canonical = _canonical_batch_id(batch_id)
    return settings.data_dir / "private" / "replay_batches" / canonical / "stage_1_urls.csv"


def _encode_stage_cell(value: object) -> str:
    """Keep locally opened CSVs from treating user text as a spreadsheet formula."""
    text = str(value or "")
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _decode_stage_cell(value: object) -> str:
    text = str(value or "")
    if text.startswith("'") and text[1:].lstrip().startswith(("=", "+", "-", "@")):
        return text[1:]
    return text


def _stage_record(item: dict) -> dict[str, str]:
    status = str(item["status"])
    if "stage_capture_ready" in item:
        capture_ready = bool(item["stage_capture_ready"])
    elif status == "invalid":
        capture_ready = False
    elif status == "duplicate":
        capture_ready = bool(item.get("attempt_count")) or (
            bool(item.get("completed_at"))
            and item.get("completed_at") != item.get("created_at")
        )
    else:
        capture_ready = True
    if status in {"invalid", "duplicate"}:
        validation_status = status
        validation_message = (
            item.get("last_error_message")
            or item.get("status_message")
            or status.replace("_", " ").title()
        )
    else:
        validation_status = "validated"
        validation_message = "Validated and queued for the URL capture pass"
    return {
        "source_row": str(item["row_number"]),
        "platform": str(item.get("platform") or ""),
        "category": str(item.get("category") or ""),
        "source_url": str(item["source_url"]),
        "capture_ready": "yes" if capture_ready else "no",
        "validation_status": validation_status,
        "validation_message": str(validation_message),
        "batch_item_id": str(item["batch_item_id"]),
    }


def _write_stage_file(batch_id: str, items: list[dict]) -> Path:
    path = stage_file_path(batch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=STAGE_FILE_FIELDS, lineterminator="\n")
            writer.writeheader()
            for item in sorted(items, key=lambda row: int(row["row_number"])):
                writer.writerow(
                    {
                        key: _encode_stage_cell(value)
                        for key, value in _stage_record(item).items()
                    }
                )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _read_stage_file(batch_id: str) -> dict[str, dict[str, str]]:
    path = stage_file_path(batch_id)
    if not path.is_file():
        raise RuntimeError(
            "Stage 1 URL file is missing. Restart GuardianLens to restore it before capture."
        )
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != STAGE_FILE_FIELDS:
                raise RuntimeError("Stage 1 URL file has an unexpected header.")
            rows: dict[str, dict[str, str]] = {}
            for raw in reader:
                if None in raw:
                    raise RuntimeError("Stage 1 URL file contains an unexpected extra column.")
                row = {key: _decode_stage_cell(raw.get(key)) for key in STAGE_FILE_FIELDS}
                item_id = row["batch_item_id"]
                if not item_id or item_id in rows:
                    raise RuntimeError("Stage 1 URL file contains a missing or duplicate item ID.")
                rows[item_id] = row
                if len(rows) > settings.csv_import_max_rows:
                    raise RuntimeError("Stage 1 URL file exceeds the configured row limit.")
    except (OSError, csv.Error) as exc:
        raise RuntimeError(f"Stage 1 URL file cannot be read: {exc}") from exc
    return rows


def _verify_stage_rows(con, batch_id: str, rows: dict[str, dict[str, str]]) -> None:
    items = [
        dict(row)
        for row in con.execute(
            """SELECT batch_item_id,row_number,source_url,platform,category,status,
                      status_message,last_error_message,attempt_count,created_at,completed_at
               FROM capture_batch_items WHERE batch_id=? ORDER BY row_number""",
            (batch_id,),
        )
    ]
    expected_ids = {item["batch_item_id"] for item in items}
    if set(rows) != expected_ids:
        raise RuntimeError("Stage 1 URL file does not match the durable queue rows.")
    for item in items:
        staged = rows[item["batch_item_id"]]
        expected = _stage_record(item)
        for field in ("source_row", "platform", "category", "source_url", "capture_ready"):
            if staged[field] != expected[field]:
                raise RuntimeError(
                    "Stage 1 URL file was changed and no longer matches the durable queue. "
                    "Re-import the source instead of editing the staged file."
                )


def ensure_stage_file(batch_id: str, *, force: bool = False) -> Path:
    """Create or restore the Stage 1 artifact from the durable queue."""
    canonical = _canonical_batch_id(batch_id)
    path = stage_file_path(canonical)
    with closing(connect()) as con:
        batch = con.execute(
            "SELECT batch_id FROM capture_batches WHERE batch_id=?", (canonical,)
        ).fetchone()
        if not batch:
            raise KeyError(batch_id)
        if path.is_file() and not force:
            return path
        items = [
            dict(row)
            for row in con.execute(
                "SELECT * FROM capture_batch_items WHERE batch_id=? ORDER BY row_number",
                (canonical,),
            )
        ]
    return _write_stage_file(canonical, items)


def stage_file_metadata(batch_id: str) -> dict:
    path = stage_file_path(batch_id)
    try:
        if not path.is_file():
            raise FileNotFoundError(path)
        size_bytes = path.stat().st_size
        exists = True
    except OSError:
        size_bytes = 0
        exists = False
    return {
        "exists": exists,
        "filename": path.name,
        "relative_path": path.relative_to(settings.root).as_posix(),
        "view_url": f"/asset/replay-stage/{_canonical_batch_id(batch_id)}",
        "download_url": f"/asset/replay-stage/{_canonical_batch_id(batch_id)}?download=true",
        "size_bytes": size_bytes,
    }


def get_stage_file(batch_id: str) -> Path:
    canonical = _canonical_batch_id(batch_id)
    with closing(connect()) as con:
        batch = con.execute(
            "SELECT 1 FROM capture_batches WHERE batch_id=?", (canonical,)
        ).fetchone()
    if not batch:
        raise KeyError(batch_id)
    path = stage_file_path(canonical)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


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
    con.execute(
        """UPDATE capture_batch_items
           SET status=?,status_message=?,listing_id=?,completed_at=?,updated_at=?,
               last_error_type=NULL,last_error_message=NULL,last_error_at=NULL
           WHERE batch_item_id=?""",
        (
            "captured",
            message,
            listing["listing_id"],
            reconciled_at,
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
            item["stage_capture_ready"] = item["status"] == "pending"
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
    try:
        _write_stage_file(batch_id, prepared)
    except (OSError, csv.Error) as exc:
        with transaction() as con:
            con.execute("DELETE FROM capture_batches WHERE batch_id=?", (batch_id,))
        raise CSVImportError(f"Could not store the Stage 1 URL file: {exc}") from exc
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


def replay_snapshot(batch_id: str | None = None) -> dict:
    with closing(connect()) as con:
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
            return {
                "batch": None,
                "stage_file": None,
                "progress": None,
                "processing": None,
                "current": None,
                "recent_attempts": [],
                "recent_failures": [],
            }
        batch_id = batch["batch_id"]
        grouped = {
            row["status"]: row["n"]
            for row in con.execute(
                "SELECT status,COUNT(*) AS n FROM capture_batch_items WHERE batch_id=? GROUP BY status",
                (batch_id,),
            )
        }
        current = con.execute(
            """SELECT * FROM capture_batch_items
               WHERE batch_id=? AND status IN ('opening','capturing')
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
        attempts = con.execute(
            """SELECT attempt.attempt_id,attempt.attempt_number,attempt.started_at,
                      attempt.finished_at,attempt.status,attempt.error_type,attempt.error_message,
                      item.row_number,item.platform,item.source_url,item.status AS item_status
               FROM capture_batch_attempts attempt
               JOIN capture_batch_items item ON item.batch_item_id=attempt.batch_item_id
               WHERE item.batch_id=?
               ORDER BY attempt.started_at DESC,attempt.attempt_number DESC LIMIT 12""",
            (batch_id,),
        ).fetchall()
        listing_grouped = {
            row["status"]: row["n"]
            for row in con.execute(
                """SELECT status,COUNT(*) AS n FROM listings
                   WHERE capture_source='csv_batch' AND capture_batch_id=? GROUP BY status""",
                (batch_id,),
            )
        }
        total = int(batch["total_rows"])
        active = sum(grouped.get(status, 0) for status in ACTIVE_ITEM_STATUSES)
        remaining = grouped.get("pending", 0) + active
        captured = grouped.get("captured", 0)
        failed = sum(grouped.get(status, 0) for status in FAILURE_STATUSES)
        blocked = sum(
            grouped.get(status, 0)
            for status in ("blocked", "login_required", "captcha", "access_denied")
        )
        resolved = max(0, total - remaining)
        processing_active = sum(
            listing_grouped.get(status, 0) for status in PROCESSING_ACTIVE_STATUSES
        )
        processing_successful = sum(
            listing_grouped.get(status, 0) for status in REVIEW_STATUSES
        )
        processing_failed = sum(
            listing_grouped.get(status, 0) for status in PROCESSING_FAILURE_STATUSES
        )
        processing_duplicates = listing_grouped.get("duplicate_blocked", 0)
        processing_queued = listing_grouped.get("captured", 0)
        processing_total = sum(listing_grouped.values())
        processing_resolved = (
            processing_successful + processing_failed + processing_duplicates
        )
        return {
            "batch": dict(batch),
            "stage_file": stage_file_metadata(batch_id),
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
                "processed": resolved,
                "resolved": resolved,
                "attempted": con.execute(
                    "SELECT COUNT(*) AS n FROM capture_batch_items WHERE batch_id=? AND attempt_count>0",
                    (batch_id,),
                ).fetchone()["n"],
                "captured": captured,
                "successful": captured,
                "failed": failed,
                "blocked": blocked,
                "duplicates": grouped.get("duplicate", 0),
                "invalid": grouped.get("invalid", 0),
                "remaining": remaining,
                "by_status": grouped,
            },
            "processing": {
                # Informational only — this batch's contribution to the one shared
                # processing queue (see batch.py READY_TO_PROCESS_SQL). Preprocessing
                # is started/controlled from the unified batch processor, not per batch.
                "total": processing_total,
                "queued": processing_queued,
                "active": processing_active,
                "resolved": processing_resolved,
                "successful": processing_successful,
                "failed": processing_failed,
                "duplicates": processing_duplicates,
                "remaining": processing_queued + processing_active,
                "by_status": listing_grouped,
            },
            "current": dict(current) if current else None,
            "recent_attempts": [dict(row) for row in attempts],
            "recent_failures": [dict(row) for row in failures],
        }


def _finish_batch_if_possible(con, batch_id: str) -> bool:
    """Return True if this call moved the batch into a terminal state.

    Callers refresh the annotation dataset once, after their write
    transaction commits, only when this returns True — replay runs many
    items per batch, so per-item refreshes would be wasteful and are
    intentionally skipped by the capture layer while a batch is active.
    """

    batch = con.execute(
        "SELECT status FROM capture_batches WHERE batch_id=?", (batch_id,)
    ).fetchone()
    if not batch:
        return False
    active = con.execute(
        """SELECT 1 FROM capture_batch_items
           WHERE batch_id=? AND status IN ('opening','capturing') LIMIT 1""",
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
        return True
    remaining = con.execute(
        """SELECT 1 FROM capture_batch_items
           WHERE batch_id=? AND status IN ('pending','opening','capturing') LIMIT 1""",
        (batch_id,),
    ).fetchone()
    if batch["status"] == "running" and not remaining:
        completed_at = now_iso()
        con.execute(
            "UPDATE capture_batches SET status='completed',completed_at=?,updated_at=? WHERE batch_id=?",
            (completed_at, completed_at, batch_id),
        )
        return True
    return False


class ReplayManager:
    """Durable URL-capture pass. Downstream work is owned by BatchManager."""

    def __init__(self) -> None:
        self._stage_cache: dict[
            str, tuple[tuple[str, int, int], dict[str, dict[str, str]]]
        ] = {}

    def _stage_rows_for_capture(self, con, batch_id: str) -> dict[str, dict[str, str]]:
        path = stage_file_path(batch_id)
        try:
            stat = path.stat()
        except OSError as exc:
            raise RuntimeError(
                "Stage 1 URL file is missing. Restart GuardianLens to restore it before capture."
            ) from exc
        signature = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        cached = self._stage_cache.get(batch_id)
        if cached and cached[0] == signature:
            return cached[1]
        rows = _read_stage_file(batch_id)
        _verify_stage_rows(con, batch_id, rows)
        self._stage_cache[batch_id] = (signature, rows)
        return rows

    def recover(self) -> None:
        self._stage_cache.clear()
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
                con.execute(
                    """UPDATE capture_batch_items
                       SET status='capture_failed',status_message='Interrupted browser capture; explicit retry required',
                           completed_at=?,updated_at=?,last_error_type='interrupted_capture',
                           last_error_message='Backend or browser stopped during capture',last_error_at=?
                       WHERE batch_item_id=?""",
                    (
                        recovered_at,
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
            legacy_processed = con.execute(
                """SELECT batch_item_id,batch_id,listing_id FROM capture_batch_items
                   WHERE listing_id IS NOT NULL
                     AND status IN ('processing','failed','ready_for_review','needs_attention',
                                    'under_review','approved','rejected','skipped','flagged')"""
            ).fetchall()
            for item in legacy_processed:
                listing = con.execute(
                    "SELECT status FROM listings WHERE listing_id=?", (item["listing_id"],)
                ).fetchone()
                target = "captured" if listing else "capture_failed"
                con.execute(
                    """UPDATE capture_batch_items SET status=?,status_message=?,updated_at=?,
                           completed_at=COALESCE(completed_at,?),
                           last_error_type=CASE WHEN ?='capture_failed' THEN 'missing_listing' ELSE last_error_type END,
                           last_error_message=CASE WHEN ?='capture_failed' THEN 'Captured listing no longer exists' ELSE last_error_message END,
                           last_error_at=CASE WHEN ?='capture_failed' THEN ? ELSE last_error_at END
                       WHERE batch_item_id=?""",
                    (
                        target,
                        "Recovered durable capture checkpoint",
                        recovered_at,
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
        with closing(connect()) as con:
            batch_ids = [
                row["batch_id"]
                for row in con.execute("SELECT batch_id FROM capture_batches ORDER BY created_at")
            ]
        for batch_id in batch_ids:
            ensure_stage_file(batch_id)

    def shutdown(self) -> None:
        return None

    def start(self, batch_id: str) -> dict:
        with transaction() as con:
            ensure_attention_idle(con)
            batch = con.execute(
                "SELECT * FROM capture_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if not batch:
                raise KeyError(batch_id)
            if batch["status"] != "draft":
                raise RuntimeError(f"batch cannot start from {batch['status']}")
            self._stage_rows_for_capture(con, batch_id)
            seller_retry = con.execute(
                """SELECT retry_batch_id FROM seller_retry_batches
                   WHERE status IN ('running','paused','stopping') LIMIT 1"""
            ).fetchone()
            if seller_retry:
                raise RuntimeError(
                    "finish the paced seller-capture retry before starting URL capture"
                )
            active = con.execute(
                """SELECT batch_id FROM capture_batches
                   WHERE batch_id<>? AND status IN ('running','paused','stopping') LIMIT 1""",
                (batch_id,),
            ).fetchone()
            if active:
                raise RuntimeError("another CSV replay batch is already active")
            processor = con.execute(
                "SELECT command FROM processor_control WHERE control_id=1"
            ).fetchone()
            if processor and processor["command"] in {"running", "paused", "stopping"}:
                raise RuntimeError("finish the current processing run before starting URL capture")
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
            finished_batch = target == "stopping" and _finish_batch_if_possible(con, batch_id)
        if finished_batch:
            refresh_annotation_dataset_safely("replay_batch_completed")
        return replay_snapshot(batch_id)

    def retry_failed(self, batch_id: str) -> dict:
        with transaction() as con:
            batch = con.execute(
                "SELECT status,max_attempts FROM capture_batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if not batch:
                raise KeyError(batch_id)
            if batch["status"] not in {"completed", "stopped"}:
                raise RuntimeError("finish the capture pass before retrying failures")
            self._stage_rows_for_capture(con, batch_id)
            seller_retry = con.execute(
                """SELECT retry_batch_id FROM seller_retry_batches
                   WHERE status IN ('running','paused','stopping') LIMIT 1"""
            ).fetchone()
            if seller_retry:
                raise RuntimeError(
                    "finish the paced seller-capture retry before retrying URL capture failures"
                )
            processor = con.execute(
                "SELECT command FROM processor_control WHERE control_id=1"
            ).fetchone()
            if processor and processor["command"] in {"running", "paused", "stopping"}:
                raise RuntimeError("finish the current processing run before retrying capture failures")
            placeholders = ",".join("?" for _ in RETRYABLE_FAILURE_STATUSES)
            eligible = con.execute(
                f"""SELECT batch_item_id,attempt_count FROM capture_batch_items
                    WHERE batch_id=? AND status IN ({placeholders})
                      AND listing_id IS NULL AND attempt_count<max(?,1)""",
                (batch_id, *RETRYABLE_FAILURE_STATUSES, batch["max_attempts"]),
            ).fetchall()
            if not eligible:
                raise RuntimeError("no retryable failed URLs remain within the attempt limit")
            retried_at = now_iso()
            retried_count = 0
            for row in eligible:
                con.execute(
                    """UPDATE capture_batch_items
                       SET status='pending',status_message='Queued for explicit browser retry',
                           completed_at=NULL,updated_at=?
                       WHERE batch_item_id=?""",
                    (retried_at, row["batch_item_id"]),
                )
                retried_count += 1
            if not retried_count:
                raise RuntimeError("no retryable failed URLs remain within the attempt limit")
            con.execute(
                """UPDATE capture_batches
                   SET status='running',completed_at=NULL,updated_at=? WHERE batch_id=?""",
                (retried_at, batch_id),
            )
        result = replay_snapshot(batch_id)
        result["retried"] = retried_count
        return result

    def claim_next(self) -> dict | None:
        finished_batch = False
        with transaction() as con:
            batch = con.execute(
                """SELECT * FROM capture_batches WHERE status='running'
                   ORDER BY started_at,created_at LIMIT 1"""
            ).fetchone()
            if not batch:
                return None
            staged_rows = self._stage_rows_for_capture(con, batch["batch_id"])
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
                con.execute(
                    """UPDATE capture_batch_items
                       SET status='capture_timeout',status_message='Browser capture lease expired; explicit retry required',completed_at=?,
                           updated_at=?,last_error_type='capture_timeout',
                           last_error_message='Chrome stopped reporting this capture',last_error_at=?
                       WHERE batch_item_id=?""",
                    (
                        recovered_at,
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
                   WHERE batch_id=? AND status IN ('opening','capturing') LIMIT 1""",
                (batch["batch_id"],),
            ).fetchone()
            if active:
                return None
            exhausted_at = now_iso()
            con.execute(
                """UPDATE capture_batch_items
                   SET status='capture_failed',status_message='Capture attempt limit reached',
                       completed_at=?,updated_at=?,last_error_type='attempt_limit',
                       last_error_message='No automatic capture attempts remain',last_error_at=?
                   WHERE batch_id=? AND status='pending' AND attempt_count>=?""",
                (
                    exhausted_at,
                    exhausted_at,
                    exhausted_at,
                    batch["batch_id"],
                    batch["max_attempts"],
                ),
            )
            while True:
                item = con.execute(
                    """SELECT * FROM capture_batch_items
                       WHERE batch_id=? AND status='pending' AND attempt_count<?
                       ORDER BY row_number LIMIT 1""",
                    (batch["batch_id"], batch["max_attempts"]),
                ).fetchone()
                if not item:
                    finished_batch = _finish_batch_if_possible(con, batch["batch_id"])
                    break
                if _reconcile_owned_capture(
                    con,
                    item,
                    "Recovered listing evidence committed before queue acknowledgement",
                    now_iso(),
                ):
                    continue
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
                staged = staged_rows.get(item["batch_item_id"])
                if not staged or staged["capture_ready"] != "yes":
                    raise RuntimeError("The claimed URL is not capture-ready in the Stage 1 file.")
                return {
                    **dict(claimed),
                    "source_url": staged["source_url"],
                    "platform": staged["platform"],
                    "category": staged["category"] or None,
                    "batch_name": batch["name"],
                    "original_filename": batch["original_filename"],
                    "page_timeout_seconds": settings.capture_page_timeout_seconds,
                }
        if finished_batch:
            refresh_annotation_dataset_safely("replay_batch_completed")
        return None

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
                completed_at = updated_at if terminal else None
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
            finished_batch = _finish_batch_if_possible(con, batch_id)
        if finished_batch:
            refresh_annotation_dataset_safely("replay_batch_completed")
        return replay_snapshot(batch_id)

    def status(self, batch_id: str | None = None) -> dict:
        return replay_snapshot(batch_id)


replay_manager = ReplayManager()
