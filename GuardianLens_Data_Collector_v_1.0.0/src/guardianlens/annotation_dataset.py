"""Build the non-destructive, annotation-ready view of GuardianLens data.

SQLite remains the only source of truth.  This module reads one consistent
snapshot, writes a complete sibling tree, and only then publishes that tree.
No source row or image is updated, copied, moved, or deleted.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .config import settings
from .db import now_iso
from .dedupe import metadata_signature
from .pii import is_placeholder_value, residual_pii
from .states import TRANSITIONS

LOGGER = logging.getLogger(__name__)

DATASET_SCHEMA_VERSION = 1
DATASET_DIRECTORY_NAME = "annotation_dataset"

# Lifecycle order is intentional: it follows capture -> processing -> review.
# The union with TRANSITIONS below makes this resilient when a new state is
# added to the application's lifecycle map.
_BASE_LIFECYCLE_STATUSES = (
    "captured",
    "processing",
    "ai_extracted",
    "validating",
    "ready_for_review",
    "needs_attention",
    "under_review",
    "skipped",
    "flagged",
    "rejected",
    "approved",
    "capture_failed",
    "processing_failed",
    "ai_failed",
    "image_failed",
    "duplicate_blocked",
)

SOURCE_ROW_FIELDS = (
    "batch_item_id",
    "batch_id",
    "batch_name",
    "original_csv_filename",
    "row_number",
    "source_url",
    "platform",
    "category",
    "status",
    "status_message",
    "attempt_count",
    "listing_id",
    "created_at",
    "started_at",
    "completed_at",
    "updated_at",
    "last_error_type",
    "last_error_message",
    "last_error_at",
)

LISTING_FIELDS = (
    "listing_id",
    "platform",
    "marketplace_listing_id",
    "source_url",
    "page_title",
    "title",
    "description",
    "category",
    "source_category",
    "condition",
    "price",
    "currency",
    "location_state",
    "location_city",
    "account_age_days",
    "seller_rating",
    "review_count",
    "active_listing_count",
    "language",
    "status",
    "image_count",
    "primary_image_path",
    "unresolved_warning_count",
    "unresolved_warning_types",
    "missing_fields",
    "ai_extracted",
    "ai_provider",
    "ai_model",
    "ai_prompt_version",
    "captured_at",
    "processed_at",
    "approved_at",
    "rejected_at",
    "processing_run_id",
    "capture_source",
    "capture_batch_id",
    "csv_row",
    "original_csv_filename",
    "created_at",
    "updated_at",
)

IMAGE_FIELDS = (
    "image_id",
    "listing_id",
    "platform",
    "storage_path",
    "file_size_bytes",
    "width",
    "height",
    "source_position",
    "is_primary",
    "source_url",
    "created_at",
)

WARNING_FIELDS = (
    "warning_id",
    "listing_id",
    "warning_type",
    "message",
    "resolved",
    "created_at",
)

REVIEW_ACTION_FIELDS = (
    "review_action_id",
    "listing_id",
    "action",
    "previous_data",
    "updated_data",
    "started_at",
    "finished_at",
    "duration_seconds",
    "created_at",
    "reason",
)

STATUS_HISTORY_FIELDS = (
    "history_id",
    "listing_id",
    "from_status",
    "to_status",
    "timestamp",
    "reason",
)

AI_EXTRACTION_FIELDS = (
    "extraction_id",
    "listing_id",
    "provider",
    "model",
    "prompt_version",
    "created_at",
    "status",
    "error",
)

CAPTURE_ATTEMPT_FIELDS = (
    "attempt_id",
    "batch_item_id",
    "batch_id",
    "row_number",
    "listing_id",
    "attempt_number",
    "started_at",
    "finished_at",
    "status",
    "error_type",
    "error_message",
)

PROCESSING_RUN_FIELDS = (
    "run_id",
    "capture_batch_id",
    "started_at",
    "finished_at",
    "duration_seconds",
    "duration_limit_minutes",
    "item_limit",
    "status",
    "attempted",
    "processed",
    "successful",
    "duplicates",
    "ai_failures",
    "image_failures",
    "privacy_warnings",
    "needs_attention",
    "other_failures",
    "failed",
)

QUALITY_SUMMARY_FIELDS = ("metric", "count", "description")
QUALITY_FINDING_FIELDS = (
    "finding_type",
    "severity",
    "listing_id",
    "image_id",
    "related_listing_ids",
    "count",
    "details",
)

_ANNOTATION_VALUE_FIELDS = (
    "title",
    "description",
    "category",
    "condition",
    "price",
    "currency",
    "location_state",
    "location_city",
    "account_age_days",
    "seller_rating",
    "review_count",
    "active_listing_count",
    "language",
)
_APPROVAL_REQUIRED_FIELDS = (
    "title",
    "description",
    "category",
    "condition",
    "price",
    "currency",
    "location_state",
)
_PII_FREE_TEXT_FIELDS = (
    "title",
    "description",
    "condition",
    "location_state",
    "location_city",
    "language",
)
_SELLER_SIGNAL_FIELDS = (
    "account_age_days",
    "seller_rating",
    "review_count",
    "active_listing_count",
)
_CORRECTION_FIELDS = frozenset(_ANNOTATION_VALUE_FIELDS)

_FORMULA_PREFIXES = ("=", "+", "-", "@")
_FORMULA_LEADING_SPACE = " \t\r\n\v\f\ufeff"
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:openai|anthropic|omniroute|gemini)?[_-]?(?:api[_-]?key|access[_-]?token|auth[_-]?token)\b"
    r"\s*[:=]\s*[^\s,;]+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_COMMON_SECRET_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|sk-ant-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{12,})\b"
)
_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|auth[_-]?token|token|key)=)[^&#\s]+"
)
_PRIVATE_RELATIVE_PATH_RE = re.compile(
    r"(?i)(?:data[\\/]+(?:soft_test[\\/]+runtime[\\/]+)?private[\\/]+)[^\r\n,;]*"
)

_REFRESH_LOCK = threading.RLock()
_STATUS_LOCK = threading.Lock()
_LAST_STATUS: dict[str, Any] | None = None


def _dataset_root() -> Path:
    return settings.data_dir / "exports" / DATASET_DIRECTORY_NAME


def _is_missing(value: Any) -> bool:
    return value is None or value == ""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _redact_sensitive_text(value: Any) -> Any:
    """Redact credential-shaped values and private filesystem references.

    Most exported columns never select private values in the first place.  The
    redactor is a second boundary for free-form audit messages and source URLs.
    """

    if not isinstance(value, str) or not value:
        return value
    text = value
    for configured_secret in (
        settings.openai_api_key,
        settings.anthropic_api_key,
        settings.omniroute_api_key,
        settings.gemini_api_key,
    ):
        if configured_secret:
            text = text.replace(configured_secret, "[secret-redacted]")
    text = _SENSITIVE_ASSIGNMENT_RE.sub("[secret-redacted]", text)
    text = _BEARER_RE.sub("Bearer [secret-redacted]", text)
    text = _COMMON_SECRET_RE.sub("[secret-redacted]", text)
    text = _SENSITIVE_QUERY_RE.sub(r"\1[secret-redacted]", text)
    text = _PRIVATE_RELATIVE_PATH_RE.sub("[private-path-redacted]", text)

    private_root = (settings.data_dir / "private").resolve()
    for rendered in (str(private_root), private_root.as_posix()):
        if rendered:
            text = text.replace(rendered, "[private-path-redacted]")
    return text


def _formula_safe(value: Any) -> Any:
    if isinstance(value, str):
        candidate = value.lstrip(_FORMULA_LEADING_SPACE)
        if value.startswith(("\t", "\r", "\n")) or candidate.startswith(_FORMULA_PREFIXES):
            return "'" + value
    return value


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    return _formula_safe(_redact_sensitive_text(value))


def _filtered_correction_json(value: Any) -> str | None:
    """Retain human corrections while dropping non-annotation/private keys."""

    if value in (None, ""):
        return None
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    filtered = {
        key: _redact_sensitive_text(item)
        for key, item in parsed.items()
        if key in _CORRECTION_FIELDS
    }
    return json.dumps(filtered, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalise_product_path(recorded: Any) -> tuple[str | None, Path | None, str | None]:
    """Return (safe project-relative path, resolved path, problem)."""

    if not isinstance(recorded, str) or not recorded.strip():
        return None, None, "missing image storage path"
    path = Path(recorded)
    candidate = path if path.is_absolute() else settings.root / path
    try:
        resolved = candidate.resolve()
        project_root = settings.root.resolve()
        product_root = (settings.data_dir / "images").resolve()
    except OSError:
        return None, None, "image storage path could not be resolved"
    if not _is_within(resolved, product_root) or not _is_within(resolved, project_root):
        return None, resolved, "image storage path is outside the canonical product-image directory"
    return resolved.relative_to(project_root).as_posix(), resolved, None


def _recorded_path_exists(recorded: Any) -> bool:
    if not isinstance(recorded, str) or not recorded.strip():
        return False
    path = Path(recorded)
    candidate = path if path.is_absolute() else settings.root / path
    try:
        return candidate.resolve().is_file()
    except OSError:
        return False


def _as_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _open_read_only_database() -> sqlite3.Connection:
    path = settings.db_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"GuardianLens database does not exist: {path}")
    con = sqlite3.connect(
        f"{path.as_uri()}?mode=ro",
        uri=True,
        timeout=30,
        isolation_level=None,
        check_same_thread=False,
    )
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _read_snapshot() -> dict[str, list[dict[str, Any]]]:
    """Materialise every input while one SQLite read transaction is active."""

    con = _open_read_only_database()
    try:
        con.execute("BEGIN")
        # The first read pins the WAL snapshot used by all queries below.
        con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        snapshot = {
            "source_rows": _as_dicts(
                con.execute(
                    """
                    SELECT item.*,batch.name AS batch_name,
                           batch.original_filename AS original_csv_filename
                    FROM capture_batch_items AS item
                    JOIN capture_batches AS batch ON batch.batch_id=item.batch_id
                    ORDER BY batch.created_at,batch.batch_id,item.row_number,item.batch_item_id
                    """
                )
            ),
            "listings": _as_dicts(
                con.execute("SELECT * FROM listings ORDER BY listing_id")
            ),
            "images": _as_dicts(
                con.execute(
                    "SELECT * FROM images ORDER BY listing_id,source_position,image_id"
                )
            ),
            "warnings": _as_dicts(
                con.execute(
                    "SELECT * FROM warnings ORDER BY listing_id,created_at,warning_id"
                )
            ),
            "review_actions": _as_dicts(
                con.execute(
                    "SELECT * FROM review_actions ORDER BY listing_id,created_at,review_action_id"
                )
            ),
            "status_history": _as_dicts(
                con.execute(
                    "SELECT * FROM status_history ORDER BY listing_id,timestamp,history_id"
                )
            ),
            "ai_extractions": _as_dicts(
                con.execute(
                    "SELECT * FROM ai_extractions ORDER BY listing_id,created_at,extraction_id"
                )
            ),
            "capture_attempts": _as_dicts(
                con.execute(
                    """
                    SELECT attempt.*,item.batch_id,item.row_number,item.listing_id
                    FROM capture_batch_attempts AS attempt
                    JOIN capture_batch_items AS item
                      ON item.batch_item_id=attempt.batch_item_id
                    ORDER BY item.batch_id,item.row_number,attempt.attempt_number,attempt.attempt_id
                    """
                )
            ),
            "processing_runs": _as_dicts(
                con.execute(
                    "SELECT * FROM processing_runs ORDER BY started_at,run_id"
                )
            ),
        }
        con.rollback()
        return snapshot
    except Exception:
        try:
            con.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        con.close()


def _lifecycle_statuses(listings: Sequence[Mapping[str, Any]]) -> list[str]:
    known: set[str] = set(_BASE_LIFECYCLE_STATUSES)
    known.update(TRANSITIONS)
    for targets in TRANSITIONS.values():
        known.update(targets)
    discovered = {
        str(row["status"])
        for row in listings
        if row.get("status") is not None and str(row["status"])
    }
    ordered = [status for status in _BASE_LIFECYCLE_STATUSES if status in known]
    ordered.extend(sorted((known | discovered) - set(ordered)))
    return ordered


def _status_filename(status: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", status):
        return f"{status}.csv"
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", status).strip("_") or "status"
    digest = hashlib.sha256(status.encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{digest}.csv"


def _similar_image_groups(images: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    """Group listings whose 64-bit perceptual hashes differ by at most 5 bits.

    Six hash chunks provide an exact candidate filter: two 64-bit values at
    Hamming distance <= 5 must share at least one of the six chunks.
    """

    hashes_to_listings: dict[int, set[str]] = defaultdict(set)
    for image in images:
        raw_hash = image.get("perceptual_hash")
        listing_id = image.get("listing_id")
        if not raw_hash or not listing_id:
            continue
        try:
            value = int(str(raw_hash), 16)
        except ValueError:
            continue
        if value < 0 or value >= 1 << 64:
            continue
        hashes_to_listings[value].add(str(listing_id))

    parent: dict[str, str] = {}

    def find(item: str) -> str:
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            if left_root > right_root:
                left_root, right_root = right_root, left_root
            parent[right_root] = left_root

    representative: dict[int, str] = {}
    for hash_value, listing_ids in hashes_to_listings.items():
        ordered_ids = sorted(listing_ids)
        if not ordered_ids:
            continue
        representative[hash_value] = ordered_ids[0]
        for listing_id in ordered_ids:
            union(ordered_ids[0], listing_id)

    chunks = ((0, 11), (11, 11), (22, 11), (33, 11), (44, 10), (54, 10))
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for hash_value in sorted(hashes_to_listings):
        candidates: set[int] = set()
        for index, (shift, width) in enumerate(chunks):
            chunk = (hash_value >> shift) & ((1 << width) - 1)
            candidates.update(buckets[(index, chunk)])
        for candidate in candidates:
            if (hash_value ^ candidate).bit_count() <= 5:
                union(representative[hash_value], representative[candidate])
        for index, (shift, width) in enumerate(chunks):
            chunk = (hash_value >> shift) & ((1 << width) - 1)
            buckets[(index, chunk)].append(hash_value)

    groups: dict[str, set[str]] = defaultdict(set)
    for listing_id in parent:
        groups[find(listing_id)].add(listing_id)
    return sorted(
        (sorted(group) for group in groups.values() if len(group) > 1),
        key=lambda group: (group[0], len(group), group),
    )


def _approval_blockers(
    listing: Mapping[str, Any],
    images: Sequence[Mapping[str, Any]],
    approved: Sequence[Mapping[str, Any]],
    configured_categories: set[str],
) -> list[str]:
    blockers: list[str] = []
    missing_required = [field for field in _APPROVAL_REQUIRED_FIELDS if _is_missing(listing.get(field))]
    if missing_required:
        blockers.append("required fields missing: " + ", ".join(missing_required))

    placeholder_fields = [
        field
        for field in _PII_FREE_TEXT_FIELDS
        if is_placeholder_value(listing.get(field))
    ]
    if placeholder_fields:
        blockers.append("placeholder values: " + ", ".join(placeholder_fields))
    free_text = "\n".join(str(listing.get(field) or "") for field in _PII_FREE_TEXT_FIELDS)
    if residual_pii(free_text):
        blockers.append("residual PII")
    if listing.get("category") not in configured_categories:
        blockers.append("category is not configured")

    if not images:
        blockers.append("no product image records")
    else:
        unavailable = 0
        unsafe = 0
        for image in images:
            _safe_path, resolved, problem = _normalise_product_path(image.get("storage_path"))
            if problem:
                unsafe += 1
            elif resolved is None or not resolved.is_file():
                unavailable += 1
        if unsafe:
            blockers.append(f"{unsafe} product image path(s) outside the canonical directory")
        if unavailable:
            blockers.append(f"{unavailable} product image file(s) missing")

    missing_seller = [field for field in _SELLER_SIGNAL_FIELDS if _is_missing(listing.get(field))]
    if missing_seller:
        blockers.append("seller fields missing: " + ", ".join(missing_seller))

    listing_id = listing.get("listing_id")
    for other in approved:
        if other.get("listing_id") == listing_id:
            continue
        same_source = bool(
            listing.get("source_url_hash")
            and listing.get("source_url_hash") == other.get("source_url_hash")
        )
        same_marketplace_id = bool(
            listing.get("marketplace_listing_id")
            and listing.get("platform") == other.get("platform")
            and listing.get("marketplace_listing_id") == other.get("marketplace_listing_id")
        )
        if same_source or same_marketplace_id:
            blockers.append("source duplicates an approved listing")
            break

    if not missing_required:
        signature = metadata_signature(
            str(listing.get("platform") or ""),
            listing.get("title"),
            listing.get("description"),
            listing.get("price"),
        )
        if any(
            other.get("listing_id") != listing_id
            and other.get("metadata_signature") == signature
            for other in approved
        ):
            blockers.append("metadata duplicates an approved listing")

    approved_hashes = {
        image.get("sha256")
        for other in approved
        if other.get("listing_id") != listing_id
        for image in other.get("_images", ())
        if image.get("sha256")
    }
    if approved_hashes and any(image.get("sha256") in approved_hashes for image in images):
        blockers.append("product image exactly duplicates an approved listing")
    return blockers


def _build_export(
    snapshot: Mapping[str, list[dict[str, Any]]]
) -> tuple[
    dict[str, tuple[Sequence[str], list[dict[str, Any]]]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    warnings_by_listing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for warning in snapshot["warnings"]:
        if not warning.get("resolved"):
            warnings_by_listing[str(warning["listing_id"])].append(warning)

    images_by_listing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    image_rows: list[dict[str, Any]] = []
    image_problems: dict[str, tuple[str | None, str]] = {}
    for image in snapshot["images"]:
        images_by_listing[str(image["listing_id"])].append(image)
        storage_path, resolved, problem = _normalise_product_path(image.get("storage_path"))
        if problem:
            image_problems[str(image["image_id"])] = (str(image["listing_id"]), problem)
        elif resolved is None or not resolved.is_file():
            image_problems[str(image["image_id"])] = (
                str(image["listing_id"]),
                "canonical product image file is missing",
            )
        exported = {field: image.get(field) for field in IMAGE_FIELDS}
        exported["storage_path"] = storage_path
        exported["source_url"] = _redact_sensitive_text(exported.get("source_url"))
        image_rows.append(exported)

    listing_rows: list[dict[str, Any]] = []
    source_listings = snapshot["listings"]
    for listing in source_listings:
        listing_id = str(listing["listing_id"])
        related_images = images_by_listing.get(listing_id, [])
        public_paths: list[tuple[int, int, str]] = []
        for image in related_images:
            path, _resolved, problem = _normalise_product_path(image.get("storage_path"))
            if path is not None and not problem:
                public_paths.append(
                    (
                        0 if image.get("is_primary") else 1,
                        int(image.get("source_position") or 0),
                        path,
                    )
                )
        unresolved = warnings_by_listing.get(listing_id, [])
        exported = {field: listing.get(field) for field in LISTING_FIELDS}
        exported.update(
            {
                "source_url": _redact_sensitive_text(listing.get("source_url")),
                "image_count": len(related_images),
                "primary_image_path": min(public_paths)[2] if public_paths else None,
                "unresolved_warning_count": len(unresolved),
                "unresolved_warning_types": ";".join(
                    sorted({str(warning["warning_type"]) for warning in unresolved})
                ),
                "missing_fields": ";".join(
                    field for field in _ANNOTATION_VALUE_FIELDS if _is_missing(listing.get(field))
                ),
            }
        )
        listing_rows.append(exported)

    source_rows: list[dict[str, Any]] = []
    for item in snapshot["source_rows"]:
        exported = {field: item.get(field) for field in SOURCE_ROW_FIELDS}
        for field in ("source_url", "status_message", "last_error_message"):
            exported[field] = _redact_sensitive_text(exported.get(field))
        source_rows.append(exported)

    warning_rows = []
    for warning in snapshot["warnings"]:
        exported = {field: warning.get(field) for field in WARNING_FIELDS}
        exported["message"] = _redact_sensitive_text(exported.get("message"))
        warning_rows.append(exported)

    review_rows = []
    for action in snapshot["review_actions"]:
        exported = {field: action.get(field) for field in REVIEW_ACTION_FIELDS}
        exported["previous_data"] = _filtered_correction_json(action.get("previous_data"))
        exported["updated_data"] = _filtered_correction_json(action.get("updated_data"))
        exported["reason"] = _redact_sensitive_text(exported.get("reason"))
        review_rows.append(exported)

    history_rows = []
    for history in snapshot["status_history"]:
        exported = {field: history.get(field) for field in STATUS_HISTORY_FIELDS}
        exported["reason"] = _redact_sensitive_text(exported.get("reason"))
        history_rows.append(exported)

    extraction_rows = []
    for extraction in snapshot["ai_extractions"]:
        # structured_output is intentionally not selected into the exported row.
        exported = {field: extraction.get(field) for field in AI_EXTRACTION_FIELDS}
        exported["error"] = _redact_sensitive_text(exported.get("error"))
        extraction_rows.append(exported)

    attempt_rows = []
    for attempt in snapshot["capture_attempts"]:
        exported = {field: attempt.get(field) for field in CAPTURE_ATTEMPT_FIELDS}
        exported["error_message"] = _redact_sensitive_text(exported.get("error_message"))
        attempt_rows.append(exported)

    processing_rows = [
        {field: run.get(field) for field in PROCESSING_RUN_FIELDS}
        for run in snapshot["processing_runs"]
    ]

    findings: list[dict[str, Any]] = []
    listings_without_images = [
        str(listing["listing_id"])
        for listing in source_listings
        if not images_by_listing.get(str(listing["listing_id"]))
    ]
    for listing_id in listings_without_images:
        findings.append(
            {
                "finding_type": "missing_product_images",
                "severity": "warning",
                "listing_id": listing_id,
                "image_id": None,
                "related_listing_ids": None,
                "count": 0,
                "details": "No product image records are registered for this listing.",
            }
        )
    for image_id, (listing_id, problem) in sorted(image_problems.items()):
        findings.append(
            {
                "finding_type": "product_image_storage_problem",
                "severity": "warning",
                "listing_id": listing_id,
                "image_id": image_id,
                "related_listing_ids": None,
                "count": 1,
                "details": problem,
            }
        )
    for listing_id, unresolved in sorted(warnings_by_listing.items()):
        warning_types = sorted({str(warning["warning_type"]) for warning in unresolved})
        findings.append(
            {
                "finding_type": "unresolved_warnings",
                "severity": "warning",
                "listing_id": listing_id,
                "image_id": None,
                "related_listing_ids": None,
                "count": len(unresolved),
                "details": "Unresolved warning types: " + ", ".join(warning_types),
            }
        )

    similar_groups = _similar_image_groups(snapshot["images"])
    for group in similar_groups:
        findings.append(
            {
                "finding_type": "visually_similar_image_group",
                "severity": "review",
                "listing_id": group[0],
                "image_id": None,
                "related_listing_ids": ";".join(group[1:]),
                "count": len(group),
                "details": "Listings have product images within perceptual Hamming distance 5.",
            }
        )

    approved = [listing for listing in source_listings if listing.get("status") == "approved"]
    for listing in approved:
        missing_evidence: list[str] = []
        for field, label in (
            ("screenshot_path", "listing screenshot"),
            ("seller_screenshot_path", "seller screenshot"),
            ("staging_text_path", "staging text"),
        ):
            if listing.get(field) and not _recorded_path_exists(listing.get(field)):
                missing_evidence.append(label)
        if missing_evidence:
            findings.append(
                {
                    "finding_type": "stale_private_evidence_reference",
                    "severity": "info",
                    "listing_id": listing["listing_id"],
                    "image_id": None,
                    "related_listing_ids": None,
                    "count": len(missing_evidence),
                    "details": "Recorded private evidence is no longer present: "
                    + ", ".join(missing_evidence),
                }
            )

    approved_with_images: list[dict[str, Any]] = []
    for listing in approved:
        enriched = dict(listing)
        enriched["_images"] = images_by_listing.get(str(listing["listing_id"]), [])
        approved_with_images.append(enriched)
    try:
        configured_categories = {str(item["name"]) for item in settings.categories()}
    except (OSError, KeyError, TypeError):
        configured_categories = set()
    review_ready_blockers = 0
    for listing in source_listings:
        if listing.get("status") != "ready_for_review":
            continue
        listing_id = str(listing["listing_id"])
        blockers = _approval_blockers(
            listing,
            images_by_listing.get(listing_id, []),
            approved_with_images,
            configured_categories,
        )
        if blockers:
            review_ready_blockers += 1
            findings.append(
                {
                    "finding_type": "review_ready_approval_blocker",
                    "severity": "warning",
                    "listing_id": listing_id,
                    "image_id": None,
                    "related_listing_ids": None,
                    "count": len(blockers),
                    "details": "; ".join(blockers),
                }
            )

    stale_approved_count = len(
        {
            str(finding["listing_id"])
            for finding in findings
            if finding["finding_type"] == "stale_private_evidence_reference"
        }
    )
    unresolved_warning_count = sum(len(items) for items in warnings_by_listing.values())
    quality_metrics = [
        ("source_rows", len(source_rows), "All imported intake rows, including failed outcomes."),
        ("listings", len(listing_rows), "Captured listing records in the annotation view."),
        ("images", len(image_rows), "Canonical product-image records; files are not copied."),
        (
            "listings_without_product_images",
            len(listings_without_images),
            "Listings with no registered product-image row.",
        ),
        (
            "product_image_storage_problems",
            len(image_problems),
            "Image rows whose canonical path is unsafe or whose file is missing.",
        ),
        (
            "unresolved_warnings",
            unresolved_warning_count,
            "All currently unresolved warning records.",
        ),
        (
            "listings_with_unresolved_warnings",
            len(warnings_by_listing),
            "Listings that currently have one or more unresolved warnings.",
        ),
        (
            "visually_similar_image_groups",
            len(similar_groups),
            "Cross-listing image groups within perceptual Hamming distance 5.",
        ),
        (
            "approved_with_stale_private_evidence_references",
            stale_approved_count,
            "Approved listings retaining a reference to private evidence that is absent.",
        ),
        (
            "review_ready_with_approval_blockers",
            review_ready_blockers,
            "Ready-for-review listings with a known blocker under the approval rules.",
        ),
    ]
    summary_rows = [
        {"metric": metric, "count": count, "description": description}
        for metric, count, description in quality_metrics
    ]
    findings.sort(
        key=lambda row: (
            str(row.get("finding_type") or ""),
            str(row.get("listing_id") or ""),
            str(row.get("image_id") or ""),
            str(row.get("related_listing_ids") or ""),
        )
    )

    csv_files: dict[str, tuple[Sequence[str], list[dict[str, Any]]]] = {
        "master/source_rows.csv": (SOURCE_ROW_FIELDS, source_rows),
        "master/listings.csv": (LISTING_FIELDS, listing_rows),
        "master/images.csv": (IMAGE_FIELDS, image_rows),
        "audit/warnings.csv": (WARNING_FIELDS, warning_rows),
        "audit/review_actions.csv": (REVIEW_ACTION_FIELDS, review_rows),
        "audit/status_history.csv": (STATUS_HISTORY_FIELDS, history_rows),
        "audit/ai_extractions.csv": (AI_EXTRACTION_FIELDS, extraction_rows),
        "audit/capture_attempts.csv": (CAPTURE_ATTEMPT_FIELDS, attempt_rows),
        "audit/processing_runs.csv": (PROCESSING_RUN_FIELDS, processing_rows),
        "test/annotation_test.csv": (
            LISTING_FIELDS,
            [row for row in listing_rows if row.get("status") == "approved"],
        ),
        "quality/summary.csv": (QUALITY_SUMMARY_FIELDS, summary_rows),
        "quality/findings.csv": (QUALITY_FINDING_FIELDS, findings),
    }

    status_counts: dict[str, int] = {}
    status_files: dict[str, str] = {}
    for status in _lifecycle_statuses(source_listings):
        relative_path = f"by_status/{_status_filename(status)}"
        status_files[status] = relative_path
        rows = [row for row in listing_rows if row.get("status") == status]
        status_counts[status] = len(rows)
        csv_files[relative_path] = (LISTING_FIELDS, rows)

    counts = {
        "source_rows": len(source_rows),
        "listings": len(listing_rows),
        "images": len(image_rows),
        "warnings": len(warning_rows),
        "unresolved_warnings": unresolved_warning_count,
        "review_actions": len(review_rows),
        "status_history": len(history_rows),
        "ai_extractions": len(extraction_rows),
        "capture_attempts": len(attempt_rows),
        "processing_runs": len(processing_rows),
        "approved_annotation_test": sum(
            1 for row in listing_rows if row.get("status") == "approved"
        ),
        "quality_findings": len(findings),
        "by_status": status_counts,
    }
    metadata = {"counts": counts, "status_files": status_files}
    return csv_files, findings, metadata


def _write_csv(
    path: Path,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fieldnames),
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})
        handle.flush()
        os.fsync(handle.fileno())


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readme_text(generated_at: str, counts: Mapping[str, Any]) -> str:
    return f"""# GuardianLens annotation dataset

Generated at: {generated_at}

This directory is a generated, one-way view of the GuardianLens SQLite database.
SQLite is authoritative. Do not edit these CSV files as a way to update records:
manual CSV changes are replaced by the next refresh.

## Contents

- `master/source_rows.csv` preserves all imported rows and their exact capture outcomes.
- `master/listings.csv` contains research-safe listing fields and annotation readiness metadata.
- `master/images.csv` points to canonical project-relative product images. Images are not copied.
- `audit/` contains safe lifecycle and processing audit views; raw AI output is excluded.
- `by_status/` partitions listings by exact lifecycle status, with headers even when empty.
- `test/annotation_test.csv` is the approved-only annotation pilot. It is not an ML test split.
- `quality/` reports missing data, warnings, similar images, stale evidence references, and approval blockers.
- `manifest.json` contains counts and SHA-256 checksums for verification.

CSV files are UTF-8 with a BOM for spreadsheet compatibility. Empty database values remain
empty cells. Text that spreadsheet software could interpret as a formula is prefixed with an
apostrophe. Private evidence paths/content, credentials, database hashes, image hashes, and raw
AI structured output are excluded.

Snapshot counts: {counts['source_rows']} source rows, {counts['listings']} listings,
{counts['images']} image records, and {counts['approved_annotation_test']} approved pilot rows.
"""


def _write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    # This function is intentionally called after every other staged file has
    # been flushed and hashed.  The directory publisher then exposes the
    # complete generation as a unit.
    _write_text(path, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _stage_dataset(
    stage_root: Path,
    snapshot: Mapping[str, list[dict[str, Any]]],
    trigger: str,
    generated_at: str,
) -> dict[str, Any]:
    csv_files, _findings, metadata = _build_export(snapshot)
    csv_row_counts: dict[str, int] = {}
    for relative_path in sorted(csv_files):
        fieldnames, rows = csv_files[relative_path]
        _write_csv(stage_root / relative_path, fieldnames, rows)
        csv_row_counts[relative_path] = len(rows)

    readme_path = stage_root / "README.md"
    _write_text(readme_path, _readme_text(generated_at, metadata["counts"]))

    file_entries: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in stage_root.rglob("*") if item.is_file()):
        relative_path = path.relative_to(stage_root).as_posix()
        entry: dict[str, Any] = {
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        if relative_path in csv_row_counts:
            entry["rows"] = csv_row_counts[relative_path]
        file_entries[relative_path] = entry

    manifest: dict[str, Any] = {
        "dataset": "GuardianLens annotation dataset",
        "schema_version": DATASET_SCHEMA_VERSION,
        "generated_at": generated_at,
        "trigger": trigger,
        "source_of_truth": settings.db_path.name,
        "sqlite_is_authoritative": True,
        "manual_csv_edits_are_imported": False,
        "images_copied": False,
        "manifest_published_last": True,
        "counts": metadata["counts"],
        "status_files": metadata["status_files"],
        "files": file_entries,
    }
    _write_manifest(stage_root / "manifest.json", manifest)
    return manifest


def _verified_generated_sibling(path: Path, exports_root: Path, marker: str) -> Path:
    resolved = path.resolve()
    resolved_exports = exports_root.resolve()
    if resolved.parent != resolved_exports or marker not in resolved.name:
        raise RuntimeError(f"refusing to remove an unverified generated directory: {resolved}")
    return resolved


def _remove_generated_sibling(path: Path, exports_root: Path, marker: str) -> None:
    if not path.exists():
        return
    verified = _verified_generated_sibling(path, exports_root, marker)
    shutil.rmtree(verified)


def _publish_staged_tree(stage_root: Path, target_root: Path) -> None:
    """Publish the staged tree and restore the previous tree on any failure."""

    exports_root = target_root.parent
    backup_root = exports_root / f".{DATASET_DIRECTORY_NAME}.{uuid.uuid4().hex}.backup"
    previous_moved = False
    try:
        if target_root.exists():
            os.replace(target_root, backup_root)
            previous_moved = True
        try:
            os.replace(stage_root, target_root)
        except Exception:
            if previous_moved and backup_root.exists() and not target_root.exists():
                os.replace(backup_root, target_root)
                previous_moved = False
            raise
        if previous_moved:
            _remove_generated_sibling(backup_root, exports_root, ".backup")
    finally:
        if stage_root.exists():
            _remove_generated_sibling(stage_root, exports_root, ".tmp")
        # A backup can remain only if restoring it failed.  Keeping it is safer
        # than deleting the last complete dataset generation.


@contextmanager
def _process_lock(exports_root: Path, timeout_seconds: float = 60.0):
    """Serialize publishers across Python processes as well as threads."""

    exports_root.mkdir(parents=True, exist_ok=True)
    lock_path = exports_root / f".{DATASET_DIRECTORY_NAME}.refresh.lock"
    handle = lock_path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + timeout_seconds
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("timed out waiting for annotation dataset refresh lock")
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _set_last_status(status: Mapping[str, Any]) -> dict[str, Any]:
    global _LAST_STATUS
    copied = deepcopy(dict(status))
    with _STATUS_LOCK:
        _LAST_STATUS = copied
    return deepcopy(copied)


def _manifest_status(target_root: Path) -> dict[str, Any] | None:
    manifest_path = target_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return {
        "ok": True,
        "state": "ready",
        "trigger": manifest.get("trigger"),
        "generated_at": manifest.get("generated_at"),
        "completed_at": manifest.get("generated_at"),
        "output_path": str(target_root),
        "manifest_path": str(manifest_path),
        "counts": manifest.get("counts", {}),
        "error": None,
    }


def refresh_annotation_dataset(trigger: str = "manual") -> dict[str, Any]:
    """Regenerate and atomically publish the annotation dataset.

    The function raises on failure.  Call ``refresh_annotation_dataset_safely``
    from request/background paths where a completed source transaction must not
    be affected by an export problem.
    """

    clean_trigger = str(trigger or "manual").strip()[:120] or "manual"
    target_root = _dataset_root()
    exports_root = target_root.parent
    started_at = now_iso()
    running = {
        "ok": None,
        "state": "refreshing",
        "trigger": clean_trigger,
        "started_at": started_at,
        "completed_at": None,
        "output_path": str(target_root),
        "manifest_path": str(target_root / "manifest.json"),
        "counts": {},
        "error": None,
    }
    _set_last_status(running)

    stage_root: Path | None = None
    with _REFRESH_LOCK:
        try:
            with _process_lock(exports_root):
                snapshot = _read_snapshot()
                generated_at = now_iso()
                stage_root = exports_root / (
                    f".{DATASET_DIRECTORY_NAME}.{uuid.uuid4().hex}.tmp"
                )
                stage_root.mkdir(parents=False, exist_ok=False)
                manifest = _stage_dataset(
                    stage_root,
                    snapshot,
                    clean_trigger,
                    generated_at,
                )
                _publish_staged_tree(stage_root, target_root)
                stage_root = None
            completed_at = now_iso()
            return _set_last_status(
                {
                    "ok": True,
                    "state": "ready",
                    "trigger": clean_trigger,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "generated_at": manifest["generated_at"],
                    "output_path": str(target_root),
                    "manifest_path": str(target_root / "manifest.json"),
                    "counts": manifest["counts"],
                    "error": None,
                }
            )
        except Exception as exc:
            if stage_root is not None and stage_root.exists():
                try:
                    _remove_generated_sibling(stage_root, exports_root, ".tmp")
                except OSError:
                    LOGGER.exception("Could not remove failed annotation-dataset staging directory")
            previous = _manifest_status(target_root)
            failure = {
                "ok": False,
                "state": "error",
                "trigger": clean_trigger,
                "started_at": started_at,
                "completed_at": now_iso(),
                "output_path": str(target_root),
                "manifest_path": str(target_root / "manifest.json"),
                "counts": previous.get("counts", {}) if previous else {},
                "previous_generation_available": bool(previous),
                "error": {
                    "type": type(exc).__name__,
                    "message": _redact_sensitive_text(str(exc)),
                },
            }
            _set_last_status(failure)
            raise


def refresh_annotation_dataset_safely(trigger: str) -> dict[str, Any]:
    """Refresh without allowing export failure to fail the caller's action."""

    try:
        return refresh_annotation_dataset(trigger=trigger)
    except Exception:
        LOGGER.exception("Annotation dataset refresh failed after trigger %r", trigger)
        return get_annotation_dataset_status()


# Request-path callers (review actions) must save DB state and return without
# waiting on the multi-minute full export rebuild. Rapid successive triggers
# are coalesced into a single delayed background refresh instead of one per
# action.
SCHEDULE_DEBOUNCE_SECONDS = 5.0

_SCHEDULE_LOCK = threading.Lock()
_SCHEDULE_TIMER: threading.Timer | None = None
_SCHEDULE_PENDING_TRIGGER: str | None = None


def schedule_annotation_dataset_refresh(trigger: str) -> None:
    """Debounce a background refresh; never blocks the calling thread.

    Multiple calls within ``SCHEDULE_DEBOUNCE_SECONDS`` collapse into one
    refresh, run with the most recent trigger, on a background thread.
    """

    global _SCHEDULE_TIMER, _SCHEDULE_PENDING_TRIGGER
    with _SCHEDULE_LOCK:
        _SCHEDULE_PENDING_TRIGGER = trigger
        if _SCHEDULE_TIMER is not None:
            _SCHEDULE_TIMER.cancel()
        _SCHEDULE_TIMER = threading.Timer(SCHEDULE_DEBOUNCE_SECONDS, _run_scheduled_refresh)
        _SCHEDULE_TIMER.daemon = True
        _SCHEDULE_TIMER.start()


def _run_scheduled_refresh() -> None:
    global _SCHEDULE_TIMER, _SCHEDULE_PENDING_TRIGGER
    with _SCHEDULE_LOCK:
        trigger = _SCHEDULE_PENDING_TRIGGER or "scheduled"
        _SCHEDULE_PENDING_TRIGGER = None
        _SCHEDULE_TIMER = None
    try:
        refresh_annotation_dataset(trigger=trigger)
    except Exception:
        LOGGER.exception("Scheduled annotation dataset refresh failed after trigger %r", trigger)


def _cancel_scheduled_refresh_for_tests() -> None:
    """Test-only: drop any pending debounced refresh without running it."""

    global _SCHEDULE_TIMER, _SCHEDULE_PENDING_TRIGGER
    with _SCHEDULE_LOCK:
        if _SCHEDULE_TIMER is not None:
            _SCHEDULE_TIMER.cancel()
        _SCHEDULE_TIMER = None
        _SCHEDULE_PENDING_TRIGGER = None


def get_annotation_dataset_status() -> dict[str, Any]:
    """Return the latest process status, falling back to the durable manifest."""

    target_root = _dataset_root()
    with _STATUS_LOCK:
        current = deepcopy(_LAST_STATUS)
    if current and current.get("output_path") == str(target_root):
        return current
    durable = _manifest_status(target_root)
    if durable:
        return durable
    return {
        "ok": False,
        "state": "not_generated",
        "trigger": None,
        "started_at": None,
        "completed_at": None,
        "output_path": str(target_root),
        "manifest_path": str(target_root / "manifest.json"),
        "counts": {},
        "error": None,
    }


__all__ = (
    "get_annotation_dataset_status",
    "refresh_annotation_dataset",
    "refresh_annotation_dataset_safely",
    "schedule_annotation_dataset_refresh",
)
