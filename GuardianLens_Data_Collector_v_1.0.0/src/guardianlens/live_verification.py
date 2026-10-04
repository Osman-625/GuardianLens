"""Verify approved listings against their live marketplace pages.

Two-tier verification, and this module never mutates listing data:

- Tier 1 (free, deterministic): fetch the live page directly (no OpenAI involved --
  OpenAI's own web_search tool is blocked by Carousell's bot protection, confirmed by
  hand: 403 on 5/5 tested URLs), parse platform-specific structured data already
  embedded in the page (Carousell's `application/ld+json` Product block, Mudah's
  `__NEXT_DATA__` ad attributes), and compare directly against the stored fields.
- Tier 2 (OpenAI, suspects only): triggered only when tier 1 disagrees or a field
  can't be parsed. Sends the stored fields, the parsed live fields, and a short live
  text excerpt to OpenAI's Responses API for a JSON verdict.

Results are written to `live_verification_runs`/`live_verification_items` and a JSON
report; nothing here ever changes a listing's `status` or any other column.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from .config import settings, provider_client_options
from .db import now_iso
from .errors import ProviderConfigurationError, ProviderOperationError, classify_error
from .extraction_contract import strip_code_fence
from .images import MAX_REDIRECTS, REDIRECT_STATUSES, _validate_connected_peer, _validate_remote_url

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MAX_PAGE_BYTES = 3_000_000
DEFAULT_RATE_DELAY_SECONDS = 1.5
TEXT_EXCERPT_MAX_CHARS = 2000

OUTCOME_MATCH = "match"
OUTCOME_MISMATCH = "mismatch"
OUTCOME_SOLD_OR_REMOVED = "sold_or_removed"
OUTCOME_BLOCKED = "blocked"
OUTCOME_FETCH_FAILED = "fetch_failed"

TIER_DETERMINISTIC = "deterministic"
TIER_OPENAI = "openai"


# --------------------------------------------------------------------------- fetching

@dataclass
class FetchResult:
    status_code: int
    final_url: str
    html: str | None
    blocked: bool = False
    error: str | None = None


def fetch_listing_page(url: str) -> FetchResult:
    """GET a listing page directly, following redirects manually with the same
    SSRF/DNS-rebinding guards as images.download_image.

    A browser User-Agent is required -- confirmed by hand that Carousell returns 403
    to a default/no User-Agent, but 200 (or 410, with a full body) to a normal browser
    UA from this machine. OpenAI's own fetcher is blocked regardless of UA; this is a
    direct local fetch, not routed through any AI provider.
    """
    current = url
    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        with httpx.Client(
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers=headers,
        ) as client:
            for redirect_count in range(MAX_REDIRECTS + 1):
                try:
                    approved_addresses = _validate_remote_url(current)
                except ValueError as exc:
                    return FetchResult(0, current, None, error=str(exc))
                with client.stream("GET", current) as response:
                    _validate_connected_peer(response, current, approved_addresses)
                    if response.status_code in REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location or redirect_count >= MAX_REDIRECTS:
                            return FetchResult(
                                response.status_code, current, None,
                                error="invalid or too-long redirect chain",
                            )
                        current = urljoin(current, location)
                        continue
                    if response.status_code in (403, 429):
                        return FetchResult(response.status_code, current, None, blocked=True)
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > MAX_PAGE_BYTES:
                            break
                    html = chunks.decode("utf-8", errors="replace")
                    return FetchResult(response.status_code, current, html)
    except httpx.HTTPError as exc:
        return FetchResult(0, current, None, error=str(exc))
    return FetchResult(0, current, None, error="redirect chain did not produce a page")


# --------------------------------------------------------------------------- parsing

@dataclass
class LivePage:
    title: str | None = None
    description: str | None = None
    price: float | None = None
    currency: str | None = None
    condition: str | None = None  # normalized to "new" / "used" / None
    availability: str | None = None  # "in_stock" / "sold" / None
    location_state: str | None = None
    text_excerpt: str = ""


_LD_JSON_RE = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_OG_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]*)"', re.S)
_MUDAH_AD_ID_RE = re.compile(r'-(\d+)\.htm')
_PRICE_NUMBER_RE = re.compile(r'[\d,]+(?:\.\d+)?')


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def parse_carousell(html: str) -> LivePage | None:
    """Parse Carousell's `application/ld+json` Product block.

    Confirmed by hand: Carousell serves this JSON-LD (with `offers.availability`
    reflecting InStock/SoldOut) even on a page returned with HTTP 410 Gone -- so the
    caller should attempt to parse regardless of status code before treating a
    non-200 response as unparseable.
    """
    for blob in _LD_JSON_RE.findall(html):
        try:
            data = json.loads(blob.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict) or data.get("@type") != "Product":
            continue
        offers = data.get("offers") or {}
        availability_raw = str(offers.get("availability") or "")
        condition_raw = str(offers.get("itemCondition") or "")
        availability = (
            "sold" if "SoldOut" in availability_raw
            else "in_stock" if "InStock" in availability_raw
            else None
        )
        condition = (
            "new" if "NewCondition" in condition_raw
            else "used" if "UsedCondition" in condition_raw
            else None
        )
        name = data.get("name") or ""
        description = data.get("description") or ""
        return LivePage(
            title=name or None,
            description=description or None,
            price=_to_float(offers.get("price")),
            currency=offers.get("priceCurrency"),
            condition=condition,
            availability=availability,
            location_state=None,
            text_excerpt=f"{name} {description}".strip()[:TEXT_EXCERPT_MAX_CHARS],
        )
    return None


def _mudah_ad_id_from_url(url: str) -> str | None:
    m = _MUDAH_AD_ID_RE.search(url)
    return m.group(1) if m else None


def _parse_mudah_price(text: str) -> tuple[float | None, str | None]:
    if not text:
        return None, None
    m = _PRICE_NUMBER_RE.search(text)
    price = _to_float(m.group(0)) if m else None
    currency = "MYR" if "RM" in text.upper() else None
    return price, currency


def _location_state_from_og_title(og_title: str | None) -> str | None:
    if not og_title or "," not in og_title:
        return None
    return og_title.rsplit(",", 1)[-1].strip() or None


def parse_mudah(html: str, source_url: str) -> LivePage | None:
    """Parse Mudah's `__NEXT_DATA__` ad-detail block, keyed by the ad id in the URL.

    If the ad id from `source_url` has no matching entry under
    `adDetails.byID`, the fetch landed somewhere other than the real ad page (Mudah
    redirects an expired/removed ad to a category browse page) -- the caller should
    treat that as removed, not as an unparseable page.
    """
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, TypeError):
        return None
    ad_id = _mudah_ad_id_from_url(source_url)
    by_id = (
        data.get("props", {}).get("initialState", {}).get("adDetails", {}).get("byID", {})
    )
    attrs = (by_id.get(ad_id) or {}).get("attributes") if ad_id else None
    if not attrs:
        return None
    price, currency = _parse_mudah_price(attrs.get("price") or "")
    subject = attrs.get("subject") or ""
    body = attrs.get("body") or ""
    og_title = _OG_TITLE_RE.search(html)
    return LivePage(
        title=subject or None,
        description=body or None,
        price=price,
        currency=currency,
        condition=None,
        availability="in_stock",
        location_state=_location_state_from_og_title(og_title.group(1) if og_title else None),
        text_excerpt=f"{subject} {body}".strip()[:TEXT_EXCERPT_MAX_CHARS],
    )


def parse_live_page(platform: str, html: str, source_url: str) -> LivePage | None:
    if platform == "carousell":
        return parse_carousell(html)
    if platform == "mudah":
        return parse_mudah(html, source_url)
    return None


def page_looks_removed(platform: str, fetch: FetchResult, live: LivePage | None) -> bool:
    """True when the fetch landed on a dead/redirected page rather than the real listing."""
    if platform == "carousell":
        return live is not None and live.availability == "sold"
    if platform == "mudah":
        # A successful fetch that could not resolve the ad id under __NEXT_DATA__ means
        # the final URL is not the ad page any more (Mudah redirects to a category page).
        return fetch.status_code == 200 and live is None
    return False


# --------------------------------------------------------------------------- tier 1

@dataclass
class Comparison:
    outcome: str
    verdict: str | None
    fields_in_disagreement: list[str] = field(default_factory=list)
    details: str = ""
    tier: str = TIER_DETERMINISTIC
    live: LivePage | None = None


_PRICE_TOLERANCE = 0.01


_BRAND_NEW_PHRASES = ("brand new", "brand-new", "factory new", "factory sealed", "unopened", "sealed")


def _condition_bucket(text: str | None) -> str | None:
    """Bucket a free-text condition into schema.org's binary new/used distinction.

    Carousell's own JSON-LD only distinguishes NewCondition from UsedCondition -- there
    is no "like new" tier in schema.org, so Carousell reports UsedCondition for a
    "Like New" listing too. A naive substring check for "new" would misclassify "Like
    New" as bucket "new" and produce a false-positive mismatch against every
    UsedCondition live page; only an unqualified "new" claim counts as bucket "new".
    """
    if not text:
        return None
    lowered = text.lower().strip()
    if lowered == "new" or any(phrase in lowered for phrase in _BRAND_NEW_PHRASES):
        return "new"
    if "new" in lowered:
        # "like new", "almost new", "near new" etc. -- still a used item in this binary sense.
        return "used"
    if any(word in lowered for word in ("used", "pre-owned", "preowned", "second hand", "secondhand", "refurbished")):
        return "used"
    return None


def compare_deterministic(row: dict, live: LivePage) -> Comparison:
    disagreements: list[str] = []

    if live.price is not None and row.get("price") is not None:
        if abs(float(row["price"]) - live.price) > _PRICE_TOLERANCE:
            disagreements.append("price")
    if live.currency and row.get("currency") and live.currency != row["currency"]:
        disagreements.append("currency")

    stored_condition = _condition_bucket(row.get("condition"))
    if live.condition and stored_condition and live.condition != stored_condition:
        disagreements.append("condition")

    if live.location_state and row.get("location_state"):
        if live.location_state.strip().lower() != str(row["location_state"]).strip().lower():
            disagreements.append("location_state")

    if disagreements:
        return Comparison(
            outcome=OUTCOME_MISMATCH,
            verdict=None,  # resolved by tier 2
            fields_in_disagreement=disagreements,
            details="deterministic check found disagreement in: " + ", ".join(disagreements),
            live=live,
        )
    return Comparison(
        outcome=OUTCOME_MATCH,
        verdict="MATCH",
        details="stored price/currency/condition/location agree with the live page",
        live=live,
    )


# --------------------------------------------------------------------------- tier 2

_VERDICT_KEYS = {"verdict", "fields_in_disagreement", "details"}


class LiveVerificationError(RuntimeError):
    """Tier-2 OpenAI adjudication failed after all retries."""


def _build_adjudication_prompt(row: dict, live: LivePage, fetch: FetchResult) -> str:
    stored = {
        "title": row.get("title"),
        "price": row.get("price"),
        "currency": row.get("currency"),
        "condition": row.get("condition"),
        "category": row.get("category"),
        "location_state": row.get("location_state"),
    }
    parsed_live = {
        "title": live.title,
        "price": live.price,
        "currency": live.currency,
        "condition": live.condition,
        "location_state": live.location_state,
        "availability": live.availability,
    }
    return f"""You are auditing a marketplace data-collection dataset for a research project.
Platform: {row.get("platform")}. Listing URL: {row.get("source_url")}

STORED (captured earlier): {json.dumps(stored, ensure_ascii=False)}
PARSED FROM THE LIVE PAGE JUST NOW: {json.dumps(parsed_live, ensure_ascii=False)}
LIVE PAGE TEXT EXCERPT: {live.text_excerpt[:TEXT_EXCERPT_MAX_CHARS]!r}
Final fetched URL (after redirects): {fetch.final_url}
HTTP status of the fetch: {fetch.status_code}

Decide whether STORED still accurately describes the live listing. Ignore wording,
casing, emoji, and formatting differences -- only real disagreements matter (wrong
price, wrong condition, wrong location/state, or the live page is clearly a different
product than what was stored, e.g. the seller edited the ad into something else).

Respond with ONLY a raw JSON object (no markdown fences, no extra text) with exactly
these keys:
{{"verdict": "MATCH" | "MISMATCH", "fields_in_disagreement": [<field names>], "details": "<short explanation, empty string if MATCH>"}}
"""


def _parse_adjudication(text: str) -> dict:
    try:
        parsed = json.loads(strip_code_fence(text))
    except (json.JSONDecodeError, TypeError) as exc:
        raise LiveVerificationError("OpenAI returned invalid adjudication JSON") from exc
    if not isinstance(parsed, dict) or "verdict" not in parsed:
        raise LiveVerificationError("OpenAI returned a malformed adjudication response")
    parsed.setdefault("fields_in_disagreement", [])
    parsed.setdefault("details", "")
    return parsed


def build_openai_client():
    if not settings.openai_api_key:
        raise ProviderConfigurationError("OPENAI_API_KEY is missing")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ProviderConfigurationError("OpenAI SDK is not installed") from exc
    return OpenAI(api_key=settings.openai_api_key, **provider_client_options())


def adjudicate_with_openai(client, row: dict, live: LivePage, fetch: FetchResult) -> Comparison:
    """Call OpenAI (Responses API, no web_search -- the page was already fetched
    locally) to judge a tier-1 disagreement. Retries transient failures the same way
    processor._extract_with_retries does; a quota error is non-retryable and propagates
    so the caller can halt the run cleanly."""
    prompt = _build_adjudication_prompt(row, live, fetch)
    last_exc: Exception | None = None
    for attempt in range(1, settings.ai_max_attempts + 1):
        try:
            response = client.responses.create(model=settings.openai_model, input=prompt)
            verdict = _parse_adjudication(response.output_text)
            outcome = OUTCOME_MISMATCH if verdict["verdict"] == "MISMATCH" else OUTCOME_MATCH
            return Comparison(
                outcome=outcome,
                verdict=verdict["verdict"],
                fields_in_disagreement=list(verdict.get("fields_in_disagreement") or []),
                details=str(verdict.get("details") or ""),
                tier=TIER_OPENAI,
                live=live,
            )
        except Exception as exc:  # noqa: BLE001 - normalized by classify_error below
            last_exc = exc
            classification = classify_error(exc)
            if classification.retryable and attempt < settings.ai_max_attempts:
                time.sleep(min(settings.ai_retry_max_seconds, settings.ai_retry_base_seconds * (2 ** (attempt - 1))))
                continue
            raise ProviderOperationError(classification) from exc
    raise LiveVerificationError(f"OpenAI adjudication failed: {last_exc}")  # pragma: no cover


# --------------------------------------------------------------------------- orchestration

def verify_listing(row: dict, client=None) -> Comparison:
    """Verify one listing row against its live page. Never mutates `row` or the DB --
    the caller is responsible for persisting the returned Comparison."""
    fetch = fetch_listing_page(row["source_url"])
    if fetch.blocked:
        return Comparison(
            outcome=OUTCOME_BLOCKED,
            verdict=None,
            details=f"blocked by the platform (HTTP {fetch.status_code})",
        )
    if fetch.html is None:
        return Comparison(outcome=OUTCOME_FETCH_FAILED, verdict=None, details=fetch.error or "fetch failed")

    live = parse_live_page(row["platform"], fetch.html, fetch.final_url)

    if page_looks_removed(row["platform"], fetch, live):
        return Comparison(
            outcome=OUTCOME_SOLD_OR_REMOVED,
            verdict=None,
            details="listing is sold, expired, or removed since capture",
            live=live,
        )
    if live is None:
        return Comparison(
            outcome=OUTCOME_FETCH_FAILED, verdict=None,
            details=f"could not parse structured data from the live page (HTTP {fetch.status_code})",
        )

    result = compare_deterministic(row, live)
    if result.outcome == OUTCOME_MATCH:
        return result

    # Tier 1 disagreed -- escalate to OpenAI for adjudication.
    client = client or build_openai_client()
    return adjudicate_with_openai(client, row, live, fetch)


# --------------------------------------------------------------------------- persistence

def create_run(con, *, selection: str, item_limit: int | None, api_call_limit: int | None,
                rate_delay_seconds: float) -> str:
    run_id = str(uuid.uuid4())
    timestamp = now_iso()
    con.execute(
        "INSERT INTO live_verification_runs("
        "run_id,status,selection,item_limit,api_call_limit,api_calls,rate_delay_seconds,"
        "message,created_at,started_at,updated_at) VALUES(?,?,?,?,?,0,?,?,?,?,?)",
        (run_id, "running", selection, item_limit, api_call_limit, rate_delay_seconds,
         None, timestamp, timestamp, timestamp),
    )
    return run_id


def record_item(con, *, run_id: str, listing_id: str, comparison: Comparison, api_called: bool) -> None:
    item_id = str(uuid.uuid4())
    timestamp = now_iso()
    con.execute(
        "INSERT INTO live_verification_items("
        "item_id,run_id,listing_id,outcome,verdict,fields_in_disagreement,details,tier,"
        "api_called,attempt_count,checked_at,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?) "
        "ON CONFLICT(run_id,listing_id) DO UPDATE SET "
        "outcome=excluded.outcome,verdict=excluded.verdict,"
        "fields_in_disagreement=excluded.fields_in_disagreement,details=excluded.details,"
        "tier=excluded.tier,api_called=excluded.api_called,"
        "attempt_count=live_verification_items.attempt_count+1,checked_at=excluded.checked_at,"
        "updated_at=excluded.updated_at",
        (item_id, run_id, listing_id, comparison.outcome, comparison.verdict,
         json.dumps(comparison.fields_in_disagreement), comparison.details, comparison.tier,
         1 if api_called else 0, timestamp, timestamp, timestamp),
    )


def finish_run(con, run_id: str, *, status: str, api_calls: int, message: str | None = None) -> None:
    con.execute(
        "UPDATE live_verification_runs SET status=?,api_calls=?,message=?,finished_at=?,updated_at=? "
        "WHERE run_id=?",
        (status, api_calls, message, now_iso(), now_iso(), run_id),
    )


def last_checked_at(con, listing_id: str) -> str | None:
    row = con.execute(
        "SELECT MAX(checked_at) AS checked_at FROM live_verification_items "
        "WHERE listing_id=? AND checked_at IS NOT NULL",
        (listing_id,),
    ).fetchone()
    return row["checked_at"] if row else None
