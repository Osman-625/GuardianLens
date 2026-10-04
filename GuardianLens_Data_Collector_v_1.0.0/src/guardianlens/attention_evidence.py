"""Conservative field proposals grounded in the listing's private capture.

Only hashes and logical evidence references leave this module. Screenshot-only
model output is left for human review because it cannot be corroborated here.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

from .config import settings
from .extraction_contract import EXTRACTION_SCHEMA
from .pii import is_placeholder_value, residual_pii

SELLER_FIELDS = {"account_age_days", "seller_rating", "review_count", "active_listing_count"}
NUMERIC_FIELDS = SELLER_FIELDS | {"price"}
INTEGER_FIELDS = {"account_age_days", "review_count", "active_listing_count"}
RULE_VERSION = "attention_evidence_v1"


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _owned_file(row: dict, field: str) -> Path | None:
    relative = row.get(field)
    if not relative:
        return None
    path = (settings.root / relative).resolve()
    if field == "staging_text_path":
        expected = (settings.data_dir / "private" / "staging" / f"{row['listing_id']}.json").resolve()
        return path if path == expected else None
    expected_directory = (
        settings.data_dir / "private" / "screenshots" / row["platform"] / row["listing_id"]
    ).resolve()
    return path if path.parent == expected_directory else None


def load_evidence(row: dict) -> dict:
    """Load bounded, owned capture files; absent/malformed evidence is never invented."""
    evidence: dict = {"listing_text": "", "seller_text": "", "assets": {}, "problems": []}
    for field in ("staging_text_path", "screenshot_path", "seller_screenshot_path"):
        path = _owned_file(row, field)
        if path is None or not path.is_file():
            evidence["assets"][field] = "missing"
            continue
        try:
            limit = 5 * 1024 * 1024 if field == "staging_text_path" else 25 * 1024 * 1024
            if path.stat().st_size > limit:
                raise ValueError("capture exceeds safe read limit")
            data = path.read_bytes()
            evidence["assets"][field] = _digest(data)
            if field == "staging_text_path":
                staging = json.loads(data.decode("utf-8"))
                if not isinstance(staging, dict):
                    raise ValueError("staging must be an object")
                for source, target in (("visible_text", "listing_text"), ("seller_visible_text", "seller_text")):
                    value = staging.get(source) or ""
                    if not isinstance(value, str):
                        raise ValueError("staging text must be a string")
                    evidence[target] = value
                evidence["seller_captured_at"] = staging.get("seller_captured_at")
            else:
                evidence[field] = path
        except (OSError, ValueError, UnicodeError):
            evidence["problems"].append(field)
            evidence["assets"][field] = "invalid"
    return evidence


def input_fingerprint(con, row: dict, evidence: dict | None = None) -> str:
    evidence = evidence if evidence is not None else load_evidence(row)
    listing_id = row["listing_id"]
    payload = {
        "rules": RULE_VERSION,
        "listing": row,
        "assets": evidence["assets"],
        "categories": [item["name"] for item in settings.categories()],
        "warnings": [dict(item) for item in con.execute(
            "SELECT * FROM warnings WHERE listing_id=? ORDER BY warning_id", (listing_id,)
        )],
        "reviews": [dict(item) for item in con.execute(
            "SELECT * FROM review_actions WHERE listing_id=? ORDER BY review_action_id", (listing_id,)
        )],
        "images": [dict(item) for item in con.execute(
            "SELECT * FROM images WHERE listing_id=? ORDER BY image_id", (listing_id,)
        )],
    }
    # Replaced or deleted product evidence should invalidate a no-progress result,
    # even if the recorded image metadata has not changed.
    for item in payload["images"]:
        path = (settings.root / item["storage_path"]).resolve()
        expected = (settings.data_dir / "images" / row["platform"] / listing_id).resolve()
        try:
            stat = path.stat() if path.parent == expected else None
            item["file_revision"] = (stat.st_size, stat.st_mtime_ns) if stat else None
        except OSError:
            item["file_revision"] = None
    return _digest(json.dumps(payload, sort_keys=True, default=str).encode("utf-8"))


def protected_fields(con, listing_id: str) -> set[str]:
    protected: set[str] = set()
    for item in con.execute(
        "SELECT updated_data FROM review_actions WHERE listing_id=? AND action='edit'", (listing_id,)
    ):
        try:
            updated = json.loads(item["updated_data"] or "{}")
        except (ValueError, TypeError):
            # An unreadable human audit cannot safely be overwritten.
            return set(EXTRACTION_SCHEMA)
        if isinstance(updated, dict):
            protected.update(set(updated) & set(EXTRACTION_SCHEMA))
    return protected


def _normalized(value: object) -> str:
    return " ".join(str(value).split()).casefold()


def _one_match(patterns: list[str], text: str, integer: bool = False) -> float | int | None:
    values: set[float] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I | re.M):
            try:
                value = float(match.group(1).replace(",", ""))
            except ValueError:
                continue
            if math.isfinite(value) and value >= 0 and (not integer or value.is_integer()):
                values.add(value)
    if len(values) != 1:
        return None
    value = values.pop()
    return int(value) if integer else value


_AGE_PART = r"(?:(\d+)\s*y(?:ears?)?)?\s*(?:(\d+)\s*mo?(?:nths?)?)?\s*(?:(\d+)\s*d(?:ays?)?)?"


def _account_age(text: str, captured_at: str | None) -> int | None:
    """Captured page text has no line breaks, so this cannot rely on ^/$ anchors, and
    platforms show either "3y 5m Joined"/"9y 8m Joined ago" (abbreviated, suffix cue) or
    "Member for 3 years" (full words, prefix cue) -- both must be matched inline."""
    values: set[int] = set()
    for pattern in (
        rf"{_AGE_PART}\s*(?:joined|member\s*(?:for|since)|on\s*carousell|on\s*mudah|ago)\b",
        rf"(?:account age\s*[:\-]?\s*|member\s*(?:for|since)\s*|joined\s*[:\-]?\s*){_AGE_PART}",
    ):
        for match in re.finditer(pattern, text, re.I):
            if any(part is not None for part in match.groups()):
                years, months, days = (int(part or 0) for part in match.groups())
                if years or months or days:
                    values.add(years * 365 + months * 30 + days)
    if captured_at:
        try:
            captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00")).date()
        except ValueError:
            captured = None
        if captured:
            for match in re.finditer(
                r"(?:joined(?:\s+since)?|member since)\s*[:\-]?\s*"
                r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})", text, re.I,
            ):
                for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d"):
                    try:
                        joined = datetime.strptime(match.group(1), fmt).date()
                    except ValueError:
                        continue
                    if joined <= captured:
                        values.add((captured - joined).days)
                    break
    return values.pop() if len(values) == 1 else None


def deterministic_proposals(row: dict, evidence: dict, fields: set[str]) -> dict[str, dict]:
    categories = {name.casefold(): name for name in (item["name"] for item in settings.categories())}
    listing_text, seller_text = evidence["listing_text"], evidence["seller_text"]
    proposals: dict[str, dict] = {}
    number = r"(\d[\d,]*(?:\.\d+)?)"
    numeric_patterns = {
        "price": [rf"(?:price\s*[:\-]?\s*(?:RM|MYR)?\s*|\b(?:RM|MYR)\s*){number}"],
        "seller_rating": [rf"(?:seller\s+)?rating\s*[:\-]?\s*{number}", rf"{number}\s*(?:/\s*5|stars?\b)"],
        "review_count": [rf"(?:reviews?|ratings?)\s*[:\-]\s*{number}", rf"{number}\s*(?:reviews?|ratings?)\b"],
        "active_listing_count": [rf"(?:active\s+)?listings?\s*[:\-]\s*{number}", rf"{number}\s*(?:active\s+)?listings?\b"],
    }
    for field in fields:
        value = None
        reference = "seller_text" if field in SELLER_FIELDS else "listing_text"
        source = seller_text if field in SELLER_FIELDS else listing_text
        explanation = "Unique explicitly labelled value in captured text"
        if field == "account_age_days":
            value = _account_age(source, evidence.get("seller_captured_at") or row.get("captured_at"))
            explanation = "Captured membership duration (365 days/year, 30 days/month) or join date relative to capture date"
        elif field == "review_count" and re.search(r"\bno\s+reviews?\s+yet\b", source, re.I):
            value = 0
            explanation = "Captured seller profile explicitly states no reviews yet"
        elif field == "seller_rating" and re.search(r"\bno\s+reviews?\s+yet\b", source, re.I):
            value = 0.0
            explanation = "No reviews exist yet to average into a rating; recorded as 0.0 by convention"
        elif field == "active_listing_count" and re.search(r"Listings\s+Filters\s+Follow us", source, re.I):
            value = 0
            explanation = "The Listings section is present but immediately empty -- zero active items shown"
        elif field == "location_state" and (match := re.search(r"\bCustom\s*\((West Malaysia|East Malaysia)\)", source, re.I)):
            value = match.group(1).title()
            reference = "listing_text"
            explanation = "Listing's delivery/shipping option states a custom shipping region"
        elif field == "location_state" and (match := re.search(
            r"Meet-?up\s+(?:Free|RM\s*[\d,]+(?:\.\d+)?)\s+(.+?)\s+(?:FAQ\s+)?Meet the seller", source, re.I,
        )):
            value = " ".join(match.group(1).split())
            reference = "listing_text"
            explanation = "Listing's deal method states a meet-up venue used as the location"
        elif field == "location_state" and re.search(r"Doorstep delivery\s+Carousell Official Delivery", source, re.I):
            value = "Nationwide"
            reference = "listing_text"
            explanation = "Listing ships via nationwide courier delivery with no specific state given"
        elif field in numeric_patterns:
            value = _one_match(numeric_patterns[field], source, field in INTEGER_FIELDS)
        elif field == "category":
            candidates = [row.get("category"), row.get("source_category")]
            values = {categories[_normalized(item)] for item in candidates if item and _normalized(item) in categories}
            if len(values) == 1:
                value = values.pop()
                reference = "captured_category"
                explanation = "Exact case-insensitive configured category mapping"
        elif field == "currency":
            if re.search(r"\b(?:RM|MYR)\s*\d", source, re.I):
                value = "MYR"
        else:
            label = field.replace("_", r"[ _]")
            matches = {_normalized(m.group(1)): m.group(1).strip() for m in re.finditer(
                rf"^{label}\s*:\s*([^\r\n]+)$", source, re.I | re.M,
            )}
            if len(matches) == 1:
                value = next(iter(matches.values()))
        if value is None or is_placeholder_value(value) or residual_pii(str(value)):
            continue
        proposals[field] = {
            "value": value,
            "evidence": {
                "reference": reference,
                "sha256": evidence["assets"].get("staging_text_path") if reference != "captured_category" else None,
                "explanation": explanation,
                "captured_at": evidence.get("seller_captured_at") or row.get("captured_at") if field in SELLER_FIELDS else row.get("captured_at"),
            },
            "provider": "deterministic", "model": "rules", "prompt_version": RULE_VERSION,
        }
    return proposals


def corroborated_ai_proposals(
    row: dict, evidence: dict, fields: set[str], extracted: dict, identity: tuple[str, str, str],
) -> dict[str, dict]:
    """Accept only text-supported missing/invalid values, never model inference alone."""
    proposals: dict[str, dict] = {}
    deterministic = deterministic_proposals(row, evidence, fields)
    for field in fields:
        value = extracted.get(field)
        if value is None or is_placeholder_value(value) or residual_pii(str(value)):
            continue
        reference = "seller_text" if field in SELLER_FIELDS else "listing_text"
        text = evidence[reference]
        if field in NUMERIC_FIELDS or field == "currency":
            if field not in deterministic or deterministic[field]["value"] != value:
                continue
        elif not text or _normalized(value) not in _normalized(text):
            continue
        proposals[field] = {
            "value": value,
            "evidence": {
                "reference": reference,
                "sha256": evidence["assets"].get("staging_text_path"),
                "explanation": "Provider proposal corroborated by captured text",
                "captured_at": evidence.get("seller_captured_at") or row.get("captured_at") if field in SELLER_FIELDS else row.get("captured_at"),
            },
            "provider": identity[0], "model": identity[1], "prompt_version": identity[2],
        }
    return proposals
