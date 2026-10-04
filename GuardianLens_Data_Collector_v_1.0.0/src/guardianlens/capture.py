from __future__ import annotations
import json
import re
import uuid
from typing import NoReturn
from urllib.parse import unquote, urlsplit, urlunsplit
from .config import settings
from .db import connect, transaction, now_iso
from .dedupe import canonicalize_url, url_hash
from .images import save_private_screenshot
from .pii import scrub_text
from .collection_handoff import refresh_annotation_dataset_safely

ALLOWED_HOSTS = {
    "carousell": ("carousell.com.my", "www.carousell.com.my"),
    "mudah": ("mudah.my", "www.mudah.my"),
}
LISTING_PATHS = {
    "carousell": re.compile(r"^/p/(?P<slug>[^/]+)-(?P<listing_id>[1-9]\d*)/?$", re.IGNORECASE),
    "mudah": re.compile(r"^/(?P<slug>[^/]+)-(?P<listing_id>[1-9]\d*)\.htm$", re.IGNORECASE),
}
INVALID_LISTING_MESSAGE = "Capture rejected: This does not appear to be an individual listing page."
GENERIC_HEADINGS = {
    "browse", "carousell", "categories", "category", "home", "login", "mudah",
    "profile", "search", "search results", "sign in", "sign up",
}

def _reject_invalid_listing() -> NoReturn:
    raise ValueError(INVALID_LISTING_MESSAGE)

def _listing_id_from_url(platform: str, url: str) -> str:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError):
        _reject_invalid_listing()
    if (
        parsed.scheme.lower() != "https"
        or host not in ALLOWED_HOSTS[platform]
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        _reject_invalid_listing()
    path = unquote(parsed.path)
    if "\\" in path or any(ord(ch) < 32 for ch in path):
        _reject_invalid_listing()
    match = LISTING_PATHS[platform].fullmatch(path)
    if not match or not match.group("slug").strip(" .-_"):
        _reject_invalid_listing()
    return match.group("listing_id")

def _has_meaningful_heading(value: str | None) -> bool:
    heading = " ".join((value or "").split()).strip()
    return (
        3 <= len(heading) <= 500
        and heading.casefold() not in GENERIC_HEADINGS
        and any(ch.isalnum() for ch in heading)
    )

def _has_https_image_candidate(urls: list[str]) -> bool:
    for url in urls:
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme.lower() == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
            ):
                return True
        except (TypeError, ValueError):
            continue
    return False

def validate_listing_capture(payload) -> str:
    marketplace_listing_id = _listing_id_from_url(payload.platform, payload.source_url)
    supplied_id = (payload.marketplace_listing_id or "").strip()
    if supplied_id and supplied_id != marketplace_listing_id:
        _reject_invalid_listing()
    evidence = payload.listing_evidence
    has_listing_signal = (
        evidence.has_price_signal
        or evidence.has_product_structured_data
        or evidence.has_offer_signal
    )
    if (
        not _has_meaningful_heading(evidence.h1_text)
        or not has_listing_signal
        or not _has_https_image_candidate(payload.image_urls)
    ):
        _reject_invalid_listing()
    return marketplace_listing_id


def _capture_provenance(payload, marketplace_listing_id: str) -> dict:
    """Resolve CSV provenance server-side so the extension cannot invent batch metadata."""
    if payload.capture_source == "extension":
        if payload.batch_item_id:
            raise ValueError("manual extension capture cannot include a batch item")
        return {
            "capture_source": "extension",
            "capture_batch_id": None,
            "csv_row": None,
            "original_csv_filename": None,
            "source_category": None,
        }
    if not payload.batch_item_id:
        raise ValueError("CSV batch capture requires a batch item ID")
    c = connect()
    try:
        item = c.execute(
            """SELECT item.*,batch.original_filename,batch.source_type
               FROM capture_batch_items item
               JOIN capture_batches batch ON batch.batch_id=item.batch_id
               WHERE item.batch_item_id=?""",
            (payload.batch_item_id,),
        ).fetchone()
    finally:
        c.close()
    if not item or item["source_type"] not in {"csv", "manual"}:
        raise ValueError("CSV batch item was not found")
    if item["status"] not in {"opening", "capturing"}:
        raise ValueError(f"CSV batch item cannot capture from {item['status']}")
    if item["platform"] != payload.platform:
        raise ValueError("captured page platform does not match the queued URL")
    try:
        queued_listing_id = _listing_id_from_url(item["platform"], item["source_url"])
    except ValueError:
        queued_listing_id = None
    if queued_listing_id and queued_listing_id != marketplace_listing_id:
        raise ValueError("captured listing does not match the queued URL")
    return {
        "capture_source": "csv_batch",
        "capture_batch_id": item["batch_id"],
        "csv_row": item["row_number"],
        "original_csv_filename": item["original_filename"],
        "source_category": item["category"],
    }


def _cleanup_capture_file(path, stop_at) -> None:
    if path is None:
        return
    path = path.resolve()
    stop_at = stop_at.resolve()
    if path != stop_at and stop_at not in path.parents:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return
    parent = path.parent
    while parent != stop_at and stop_at in parent.parents:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent

def _validate_seller_url(platform: str, url: str) -> str:
    """Same trust boundary as a listing URL, without the listing-path shape requirement --
    profile/seller page paths vary too much per platform to pin to one regex."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError):
        raise ValueError("seller URL is not a valid marketplace URL")
    if (
        parsed.scheme.lower() != "https"
        or host not in ALLOWED_HOSTS[platform]
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        raise ValueError("seller URL is not a valid marketplace URL")
    path = unquote(parsed.path)
    if "\\" in path or any(ord(ch) < 32 for ch in path):
        raise ValueError("seller URL is not a valid marketplace URL")
    return urlunsplit((parsed.scheme, parsed.hostname, parsed.path, "", ""))


def attach_seller_capture(listing_id: str, payload) -> dict:
    """Record the seller/profile page as a second, independent capture on an existing listing.

    The seller page's visible text is the primary source for the four seller/behavioural
    fields; its screenshot is secondary proof, same treatment as the listing screenshot.
    """
    c = connect()
    try:
        row = c.execute(
            """SELECT listing.platform,listing.staging_text_path,listing.capture_source,
                      batch.status AS capture_batch_status
               FROM listings listing
               LEFT JOIN capture_batches batch ON batch.batch_id=listing.capture_batch_id
               WHERE listing.listing_id=?""",
            (listing_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        raise KeyError(listing_id)
    platform = row["platform"]
    seller_url = _validate_seller_url(platform, payload.seller_url)

    seller_screenshot_file = None
    staging_path = None
    staging_temporary = None
    try:
        seller_screenshot_path = save_private_screenshot(platform, listing_id, payload.screenshot_data_url, filename="seller")
        seller_screenshot_file = settings.root / seller_screenshot_path

        staging = {}
        if row["staging_text_path"]:
            staging_path = settings.root / row["staging_text_path"]
            if staging_path.exists():
                staging = json.loads(staging_path.read_text(encoding="utf-8"))
            staging["seller_visible_text"] = scrub_text(payload.visible_text).text or None
            staging_temporary = staging_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            staging_temporary.write_text(json.dumps(staging, ensure_ascii=False), encoding="utf-8")
            staging_temporary.replace(staging_path)
            staging_temporary = None

        with transaction() as con:
            con.execute(
                "UPDATE listings SET seller_url=?,seller_screenshot_path=?,updated_at=? WHERE listing_id=?",
                (seller_url, seller_screenshot_path, now_iso(), listing_id),
            )
    except Exception:
        _cleanup_capture_file(staging_temporary, settings.data_dir / "private" / "staging")
        _cleanup_capture_file(seller_screenshot_file, settings.data_dir / "private" / "screenshots")
        raise
    if row["capture_source"] != "csv_batch" or row["capture_batch_status"] not in {
        "running",
        "paused",
        "stopping",
    }:
        refresh_annotation_dataset_safely("seller_capture_completed")
    return {"listing_id": listing_id, "seller_url": seller_url}


def create_capture(payload) -> dict:
    marketplace_listing_id = validate_listing_capture(payload)
    provenance = _capture_provenance(payload, marketplace_listing_id)
    listing_id = str(uuid.uuid4())
    canonical_url = canonicalize_url(payload.source_url)
    uhash = url_hash(canonical_url)
    screenshot_file = None
    staging_path = None
    staging_temporary = None
    try:
        with transaction() as con:
            existing = con.execute("SELECT listing_id,status FROM listings WHERE source_url_hash=? LIMIT 1", (uhash,)).fetchone()
            if existing:
                return {"duplicate": True, "listing_id": existing["listing_id"], "status": existing["status"]}
            existing = con.execute("SELECT listing_id,status FROM listings WHERE platform=? AND marketplace_listing_id=? LIMIT 1", (payload.platform, marketplace_listing_id)).fetchone()
            if existing:
                return {"duplicate": True, "listing_id": existing["listing_id"], "status": existing["status"]}
            screenshot_path = save_private_screenshot(payload.platform, listing_id, payload.screenshot_data_url)
            screenshot_file = settings.root / screenshot_path
            staging_path = settings.data_dir / "private" / "staging" / f"{listing_id}.json"
            staging_path.parent.mkdir(parents=True, exist_ok=True)
            staging_temporary = staging_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            # Captured page text is the primary extraction source, so it must be persisted for the
            # AI step to read later. It is regex-scrubbed before it ever touches disk (same patterns
            # used on the AI's own output) so a raw seller email/phone/handle is never written, even
            # to this private, access-controlled file. It gets the same deleted-after-review treatment
            # as the screenshot (see review._cleanup_private_assets).
            staging_temporary.write_text(json.dumps({
                "image_urls": payload.image_urls[:settings.max_product_images],
                "visible_text": scrub_text(payload.visible_text).text or None,
            }, ensure_ascii=False), encoding="utf-8")
            staging_temporary.replace(staging_path)
            now = now_iso()
            con.execute("""
                INSERT INTO listings(
                    listing_id,platform,marketplace_listing_id,source_url,source_url_hash,
                    page_title,status,screenshot_path,staging_text_path,captured_at,
                    capture_source,capture_batch_id,csv_row,original_csv_filename,source_category,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                listing_id,payload.platform,marketplace_listing_id,canonical_url,uhash,
                payload.page_title,"captured",screenshot_path,
                str(staging_path.relative_to(settings.root)),now,
                provenance["capture_source"],provenance["capture_batch_id"],
                provenance["csv_row"],provenance["original_csv_filename"],
                provenance["source_category"],now,now,
            ))
            capture_reason = (
                "CSV batch replay capture"
                if provenance["capture_source"] == "csv_batch"
                else "manual extension capture"
            )
            if provenance["capture_source"] == "csv_batch":
                con.execute(
                    """UPDATE capture_batch_items
                       SET listing_id=?,status_message='Listing evidence stored; capturing seller behaviour',
                           updated_at=?
                       WHERE batch_item_id=? AND status IN ('opening','capturing')""",
                    (listing_id, now, payload.batch_item_id),
                )
            con.execute("INSERT INTO status_history(history_id,listing_id,from_status,to_status,timestamp,reason) VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()),listing_id,None,"captured",now,capture_reason))
    except Exception:
        _cleanup_capture_file(staging_temporary, settings.data_dir / "private" / "staging")
        _cleanup_capture_file(staging_path, settings.data_dir / "private" / "staging")
        _cleanup_capture_file(screenshot_file, settings.data_dir / "private" / "screenshots")
        raise
    if provenance["capture_source"] == "extension":
        refresh_annotation_dataset_safely("manual_capture_completed")
    return {"duplicate": False, "listing_id": listing_id, "status": "captured"}
