from __future__ import annotations
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol
from .models import ExtractedListing

EXTRACTION_SCHEMA = {
    "title": "string|null",
    "description": "string|null",
    "category": "string|null",
    "condition": "string|null",
    "price": "number|null",
    "currency": "string|null",
    "location_state": "string|null",
    "location_city": "string|null",
    "account_age_days": "integer|null",
    "seller_rating": "number|null",
    "review_count": "integer|null",
    "active_listing_count": "integer|null",
    "language": "string|null",
}

SYSTEM_RULES = """You extract marketplace listing fields from captured page text plus a screenshot.
The captured page text is the PRIMARY source of truth: title, description, category, condition,
price, currency, and location come from the listing page's text; account_age_days, seller_rating,
review_count, and active_listing_count come from the seller/profile page's text. The screenshot is
SECONDARY evidence only -- proof the page looked like this. Use it to catch a mismatch with the text,
never to invent a value the text does not support. If a field is not present in the text and cannot
be confidently confirmed from the screenshot, return null -- do not guess and do not fill in a
placeholder like "N/A" or "Unknown".
account_age_days is one field you must convert, not just copy: platforms state account age as
a relative duration ("11 years", "3 years 2 months", "8 months") rather than a day count. Convert
it using 1 year = 365 days and 1 month = 30 days (e.g. "11 years" -> 4015, "3 years 2 months" ->
1155). This is an approximation from a duration the page actually states, not a guess. If the text
instead gives an absolute join date (e.g. "Joined Since 21 May 2020") with no duration stated, use
the "Captured on" date given below as today's reference point and compute the day count between the
join date and the capture date. Only return null if the text gives neither a stated duration nor an
absolute date to anchor against the capture date.
active_listing_count is usually not printed as a number either. When the seller/profile page text
lists individual items under a Listings section, count the listing entries that are NOT marked SOLD
and return that count -- this is a count of what the captured text actually shows, not a guess. If
a Listings section header is present but no items follow it (it goes straight to the page footer),
that is a stated count of zero, not null. Only return null if no listings section is present in the
text at all.
review_count: if the seller/profile page text explicitly states "No review(s) yet" (or equivalent),
that is a stated count of zero, not an absence of data -- return 0, not null.
seller_rating: if the seller/profile page text explicitly states "No review(s) yet" alongside an
"N/A" rating, there are zero reviews to average, so by convention return 0.0 rather than null --
this keeps a stated "no rating exists" distinct from an unread page.
location_state: many Carousell listings give no self-pickup state, only a delivery option --
extract whatever location signal the deal method actually states rather than returning null:
- "Custom (West Malaysia)" / "Custom (East Malaysia)" -> use that region name as location_state.
- "Meet-up" followed by a venue name (e.g. "Meet-up Free Restoran Sahabat Tom Yam") -> use the
  venue name itself as location_state.
- "Doorstep delivery" via Carousell's own nationwide courier with no state given -> use "Nationwide"
  as location_state.
Only return null if the deal method text gives no location signal of any kind.
Do not infer hidden seller identity. Do not return seller username, seller name, email, phone, bank
details, contact handles, or exact street address.
Return only one JSON object and no markdown. No confidence fields are allowed. Categories should use
the configured GuardianLens category names when an obvious mapping exists."""

def build_extraction_prompt(
    platform: str,
    page_title: str | None,
    source_url: str | None,
    categories: list[str],
    visible_text: str | None = None,
    seller_visible_text: str | None = None,
    captured_at: str | None = None,
) -> str:
    """One prompt body shared by every provider so the text-primary/screenshot-secondary
    contract can't drift between them."""
    return "\n".join([
        f"Platform: {platform}",
        f"Page title: {page_title or ''}",
        f"Listing URL: {source_url or ''}",
        f"Captured on: {captured_at or 'unknown'}",
        f"Allowed categories: {', '.join(categories)}",
        f"Required JSON keys and types: {json.dumps(EXTRACTION_SCHEMA)}",
        "--- CAPTURED LISTING PAGE TEXT (primary source for title, description, category, "
        "condition, price, currency, location) ---",
        visible_text or "(no listing page text was captured; use the screenshot only for these fields)",
        "--- CAPTURED SELLER/PROFILE PAGE TEXT (primary source for account_age_days, "
        "seller_rating, review_count, active_listing_count) ---",
        seller_visible_text or "(the seller/profile page has not been captured; leave these fields null "
        "unless the screenshot unambiguously shows them)",
        "Return only one JSON object and no markdown fences.",
    ])

class Extractor(Protocol):
    provider: str
    model: str
    prompt_version: str
    def extract(
        self,
        screenshot_path: Path,
        platform: str,
        page_title: str | None,
        categories: list[str],
        source_url: str | None = None,
        visible_text: str | None = None,
        seller_visible_text: str | None = None,
        captured_at: str | None = None,
    ) -> dict: ...


class InvalidExtractionResponse(ValueError):
    """Provider output was not the normalized GuardianLens listing contract."""

_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)

def strip_code_fence(text: str) -> str:
    """Removes a ```json ... ``` (or bare ```) wrapper some providers add around the JSON body.

    str.strip("`") only trims characters that sit at the very edge of the string, so a trailing
    newline after the closing fence (very common in real provider output) leaves the fence intact
    and breaks json.loads. This matches the fence as a whole block instead.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text


def normalize_extracted_listing(value: Mapping[str, object]) -> dict:
    """Validate one provider mapping and materialize every contract key.

    Explicitly filling absent keys with ``None`` prevents Pydantic field defaults
    (notably currency) from turning an unobserved value into an apparent extraction.
    """
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise InvalidExtractionResponse("AI returned an invalid structured listing response")
    if any("confidence" in key.lower() for key in value):
        raise InvalidExtractionResponse("AI returned a forbidden confidence field")
    complete = {key: value.get(key) for key in EXTRACTION_SCHEMA}
    complete.update({key: item for key, item in value.items() if key not in EXTRACTION_SCHEMA})
    try:
        return ExtractedListing.model_validate(complete).model_dump()
    except Exception as exc:
        raise InvalidExtractionResponse("AI returned fields outside the listing contract") from exc


def parse_extracted_listing(text: str) -> dict:
    """Parse provider text without retaining raw malformed output in errors."""
    try:
        parsed = json.loads(strip_code_fence(text))
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidExtractionResponse("AI returned invalid listing JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidExtractionResponse("AI returned a non-object listing response")
    return normalize_extracted_listing(parsed)
