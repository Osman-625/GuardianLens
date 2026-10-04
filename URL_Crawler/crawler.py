from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.async_api import (
    Browser,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from url_utils import normalize_listing_url, normalize_mudah_listing_url

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
DEBUG_DIR = ROOT / "debug"
PAGINATION_STAGNATED_ERROR = "pagination_stagnated_no_new_urls"
LISTING_ID_RE = re.compile(r"-(\d+)(?:/|\.htm)$")


class SiteBlockedError(RuntimeError):
    pass


def listing_identity(url: str) -> str:
    match = LISTING_ID_RE.search(url)
    return match.group(1) if match else url


def mudah_page_url(seed_url: str, page_number: int) -> str:
    parts = urlsplit(seed_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["o"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def jittered_delay_ms(delay_ms: int, minimum_ms: int = 0) -> int:
    delay_ms = max(delay_ms, minimum_ms)
    spread = max(1, delay_ms // 5)
    return max(minimum_ms, delay_ms + random.randint(-spread, spread))


async def prepare_for_click(page: Page, locator: Locator, delay_ms: int) -> None:
    await page.mouse.wheel(0, random.randint(240, 640))
    await page.wait_for_timeout(jittered_delay_ms(max(350, delay_ms // 2), 250))
    await locator.scroll_into_view_if_needed(timeout=2500)
    await page.wait_for_timeout(random.randint(120, 320))


async def try_select_all_phone_listings(page: Page, category: str) -> None:
    if category != "Phones":
        return

    # The Mobile Phones category opens on a Certified catalogue whose product
    # URLs are not marketplace listing URLs. Switch to the standard All tab and
    # wait until its /p/ links are actually mounted before extraction begins.
    listing_links = page.locator('a[href*="/p/"]')
    if await listing_links.count():
        print("    phone_all_tab outcome=already_all exception=''")
        return

    last_error = "All button not found"
    for attempt_no in range(1, 4):
        try:
            locator = page.get_by_role("button", name="All", exact=True)
            await locator.first.wait_for(state="visible", timeout=8000)
            count = await locator.count()
            clicked = False
            for index in range(count):
                item = locator.nth(index)
                if not await item.is_visible():
                    continue
                await prepare_for_click(page, item, 900)
                await item.click(timeout=3500)
                clicked = True
                break
            if not clicked:
                raise RuntimeError("All button was not visible")

            await listing_links.first.wait_for(state="attached", timeout=10000)
            print(
                f"    phone_all_tab attempt={attempt_no} "
                "outcome=switched_to_all exception=''"
            )
            return
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"    phone_all_tab attempt={attempt_no} outcome=retry "
                f"exception={last_error}"
            )
            await page.wait_for_timeout(jittered_delay_ms(1000, 600))

    raise RuntimeError(f"phone_all_tab_failed_after_3_attempts: {last_error}")


@dataclass(frozen=True)
class SiteSpec:
    key: str
    app_name: str
    default_config: Path
    href_selector: str
    normalize: Callable[[str | None], str | None]
    show_more_selectors: tuple[str, ...]
    blocked_message: str
    post_load_hook: Callable[[Page, str], Awaitable[None]] | None = None


@dataclass(frozen=True)
class SelectorAttempt:
    selector: str
    outcome: str
    exception_text: str = ""


@dataclass(frozen=True)
class ShowMoreResult:
    clicked: bool
    selector: str | None
    attempts: tuple[SelectorAttempt, ...]


@dataclass(frozen=True)
class ListingUrlExtraction:
    urls: tuple[str, ...]
    raw_url_count: int
    duplicates_skipped: int = 0


@dataclass(frozen=True)
class PaginationResult:
    urls: tuple[str, ...]
    duplicates_skipped: int
    pagination_rounds: int
    last_raw_url_count: int
    last_new_url_count: int
    stop_reason: str
    error: str = ""


SITES: dict[str, SiteSpec] = {
    "carousell": SiteSpec(
        key="carousell",
        app_name="Carousell",
        default_config=ROOT / "config" / "categories.csv",
        href_selector='a[href*="/p/"]',
        normalize=normalize_listing_url,
        show_more_selectors=(
            'button:has-text("Show more results")',
            '[role="button"]:has-text("Show more results")',
            'button:has-text("Show more")',
        ),
        blocked_message=(
            "Carousell returned a CAPTCHA/security (Cloudflare) page. Headless browsing "
            "is blocked. Stop the run and retry with run_carousell_soft.bat / "
            "run_carousell_full.bat / --headed."
        ),
        post_load_hook=try_select_all_phone_listings,
    ),
    "mudah": SiteSpec(
        key="mudah",
        app_name="Mudah",
        default_config=ROOT / "config" / "categories_mudah.csv",
        href_selector='a[href*=".htm"]',
        normalize=normalize_mudah_listing_url,
        show_more_selectors=("text=Next",),
        blocked_message=(
            "Mudah.my returned a CAPTCHA/security (Cloudflare) page. Headless browsing "
            "is blocked. Stop the run and retry with run_mudah_soft.bat / "
            "run_mudah_full.bat / --headed."
        ),
        post_load_hook=None,
    ),
}


def default_output_path(site: str, mode: str) -> Path:
    return OUTPUT_DIR / f"{site}_urls_{mode}.csv"


def default_summary_path(site: str, mode: str) -> Path:
    return OUTPUT_DIR / f"{site}_summary_{mode}.csv"


def default_state_path(summary_path: Path) -> Path:
    return Path(f"{summary_path}.state.json")


def write_run_state(path: Path, state: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.time()
    temp_path = path.parent / f".{path.name}.{state['run_id']}.tmp"
    temp_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp_path, path)


@dataclass(frozen=True)
class CategoryConfig:
    category: str
    soft_target: int
    full_target: int
    seed_urls: tuple[str, ...]

    def target(self, mode: str) -> int:
        return self.soft_target if mode == "soft" else self.full_target


def load_config(path: Path) -> list[CategoryConfig]:
    rows: list[CategoryConfig] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"category", "soft_target", "full_target", "seed_urls"}
        if set(reader.fieldnames or []) != required:
            raise ValueError(f"Config columns must be exactly: {', '.join(required)}")

        for row in reader:
            seeds = tuple(u.strip() for u in row["seed_urls"].split("|") if u.strip())
            if not seeds:
                raise ValueError(f"{row['category']}: no seed URL configured")
            rows.append(
                CategoryConfig(
                    category=row["category"].strip(),
                    soft_target=int(row["soft_target"]),
                    full_target=int(row["full_target"]),
                    seed_urls=seeds,
                )
            )
    return rows


def init_output(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["app", "category", "product_url"])
        writer.writeheader()


def append_urls(path: Path, app_name: str, category: str, urls: Iterable[str]) -> None:
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["app", "category", "product_url"])
        for url in urls:
            writer.writerow({"app": app_name, "category": category, "product_url": url})
        f.flush()


def write_summary(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "category",
        "target",
        "collected",
        "remaining",
        "duplicates_skipped",
        "seed_pages_used",
        "status",
        "error",
        "pagination_rounds",
        "last_raw_url_count",
        "last_new_url_count",
        "stop_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


async def page_is_blocked(page: Page, status: int | None = None) -> bool:
    if status in (403, 429, 503):
        return True
    try:
        title = (await page.title()).lower()
        body = (await page.locator("body").inner_text(timeout=3000)).lower()[:6000]
    except Exception:
        return False
    indicators = (
        "captcha",
        "access denied",
        "unusual traffic",
        "verify you are human",
        "security check",
        "just a moment",
        "checking your browser",
        "checking if the site connection is secure",
        "cloudflare",
        "ray id",
        "enable javascript and cookies to continue",
    )
    text = title + "\n" + body
    return any(marker in text for marker in indicators)


async def dismiss_page_overlays(page: Page, site: SiteSpec) -> bool:
    if site.key != "carousell":
        return False

    dialog = page.locator('[role="dialog"]')
    close_selector = '[role="dialog"] button[aria-label="Close"]'
    try:
        visible_dialog: Locator | None = None
        for index in range(await dialog.count()):
            candidate = dialog.nth(index)
            if await candidate.is_visible():
                visible_dialog = candidate
                break
        if visible_dialog is None:
            return False

        close_buttons = page.locator(close_selector)
        close_error = ""
        for index in range(await close_buttons.count()):
            close_button = close_buttons.nth(index)
            if not await close_button.is_visible():
                continue
            try:
                await page.wait_for_timeout(random.randint(150, 350))
                await close_button.click(timeout=2500)
                await visible_dialog.wait_for(state="hidden", timeout=3500)
                print(
                    f"      overlay selector={close_selector!r} "
                    "outcome=closed exception=''"
                )
                return True
            except Exception as exc:
                close_error = f"{type(exc).__name__}: {exc}"
                print(
                    f"      overlay selector={close_selector!r} "
                    f"outcome=close_button_failed exception={close_error}"
                )

        try:
            await page.keyboard.press("Escape")
            await visible_dialog.wait_for(state="hidden", timeout=3500)
            print("      overlay selector='Escape' outcome=closed exception=''")
            return True
        except Exception as exc:
            escape_error = f"{type(exc).__name__}: {exc}"
            detail = f"close={close_error!r} escape={escape_error!r}"
            print(
                f"      overlay selector={close_selector!r} outcome=close_failed "
                f"exception={detail}"
            )
            return False
    except Exception as exc:
        print(
            f"      overlay selector={close_selector!r} outcome=close_failed "
            f"exception={type(exc).__name__}: {exc}"
        )
        return False


async def navigate_with_retries(
    page: Page,
    site: SiteSpec,
    url: str,
    attempts: int = 3,
) -> None:
    last_error = ""
    for attempt_no in range(1, attempts + 1):
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(1500)
            if page.url.startswith("chrome-error://"):
                raise RuntimeError(f"browser_error_page: {page.url}")
            if await page_is_blocked(page, status=response.status if response else None):
                raise SiteBlockedError(site.blocked_message)
            print(
                f"      navigation url={url!r} attempt={attempt_no} "
                f"outcome=loaded final_url={page.url!r}"
            )
            return
        except SiteBlockedError:
            raise
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"      navigation url={url!r} attempt={attempt_no} "
                f"outcome=failed exception={last_error!r}"
            )
            if attempt_no >= attempts:
                break
            try:
                await page.goto("about:blank", wait_until="commit", timeout=10_000)
            except Exception as reset_exc:
                print(
                    f"      navigation_reset outcome=failed "
                    f"exception={type(reset_exc).__name__}: {reset_exc}"
                )
            await page.wait_for_timeout(jittered_delay_ms(1200, 750))

    raise RuntimeError(f"navigation_failed_after_{attempts}_attempts: {last_error}")


async def extract_visible_listing_urls(page: Page, site: SiteSpec) -> ListingUrlExtraction:
    hrefs = await page.locator(site.href_selector).evaluate_all(
        "els => els.map(el => el.getAttribute('href')).filter(Boolean)"
    )
    out: list[str] = []
    seen: set[str] = set()
    duplicates_skipped = 0
    for href in hrefs:
        url = site.normalize(href)
        if not url:
            continue
        identity = listing_identity(url)
        if identity in seen:
            duplicates_skipped += 1
            continue
        seen.add(identity)
        out.append(url)
    return ListingUrlExtraction(
        urls=tuple(out),
        raw_url_count=len(hrefs),
        duplicates_skipped=duplicates_skipped,
    )


async def try_show_more(page: Page, site: SiteSpec, delay_ms: int = 900) -> ShowMoreResult:
    attempts: list[SelectorAttempt] = []
    for selector in site.show_more_selectors:
        try:
            matches = page.locator(selector)
            count = await matches.count()
            if not count:
                attempt = SelectorAttempt(selector=selector, outcome="not_found")
                attempts.append(attempt)
                print(f"      show_more selector={selector!r} outcome=not_found exception=''")
                continue

            loc: Locator | None = None
            for index in range(count):
                candidate = matches.nth(index)
                if await candidate.is_visible():
                    loc = candidate
                    break
            if loc is None:
                attempt = SelectorAttempt(selector=selector, outcome="not_visible")
                attempts.append(attempt)
                print(f"      show_more selector={selector!r} outcome=not_visible exception=''")
                continue

            await prepare_for_click(page, loc, delay_ms)
            try:
                await loc.click(timeout=2500)
            except Exception as exc:
                if await dismiss_page_overlays(page, site):
                    try:
                        await prepare_for_click(page, loc, delay_ms)
                        await loc.click(timeout=2500)
                        attempt = SelectorAttempt(
                            selector=selector, outcome="clicked_after_overlay"
                        )
                        attempts.append(attempt)
                        print(
                            f"      show_more selector={selector!r} "
                            "outcome=clicked_after_overlay exception=''"
                        )
                        return ShowMoreResult(
                            clicked=True, selector=selector, attempts=tuple(attempts)
                        )
                    except Exception as retry_exc:
                        exc = retry_exc
                exception_text = f"{type(exc).__name__}: {exc}"
                attempt = SelectorAttempt(
                    selector=selector,
                    outcome="click_failed",
                    exception_text=exception_text,
                )
                attempts.append(attempt)
                print(
                    f"      show_more selector={selector!r} outcome=click_failed "
                    f"exception={exception_text!r}"
                )
                continue

            attempt = SelectorAttempt(selector=selector, outcome="clicked")
            attempts.append(attempt)
            print(f"      show_more selector={selector!r} outcome=clicked exception=''")
            return ShowMoreResult(clicked=True, selector=selector, attempts=tuple(attempts))
        except Exception as exc:
            exception_text = f"{type(exc).__name__}: {exc}"
            attempt = SelectorAttempt(
                selector=selector,
                outcome="selector_failed",
                exception_text=exception_text,
            )
            attempts.append(attempt)
            print(
                f"      show_more selector={selector!r} outcome=selector_failed "
                f"exception={exception_text!r}"
            )

    return ShowMoreResult(clicked=False, selector=None, attempts=tuple(attempts))


def debug_category_name(category: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-") or "category"


async def dump_stagnated_page(page: Page, site: SiteSpec, category: str, round_no: int) -> None:
    path = DEBUG_DIR / site.key / f"{debug_category_name(category)}-stagnated-{round_no}.html"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(await page.content(), encoding="utf-8")
        print(f"      pagination_debug_html={path}")
    except Exception as exc:
        print(
            f"      pagination_debug_dump_failed path={path} "
            f"exception={type(exc).__name__}: {exc}"
        )


async def collect_from_seed(
    page: Page,
    site: SiteSpec,
    seed_url: str,
    category: str,
    quota: int,
    global_seen: set[str],
    delay_ms: int,
    max_rounds: int,
    collected_before: int = 0,
) -> PaginationResult:
    collected: list[str] = []
    collected_identities: set[str] = set()
    pagination_seen: set[str] = set()
    duplicates = 0
    rounds_completed = 0
    last_raw_url_count = 0
    last_new_url_count = 0

    def finish(stop_reason: str, error: str = "") -> PaginationResult:
        global_seen.update(collected_identities)
        return PaginationResult(
            urls=tuple(collected),
            duplicates_skipped=duplicates,
            pagination_rounds=rounds_completed,
            last_raw_url_count=last_raw_url_count,
            last_new_url_count=last_new_url_count,
            stop_reason=stop_reason,
            error=error,
        )

    print(f"    open: {seed_url}")
    await navigate_with_retries(page, site, seed_url)
    await dismiss_page_overlays(page, site)

    if site.post_load_hook:
        await site.post_load_hook(page, category)

    stagnant_rounds = 0
    try:
        for round_no in range(1, max_rounds + 1):
            await dismiss_page_overlays(page, site)
            if round_no > 1 and await page_is_blocked(page):
                raise SiteBlockedError(site.blocked_message)

            extraction = await extract_visible_listing_urls(page, site)
            candidates = extraction.urls
            identities = tuple(listing_identity(url) for url in candidates)
            last_raw_url_count = extraction.raw_url_count
            new_this_round = 0
            duplicates_this_round = extraction.duplicates_skipped
            duplicates += extraction.duplicates_skipped
            pagination_progress = sum(
                identity not in pagination_seen for identity in identities
            )
            pagination_seen.update(identities)

            for url, identity in zip(candidates, identities):
                if identity in global_seen or identity in collected_identities:
                    duplicates += 1
                    duplicates_this_round += 1
                    continue
                collected_identities.add(identity)
                collected.append(url)
                new_this_round += 1
                if len(collected) >= quota:
                    break

            last_new_url_count = new_this_round
            rounds_completed = round_no
            print(
                "      pagination_round "
                f"category={category!r} seed_url={seed_url!r} round={round_no} "
                f"raw_url_count={last_raw_url_count} "
                f"new_unique_added={new_this_round} "
                f"duplicates_skipped={duplicates_this_round} "
                f"pagination_progress={pagination_progress} "
                f"total_collected={collected_before + len(collected)}"
            )

            if len(collected) >= quota:
                return finish("quota_reached")

            if new_this_round == 0 and pagination_progress == 0:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

            if stagnant_rounds >= 5:
                await dump_stagnated_page(page, site, category, round_no)
                return finish("pagination_stagnated", PAGINATION_STAGNATED_ERROR)

            if site.key == "mudah":
                await page.wait_for_timeout(jittered_delay_ms(delay_ms, 250))
                next_url = mudah_page_url(seed_url, round_no + 1)
                await navigate_with_retries(page, site, next_url)
                print(
                    f"      mudah_pagination page={round_no + 1} "
                    f"url={next_url!r} outcome=navigated"
                )
            else:
                await dismiss_page_overlays(page, site)
                show_more = await try_show_more(page, site, delay_ms=delay_ms)
                if not show_more.clicked:
                    await page.mouse.wheel(0, random.randint(900, 1500))
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(jittered_delay_ms(delay_ms, 250))

    except SiteBlockedError:
        if not collected:
            raise
        error_text = "pagination_blocked_security_challenge"
        print(f"      pagination_partial_result exception={error_text!r}")
        return finish("pagination_blocked", error_text)
    except Exception as exc:
        if not collected:
            raise
        error_text = f"pagination_error: {type(exc).__name__}: {exc}"
        print(f"      pagination_partial_result exception={error_text!r}")
        return finish("pagination_error", error_text)

    return finish("max_rounds_reached")


async def crawl_category(
    browser: Browser,
    site: SiteSpec,
    cfg: CategoryConfig,
    target: int,
    global_seen: set[str],
    output_path: Path,
    delay_ms: int,
    max_rounds: int,
) -> dict[str, object]:
    context = await browser.new_context(
        viewport={"width": 1440, "height": 1000},
        locale="en-MY",
    )
    page = await context.new_page()
    category_urls: list[str] = []
    duplicate_count = 0
    seed_pages_used = 0
    pagination_rounds = 0
    last_raw_url_count = 0
    last_new_url_count = 0
    stop_reason = "not_started"
    errors: list[str] = []
    stagnation_seen = False

    async def replace_page() -> None:
        nonlocal page
        try:
            await page.close()
        except Exception as exc:
            print(f"    page_reset close_exception={type(exc).__name__}: {exc}")
        page = await context.new_page()
        print("    page_reset outcome=fresh_page_created")

    async def collect_seed(seed: str, quota: int, pass_name: str) -> None:
        nonlocal duplicate_count
        nonlocal last_new_url_count
        nonlocal last_raw_url_count
        nonlocal pagination_rounds
        nonlocal seed_pages_used
        nonlocal stagnation_seen
        nonlocal stop_reason

        seed_pages_used += 1
        print(f"    pagination_pass={pass_name} seed_page_attempt={seed_pages_used}")
        try:
            result = await collect_from_seed(
                page=page,
                site=site,
                seed_url=seed,
                category=cfg.category,
                quota=quota,
                global_seen=global_seen,
                delay_ms=delay_ms,
                max_rounds=max_rounds,
                collected_before=len(category_urls),
            )
        except (PlaywrightTimeoutError, RuntimeError) as exc:
            error_text = str(exc)
            errors.append(error_text)
            stop_reason = "seed_error"
            print(f"    warning: {error_text}")
            await replace_page()
            return
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            errors.append(error_text)
            stop_reason = "seed_error"
            print(f"    warning: {error_text}")
            await replace_page()
            return

        duplicate_count += result.duplicates_skipped
        pagination_rounds += result.pagination_rounds
        last_raw_url_count = result.last_raw_url_count
        last_new_url_count = result.last_new_url_count
        stop_reason = result.stop_reason
        if result.error:
            errors.append(result.error)
        if result.error == PAGINATION_STAGNATED_ERROR:
            stagnation_seen = True

        urls = list(result.urls)
        category_urls.extend(urls)
        append_urls(output_path, site.app_name, cfg.category, urls)
        if result.stop_reason in (
            "max_rounds_reached",
            "pagination_blocked",
            "pagination_error",
            "pagination_stagnated",
        ):
            await replace_page()

    try:
        remaining = target
        total_seeds = len(cfg.seed_urls)

        for idx, seed in enumerate(cfg.seed_urls):
            if remaining <= 0:
                break
            seeds_left = total_seeds - idx
            seed_quota = (remaining + seeds_left - 1) // seeds_left
            await collect_seed(seed, seed_quota, "initial")
            remaining = target - len(category_urls)

        # Give every short category one bounded retry, including categories
        # configured with a single seed and attempts that ended with an error.
        if len(category_urls) < target:
            print(
                f"    second_pass_retry collected={len(category_urls)} "
                f"target={target} seeds={len(cfg.seed_urls)}"
            )
            for seed in cfg.seed_urls:
                gap = target - len(category_urls)
                if gap <= 0:
                    break
                await collect_seed(seed, gap, "retry")

    finally:
        await context.close()

    collected = len(category_urls)
    remaining = max(0, target - collected)
    if collected >= target:
        status = "complete"
        error = ""
        stop_reason = "target_reached"
    elif stagnation_seen:
        status = "partial"
        error = PAGINATION_STAGNATED_ERROR
        stop_reason = "pagination_stagnated"
    elif errors and collected == 0:
        status = "failed"
        error = errors[-1]
    else:
        status = "partial"
        error = errors[-1] if errors else ""

    return {
        "category": cfg.category,
        "target": target,
        "collected": collected,
        "remaining": remaining,
        "duplicates_skipped": duplicate_count,
        "seed_pages_used": seed_pages_used,
        "status": status,
        "error": error,
        "pagination_rounds": pagination_rounds,
        "last_raw_url_count": last_raw_url_count,
        "last_new_url_count": last_new_url_count,
        "stop_reason": stop_reason,
    }


async def run(args: argparse.Namespace) -> int:
    site = SITES[args.site]
    config_path = Path(args.config).resolve() if args.config else site.default_config
    output_path = Path(args.output).resolve() if args.output else default_output_path(args.site, args.mode)
    summary_path = Path(args.summary).resolve() if args.summary else default_summary_path(args.site, args.mode)
    state_path = default_state_path(summary_path)
    run_state: dict[str, object] = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "site": args.site,
        "mode": args.mode,
        "config_path": str(config_path.resolve()),
        "output_path": str(output_path.resolve()),
        "summary_path": str(summary_path.resolve()),
        "expected_total": None,
        "status": "starting",
        "started_at": time.time(),
        "completed_categories": 0,
        "collected": 0,
    }
    write_run_state(state_path, run_state)

    try:
        configs = load_config(config_path)
        expected_total = sum(c.target(args.mode) for c in configs)
        run_state["expected_total"] = expected_total
        write_run_state(state_path, run_state)
    except BaseException as exc:
        run_state.update(
            status="fatal",
            exit_code=1,
            error=f"{type(exc).__name__}: {exc}",
            finished_at=time.time(),
        )
        write_run_state(state_path, run_state)
        raise

    print(f"Site: {site.app_name}")
    print(f"Mode: {args.mode}")
    print(f"Expected total: {expected_total} URLs")
    print(f"Output: {output_path}")
    if not args.headed:
        print(
            f"WARNING: running headless. {site.app_name} blocks headless Chromium with a "
            "Cloudflare challenge on every request. Use --headed unless you have confirmed "
            "headless works in your environment."
        )

    try:
        init_output(output_path)
        write_summary(summary_path, [])
        run_state["status"] = "running"
        write_run_state(state_path, run_state)
    except BaseException as exc:
        run_state.update(
            status="fatal",
            exit_code=1,
            error=f"{type(exc).__name__}: {exc}",
            finished_at=time.time(),
        )
        write_run_state(state_path, run_state)
        raise

    global_seen: set[str] = set()
    summary_rows: list[dict[str, object]] = []

    try:
        async with async_playwright() as pw:
            launch_kwargs = {"headless": not args.headed}
            if args.browser_executable:
                launch_kwargs["executable_path"] = args.browser_executable
            browser = await pw.chromium.launch(**launch_kwargs)
            try:
                for cfg in configs:
                    target = cfg.target(args.mode)
                    print(f"\n[{cfg.category}] target={target}")
                    result = await crawl_category(
                        browser=browser,
                        site=site,
                        cfg=cfg,
                        target=target,
                        global_seen=global_seen,
                        output_path=output_path,
                        delay_ms=args.delay_ms,
                        max_rounds=args.max_rounds,
                    )
                    summary_rows.append(result)
                    write_summary(summary_path, summary_rows)
                    run_state.update(
                        completed_categories=len(summary_rows),
                        collected=sum(int(row["collected"]) for row in summary_rows),
                    )
                    write_run_state(state_path, run_state)
                    print(
                        f"  -> {result['collected']}/{result['target']} "
                        f"({result['status']})"
                    )
            finally:
                await browser.close()
    except BaseException as exc:
        interrupted = isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError))
        run_state.update(
            status="interrupted" if interrupted else "fatal",
            exit_code=130 if interrupted else 1,
            error=f"{type(exc).__name__}: {exc}",
            finished_at=time.time(),
        )
        write_run_state(state_path, run_state)
        raise

    total_collected = sum(int(r["collected"]) for r in summary_rows)
    total_duplicates = sum(int(r["duplicates_skipped"]) for r in summary_rows)
    failed = [r for r in summary_rows if r["status"] == "failed"]
    partial = [r for r in summary_rows if r["status"] == "partial"]

    print("\nDone")
    print(f"Collected: {total_collected}/{expected_total}")
    print(f"Duplicates skipped: {total_duplicates}")
    print(f"URL CSV: {output_path}")
    print(f"Summary CSV: {summary_path}")

    if failed or partial:
        print("\nERRORS / SHORTFALLS:")
        for r in failed + partial:
            detail = f" - {r['error']}" if r["error"] else ""
            print(f"  [{r['status'].upper()}] {r['category']}: {r['collected']}/{r['target']}{detail}")
    else:
        print("\nAll categories reached their target with no errors.")

    all_complete = len(summary_rows) == len(configs) and all(
        row["status"] == "complete"
        and int(row["collected"]) == int(row["target"])
        and int(row["remaining"]) == 0
        for row in summary_rows
    )
    exit_code = 0 if total_collected == expected_total and all_complete else 2
    run_state.update(
        status="success" if exit_code == 0 else "shortfall",
        exit_code=exit_code,
        error="",
        collected=total_collected,
        completed_categories=len(summary_rows),
        finished_at=time.time(),
    )
    write_run_state(state_path, run_state)
    return exit_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Carousell/Mudah Malaysia product listing URLs by category."
    )
    parser.add_argument(
        "--site",
        choices=tuple(SITES.keys()),
        default="carousell",
        help="Which marketplace to crawl.",
    )
    parser.add_argument(
        "--mode",
        choices=("soft", "full"),
        default="soft",
        help="soft = proportional quick test, full = full target (see each site's config).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Defaults to each site's config/categories*.csv.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Defaults to output/<site>_urls_<mode>.csv (keeps soft/full/test runs separate).",
    )
    parser.add_argument(
        "--summary",
        default=None,
        help="Defaults to output/<site>_summary_<mode>.csv (keeps soft/full/test runs separate).",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show Chromium. Useful if the site blocks headless browsing or you want to watch the run.",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=1800,
        help="Pause between load-more/scroll rounds. Default: 1800 ms.",
    )
    parser.add_argument(
        "--browser-executable",
        default=None,
        help="Optional Chromium/Chrome executable path. Normally not needed after setup.bat.",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=120,
        help="Maximum load-more/scroll rounds per seed page. Default: 120.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        code = asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nStopped by user. CSV rows written before the stop are kept.")
        code = 130
    except Exception as exc:
        print(f"\nFatal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
