"""Read-only data gates shared by preprocessing, attention repair and approval."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .config import settings
from .dedupe import metadata_signature
from .errors import redact_secrets
from .images import validate_image_bytes
from .models import MAX_DESCRIPTION_LENGTH, MAX_SHORT_TEXT_LENGTH, MAX_TITLE_LENGTH
from .pii import is_placeholder_value, residual_pii, scrub_text


REQUIRED_FIELDS = (
    "title", "description", "category", "condition", "price", "currency", "location_state",
)
SELLER_SIGNAL_FIELDS = (
    "account_age_days", "seller_rating", "review_count", "active_listing_count",
)
PII_FREE_TEXT_FIELDS = (
    "title", "description", "condition", "location_state", "location_city", "language",
)
FIELD_WARNING_TYPES = frozenset({
    "missing_field", "placeholder_value", "category", "invalid_type", "invalid_range",
})
TEXT_LIMITS = {
    "title": MAX_TITLE_LENGTH,
    "description": MAX_DESCRIPTION_LENGTH,
    "category": MAX_SHORT_TEXT_LENGTH,
    "condition": MAX_SHORT_TEXT_LENGTH,
    "currency": 8,
    "location_state": MAX_SHORT_TEXT_LENGTH,
    "location_city": MAX_SHORT_TEXT_LENGTH,
    "language": 100,
}
NUMERIC_LIMITS = {
    "price": 1_000_000_000,
    "account_age_days": 100_000,
    "seller_rating": 5,
    "review_count": 100_000_000,
    "active_listing_count": 100_000_000,
}
INTEGER_FIELDS = {"account_age_days", "review_count", "active_listing_count"}


def _finding(code: str, field: str | None, message: str, action: str = "repair") -> dict:
    return {"code": code, "field": field, "message": message, "action": action}


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_fields(record: dict, categories: list[str] | None = None) -> list[dict]:
    """Return current blockers without coercing values or accepting unknown as zero."""
    record = dict(record)
    findings = []
    for field in (*REQUIRED_FIELDS, *SELLER_SIGNAL_FIELDS):
        if _missing(record.get(field)):
            label = "seller/behavioural field" if field in SELLER_SIGNAL_FIELDS else "field"
            findings.append(_finding("missing_field", field, f"Missing required {label}: {field}"))
    for field, limit in TEXT_LIMITS.items():
        value = record.get(field)
        if _missing(value):
            continue
        if not isinstance(value, str):
            findings.append(_finding("invalid_type", field, f"{field} must be text"))
            continue
        if len(value) > limit:
            findings.append(_finding("invalid_range", field, f"{field} exceeds {limit} characters"))
        if is_placeholder_value(value):
            findings.append(_finding(
                "placeholder_value", field, f"Placeholder or non-informative value present in: {field}",
            ))
        if residual_pii(value):
            findings.append(_finding("pii", field, f"Residual PII patterns detected in: {field}"))
    for field, maximum in NUMERIC_LIMITS.items():
        value = record.get(field)
        if _missing(value):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            findings.append(_finding("invalid_type", field, f"{field} must be a number"))
            continue
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite or value < 0 or value > maximum:
            findings.append(_finding("invalid_range", field, f"{field} must be between 0 and {maximum}"))
        elif field in INTEGER_FIELDS and int(value) != value:
            findings.append(_finding("invalid_type", field, f"{field} must be a whole number"))
    category = record.get("category")
    if categories is None:
        categories = [item["name"] for item in settings.categories()]
    if isinstance(category, str) and category.strip() and category not in categories:
        findings.append(_finding("category", "category", "Category is not in configured category list"))
    return findings


def inspect_product_images(con, listing_id: str, platform: str, *, verify_images: bool = True) -> list[dict]:
    """Check every product asset and report errors using the existing approval messages."""
    images = con.execute(
        "SELECT * FROM images WHERE listing_id=? ORDER BY source_position,image_id", (listing_id,),
    ).fetchall()
    if not images:
        return [_finding("image", "images", "at least one product image is required for approval", "capture")]
    if not verify_images:
        return []
    findings = []
    allowed = (settings.data_dir / "images").resolve()
    expected_directory = (allowed / platform / listing_id).resolve()
    for item in images:
        label = item["image_id"]
        message = None
        try:
            path = (settings.root / item["storage_path"]).resolve()
            if (
                allowed not in expected_directory.parents or item["platform"] != platform
                or path.parent != expected_directory
            ):
                message = f"product image {label} is not stored under this listing's dataset directory"
            elif not path.is_file():
                message = f"product image {label} is missing from storage"
            elif path.stat().st_size > settings.max_image_bytes:
                message = f"product image {label} is unreadable or invalid: exceeds configured maximum size"
            else:
                data = path.read_bytes()
                _fmt, width, height, sha256, phash_int = validate_image_bytes(data)
                if len(data) != item["file_size_bytes"]:
                    message = f"product image {label} file size does not match its database metadata"
                elif sha256 != item["sha256"]:
                    message = f"product image {label} SHA-256 does not match its database metadata"
                elif width != item["width"] or height != item["height"]:
                    message = f"product image {label} dimensions do not match its database metadata"
                elif f"{phash_int:016x}" != item["perceptual_hash"]:
                    message = f"product image {label} perceptual hash does not match its database metadata"
        except (OSError, ValueError, TypeError) as exc:
            # Do not copy arbitrary paths or private data from OS exception messages.
            message = f"product image {label} is unreadable or invalid: {type(exc).__name__}"
        if message:
            finding = _finding("image", "images", message, "human")
            finding["asset_id"] = label
            findings.append(finding)
    return findings


def verify_product_images(con, listing_id: str, platform: str) -> None:
    findings = inspect_product_images(con, listing_id, platform)
    if findings:
        raise ValueError(findings[0]["message"])


def inspect_approved_duplicates(con, listing: dict) -> list[dict]:
    """Evaluate duplicate relationships again; approval may have changed since extraction."""
    listing = dict(listing)
    listing_id = listing["listing_id"]
    findings = []
    duplicate = con.execute(
        """SELECT listing_id FROM listings
           WHERE listing_id<>? AND status='approved'
             AND (source_url_hash=? OR
                  (marketplace_listing_id IS NOT NULL AND marketplace_listing_id<>''
                   AND platform=? AND marketplace_listing_id=?))
           ORDER BY listing_id LIMIT 1""",
        (listing_id, listing.get("source_url_hash"), listing["platform"], listing.get("marketplace_listing_id")),
    ).fetchone()
    if duplicate:
        findings.append(_finding(
            "duplicate_source", None, f"source duplicate of approved listing {duplicate['listing_id']}", "human",
        ))
    try:
        signature = metadata_signature(
            listing["platform"], listing.get("title"), listing.get("description"), listing.get("price"),
        )
    except (TypeError, ValueError, AttributeError, OverflowError):
        signature = None  # Field validation reports malformed legacy values separately.
    if signature is not None:
        duplicate = con.execute(
            """SELECT listing_id FROM listings WHERE listing_id<>? AND status='approved'
               AND metadata_signature=? ORDER BY listing_id LIMIT 1""", (listing_id, signature),
        ).fetchone()
        if duplicate:
            findings.append(_finding(
                "duplicate_metadata", None,
                f"metadata duplicate of approved listing {duplicate['listing_id']}", "human",
            ))
    duplicate = con.execute(
        """SELECT approved_images.listing_id FROM images current_images
           JOIN images approved_images ON approved_images.sha256=current_images.sha256
                AND approved_images.listing_id<>current_images.listing_id
           JOIN listings approved_listings ON approved_listings.listing_id=approved_images.listing_id
                AND approved_listings.status='approved'
           WHERE current_images.listing_id=? ORDER BY approved_images.listing_id LIMIT 1""",
        (listing_id,),
    ).fetchone()
    if duplicate:
        findings.append(_finding(
            "duplicate_image", "images",
            f"exact product image duplicate of approved listing {duplicate['listing_id']}", "human",
        ))
    return findings


def _available_screenshot(relative_path: str | None, expected_directory: Path) -> bool:
    if not relative_path:
        return False
    try:
        path = (settings.root / relative_path).resolve()
        allowed = (settings.data_dir / "private" / "screenshots").resolve()
        if (
            allowed not in path.parents or path.parent != expected_directory.resolve()
            or not path.is_file() or path.stat().st_size > settings.max_image_bytes
        ):
            return False
        validate_image_bytes(path.read_bytes())
        return True
    except (OSError, ValueError, TypeError):
        return False


def evidence_availability(listing: dict) -> dict:
    """Expose availability only, keeping raw private evidence out of findings."""
    listing = dict(listing)
    evidence = {"listing_text": False, "seller_text": False}
    staging_directory = (settings.data_dir / "private" / "staging").resolve()
    expected_staging = staging_directory / f"{listing['listing_id']}.json"
    try:
        staging_path = listing.get("staging_text_path")
        path = (settings.root / staging_path).resolve() if staging_path else None
        if (
            path is not None and path.parent == staging_directory
            and path == expected_staging.resolve() and path.is_file()
        ):
            staged = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(staged, dict):
                for key, source in (("listing_text", "visible_text"), ("seller_text", "seller_visible_text")):
                    evidence[key] = isinstance(staged.get(source), str) and bool(staged[source].strip())
    except (OSError, ValueError, TypeError):
        pass
    screenshot_directory = (
        settings.data_dir / "private" / "screenshots" / listing["platform"] / listing["listing_id"]
    )
    evidence["listing_screenshot"] = _available_screenshot(listing.get("screenshot_path"), screenshot_directory)
    evidence["seller_screenshot"] = _available_screenshot(listing.get("seller_screenshot_path"), screenshot_directory)
    return evidence


def inspect_listing(con, listing: dict, *, verify_images: bool = True) -> list[dict]:
    """Inspect current evidence and blockers without requiring a human review session.

    Historical field warnings are replaced by current checks. Other unresolved
    warnings remain human decisions, even if approval permits a human override.
    """
    listing = dict(listing)
    findings = validate_fields(listing)
    evidence = evidence_availability(listing)
    for finding in findings:
        seller_field = finding["field"] in SELLER_SIGNAL_FIELDS
        available = (
            evidence["seller_text"] or evidence["seller_screenshot"]
            if seller_field else evidence["listing_text"] or evidence["listing_screenshot"]
        )
        finding["evidence_available"] = dict(evidence)
        if finding["code"] == "missing_field" and not available:
            finding["action"] = "capture"
    findings.extend(inspect_product_images(con, listing["listing_id"], listing["platform"], verify_images=verify_images))
    findings.extend(inspect_approved_duplicates(con, listing))
    for warning in con.execute(
        "SELECT * FROM warnings WHERE listing_id=? AND resolved=0 ORDER BY created_at,warning_id",
        (listing["listing_id"],),
    ):
        if warning["warning_type"] in FIELD_WARNING_TYPES or warning["warning_type"] == "image":
            continue
        finding = _finding(
            warning["warning_type"], None,
            scrub_text(redact_secrets(warning["message"])).text[:2000], "human",
        )
        finding["warning_id"] = warning["warning_id"]
        findings.append(finding)
    return findings
