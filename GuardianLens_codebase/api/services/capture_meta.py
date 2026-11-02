"""Validation of the `source` and `capture_meta` form fields of POST /api/v1/assess.

Kept separate from the router so the rules are in one place and easy to test. Both functions
raise AppError (a 422 with a field name) so the buyer-facing error envelope stays consistent.
"""

from __future__ import annotations

from api.errors import AppError
from api.schemas import CaptureMeta

# Where a submission can come from: the browser extension, or the website's manual form.
VALID_SOURCES = frozenset({"extension", "manual"})

# Upper bound on the raw JSON string, checked before parsing so a huge body is never parsed.
MAX_CAPTURE_META_CHARS = 2000


def parse_source(value: str) -> str:
    """Returns the normalised source, or raises a 422 on the `source` field."""
    cleaned = value.strip().lower()
    if cleaned not in VALID_SOURCES:
        raise AppError(422, "invalid_source", "Source must be extension or manual.", "source")
    return cleaned


def parse_capture_meta(raw: str | None, source: str) -> dict[str, object] | None:
    """Validates the `capture_meta` JSON string and returns it as a plain dict.

    Returns None when no metadata was sent. Raises a 422 on the `capture_meta` field when the
    metadata comes from a non-extension source, is too large, is not JSON, or does not match
    the CaptureMeta model (unknown keys, a host that is not one of the four platform hosts,
    or a field status outside captured / edited / not_found).
    """
    if raw is None or raw == "":
        return None
    if source != "extension":
        raise AppError(
            422,
            "invalid_capture_meta",
            "Capture details are only accepted from the extension.",
            "capture_meta",
        )
    if len(raw) > MAX_CAPTURE_META_CHARS:
        raise AppError(
            422, "invalid_capture_meta", "Capture details are too large.", "capture_meta"
        )
    try:
        meta = CaptureMeta.model_validate_json(raw)
    except ValueError as exc:  # pydantic's ValidationError is a ValueError
        raise AppError(
            422,
            "invalid_capture_meta",
            "Capture details were not in the expected format.",
            "capture_meta",
        ) from exc
    return meta.model_dump(mode="json")
