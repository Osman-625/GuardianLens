import unittest
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import crawler


class MudahPageUrlTests(unittest.TestCase):
    def test_preserves_search_query_while_setting_page_number(self):
        result = crawler.mudah_page_url(
            "https://www.mudah.my/malaysia/phones-for-sale?q=iphone&o=7&sort=price",
            3,
        )

        self.assertEqual(
            result,
            "https://www.mudah.my/malaysia/phones-for-sale?q=iphone&o=3&sort=price",
        )


class NavigateWithRetriesTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_after_first_failure_then_succeeds(self):
        site = crawler.SITES["carousell"]
        url = "https://www.carousell.com.my/categories/mobile-phones-215/"
        page = MagicMock()
        page.url = url
        response = MagicMock(status=200)
        page.goto = AsyncMock(
            side_effect=[RuntimeError("temporary network failure"), None, response]
        )
        page.wait_for_timeout = AsyncMock()

        with (
            patch("crawler.page_is_blocked", new=AsyncMock(return_value=False)) as blocked,
            patch("crawler.jittered_delay_ms", return_value=750),
        ):
            await crawler.navigate_with_retries(page, site, url, attempts=3)

        self.assertEqual(
            page.goto.await_args_list,
            [
                call(url, wait_until="domcontentloaded", timeout=60_000),
                call("about:blank", wait_until="commit", timeout=10_000),
                call(url, wait_until="domcontentloaded", timeout=60_000),
            ],
        )
        blocked.assert_awaited_once_with(page, status=200)

    async def test_rejects_chrome_error_page_after_retries(self):
        site = crawler.SITES["carousell"]
        url = "https://www.carousell.com.my/categories/mobile-phones-215/"
        page = MagicMock()
        page.url = "chrome-error://chromewebdata/"
        page.goto = AsyncMock(return_value=MagicMock(status=200))
        page.wait_for_timeout = AsyncMock()

        with (
            patch("crawler.page_is_blocked", new=AsyncMock()) as blocked,
            patch("crawler.jittered_delay_ms", return_value=750),
            self.assertRaisesRegex(
                RuntimeError,
                "navigation_failed_after_2_attempts: .*browser_error_page",
            ),
        ):
            await crawler.navigate_with_retries(page, site, url, attempts=2)

        self.assertEqual(
            page.goto.await_args_list,
            [
                call(url, wait_until="domcontentloaded", timeout=60_000),
                call("about:blank", wait_until="commit", timeout=10_000),
                call(url, wait_until="domcontentloaded", timeout=60_000),
            ],
        )
        blocked.assert_not_awaited()


class TryShowMoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_selector_exception_is_reported_before_later_success(self):
        site = replace(
            crawler.SITES["carousell"],
            show_more_selectors=("broken-selector", "working-selector"),
        )
        page = MagicMock()
        page.mouse.wheel = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        locator = MagicMock()
        locator.is_visible = AsyncMock(return_value=True)
        locator.scroll_into_view_if_needed = AsyncMock()
        locator.click = AsyncMock()

        locator_query = MagicMock()
        locator_query.count = AsyncMock(return_value=1)
        locator_query.nth.return_value = locator
        page.locator.side_effect = [
            RuntimeError("selector lookup exploded"),
            locator_query,
        ]

        with patch("builtins.print") as mock_print:
            result = await crawler.try_show_more(page, site, delay_ms=500)

        self.assertTrue(result.clicked)
        self.assertEqual(result.selector, "working-selector")
        self.assertEqual(
            [(attempt.selector, attempt.outcome) for attempt in result.attempts],
            [
                ("broken-selector", "selector_failed"),
                ("working-selector", "clicked"),
            ],
        )
        self.assertEqual(
            result.attempts[0].exception_text,
            "RuntimeError: selector lookup exploded",
        )
        locator.click.assert_awaited_once_with(timeout=2500)
        page.mouse.wheel.assert_awaited_once()

        messages = [str(args[0]) for args, _ in mock_print.call_args_list]
        self.assertTrue(
            any(
                "selector='broken-selector'" in message
                and "RuntimeError: selector lookup exploded" in message
                for message in messages
            )
        )


class ListingUrlExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_page_normalized_duplicates_are_counted(self):
        site = crawler.SITES["carousell"]
        page = MagicMock()
        locator = MagicMock()
        locator.evaluate_all = AsyncMock(
            return_value=[
                "/p/headphone-1455931388/?t-id=first",
                "https://www.carousell.com.my/p/headphone-1455931388/?ref=duplicate",
                "/p/phone-case-1455931389/",
            ]
        )
        page.locator.return_value = locator

        result = await crawler.extract_visible_listing_urls(page, site)

        self.assertEqual(
            result.urls,
            (
                "https://www.carousell.com.my/p/headphone-1455931388/",
                "https://www.carousell.com.my/p/phone-case-1455931389/",
            ),
        )
        self.assertEqual(result.raw_url_count, 3)
        self.assertEqual(result.duplicates_skipped, 1)
        page.locator.assert_called_once_with(site.href_selector)


class CollectFromSeedTests(unittest.IsolatedAsyncioTestCase):
    async def test_five_stagnant_rounds_return_diagnostic_error_and_dump_html(self):
        site = replace(crawler.SITES["carousell"], post_load_hook=None)
        page = MagicMock()
        page.goto = AsyncMock(return_value=MagicMock(status=200))
        page.wait_for_timeout = AsyncMock()
        page.mouse.wheel = AsyncMock()
        page.evaluate = AsyncMock()

        extraction = crawler.ListingUrlExtraction(
            urls=(),
            raw_url_count=7,
            duplicates_skipped=2,
        )
        show_more = crawler.ShowMoreResult(clicked=False, selector=None, attempts=())

        with (
            patch("crawler.navigate_with_retries", new=AsyncMock()) as mock_navigate,
            patch(
                "crawler.dismiss_page_overlays", new=AsyncMock(return_value=False)
            ),
            patch("crawler.page_is_blocked", new=AsyncMock(return_value=False)),
            patch(
                "crawler.extract_visible_listing_urls",
                new=AsyncMock(return_value=extraction),
            ) as mock_extract,
            patch(
                "crawler.try_show_more",
                new=AsyncMock(return_value=show_more),
            ) as mock_show_more,
            patch("crawler.dump_stagnated_page", new=AsyncMock()) as mock_dump,
        ):
            result = await crawler.collect_from_seed(
                page=page,
                site=site,
                seed_url="https://example.test/phones",
                category="Phones",
                quota=90,
                global_seen=set(),
                delay_ms=0,
                max_rounds=20,
            )

        self.assertEqual(result.urls, ())
        self.assertEqual(result.pagination_rounds, 5)
        self.assertEqual(result.last_raw_url_count, 7)
        self.assertEqual(result.last_new_url_count, 0)
        self.assertEqual(result.stop_reason, "pagination_stagnated")
        self.assertEqual(result.error, "pagination_stagnated_no_new_urls")
        self.assertEqual(result.duplicates_skipped, 10)
        self.assertEqual(mock_extract.await_count, 5)
        self.assertEqual(mock_show_more.await_count, 4)
        mock_navigate.assert_awaited_once_with(
            page,
            site,
            "https://example.test/phones",
        )
        mock_dump.assert_awaited_once_with(page, site, "Phones", 5)

    async def test_unexpected_later_page_exception_returns_committed_partial_checkpoint(self):
        site = replace(crawler.SITES["carousell"], post_load_hook=None)
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        global_seen = {"9000"}
        pending_url = "https://example.test/p/pending-9001/"
        first_round = crawler.ListingUrlExtraction(
            urls=(pending_url,),
            raw_url_count=1,
        )
        show_more = crawler.ShowMoreResult(
            clicked=True,
            selector="show-more",
            attempts=(),
        )

        with (
            patch("crawler.navigate_with_retries", new=AsyncMock()) as mock_navigate,
            patch(
                "crawler.dismiss_page_overlays", new=AsyncMock(return_value=False)
            ),
            patch("crawler.page_is_blocked", new=AsyncMock(return_value=False)),
            patch(
                "crawler.extract_visible_listing_urls",
                new=AsyncMock(
                    side_effect=[first_round, ValueError("pagination exploded")]
                ),
            ),
            patch(
                "crawler.try_show_more",
                new=AsyncMock(return_value=show_more),
            ) as mock_show_more,
            patch("crawler.jittered_delay_ms", return_value=0),
        ):
            result = await crawler.collect_from_seed(
                page=page,
                site=site,
                seed_url="https://example.test/phones",
                category="Phones",
                quota=2,
                global_seen=global_seen,
                delay_ms=0,
                max_rounds=10,
            )

        self.assertEqual(result.urls, (pending_url,))
        self.assertEqual(result.pagination_rounds, 1)
        self.assertEqual(result.last_raw_url_count, 1)
        self.assertEqual(result.last_new_url_count, 1)
        self.assertEqual(result.stop_reason, "pagination_error")
        self.assertEqual(
            result.error,
            "pagination_error: ValueError: pagination exploded",
        )
        self.assertEqual(global_seen, {"9000", "9001"})
        mock_navigate.assert_awaited_once_with(
            page,
            site,
            "https://example.test/phones",
        )
        mock_show_more.assert_awaited_once_with(page, site, delay_ms=0)

    async def test_retry_frontier_progress_survives_more_than_five_replay_rounds(self):
        site = replace(crawler.SITES["carousell"], post_load_hook=None)
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()

        replay_urls = tuple(
            f"https://example.test/p/replay-{1000 + index}/"
            for index in range(1, 7)
        )
        replay_identities = {str(1000 + index) for index in range(1, 7)}
        fresh_url = "https://example.test/p/fresh-2000/"
        global_seen = set(replay_identities)
        extractions = [
            crawler.ListingUrlExtraction(urls=(url,), raw_url_count=1)
            for url in replay_urls
        ]
        extractions.append(
            crawler.ListingUrlExtraction(urls=(fresh_url,), raw_url_count=1)
        )
        show_more = crawler.ShowMoreResult(
            clicked=True,
            selector="show-more",
            attempts=(),
        )

        with (
            patch("crawler.navigate_with_retries", new=AsyncMock()) as mock_navigate,
            patch(
                "crawler.dismiss_page_overlays", new=AsyncMock(return_value=False)
            ),
            patch("crawler.page_is_blocked", new=AsyncMock(return_value=False)),
            patch(
                "crawler.extract_visible_listing_urls",
                new=AsyncMock(side_effect=extractions),
            ) as mock_extract,
            patch(
                "crawler.try_show_more",
                new=AsyncMock(return_value=show_more),
            ) as mock_show_more,
            patch("crawler.dump_stagnated_page", new=AsyncMock()) as mock_dump,
            patch("crawler.jittered_delay_ms", return_value=0),
        ):
            result = await crawler.collect_from_seed(
                page=page,
                site=site,
                seed_url="https://example.test/phones",
                category="Phones",
                quota=1,
                global_seen=global_seen,
                delay_ms=0,
                max_rounds=10,
            )

        self.assertEqual(result.urls, (fresh_url,))
        self.assertEqual(result.pagination_rounds, 7)
        self.assertEqual(result.duplicates_skipped, 6)
        self.assertEqual(result.last_new_url_count, 1)
        self.assertEqual(result.stop_reason, "quota_reached")
        self.assertEqual(result.error, "")
        self.assertEqual(mock_extract.await_count, 7)
        self.assertEqual(mock_show_more.await_count, 6)
        mock_navigate.assert_awaited_once_with(
            page,
            site,
            "https://example.test/phones",
        )
        mock_dump.assert_not_awaited()
        self.assertEqual(global_seen, {*replay_identities, "2000"})

    async def test_mudah_uses_deterministic_page_urls_between_rounds(self):
        site = crawler.SITES["mudah"]
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        seed_url = "https://www.mudah.my/malaysia/phones-for-sale?q=iphone&sort=price"
        listing_urls = tuple(
            f"https://www.mudah.my/malaysia/phone-{listing_id}.htm"
            for listing_id in (3001, 3002, 3003)
        )
        extractions = [
            crawler.ListingUrlExtraction(urls=(url,), raw_url_count=1)
            for url in listing_urls
        ]
        global_seen: set[str] = set()

        with (
            patch("crawler.navigate_with_retries", new=AsyncMock()) as mock_navigate,
            patch(
                "crawler.dismiss_page_overlays", new=AsyncMock(return_value=False)
            ),
            patch("crawler.page_is_blocked", new=AsyncMock(return_value=False)),
            patch(
                "crawler.extract_visible_listing_urls",
                new=AsyncMock(side_effect=extractions),
            ),
            patch("crawler.try_show_more", new=AsyncMock()) as mock_show_more,
            patch("crawler.jittered_delay_ms", return_value=0),
        ):
            result = await crawler.collect_from_seed(
                page=page,
                site=site,
                seed_url=seed_url,
                category="Phones",
                quota=3,
                global_seen=global_seen,
                delay_ms=0,
                max_rounds=10,
            )

        self.assertEqual(result.urls, listing_urls)
        self.assertEqual(result.pagination_rounds, 3)
        self.assertEqual(result.stop_reason, "quota_reached")
        self.assertEqual(global_seen, {"3001", "3002", "3003"})
        self.assertEqual(
            mock_navigate.await_args_list,
            [
                call(page, site, seed_url),
                call(page, site, crawler.mudah_page_url(seed_url, 2)),
                call(page, site, crawler.mudah_page_url(seed_url, 3)),
            ],
        )
        self.assertEqual(page.wait_for_timeout.await_args_list, [call(0), call(0)])
        mock_show_more.assert_not_awaited()


class CrawlCategoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_first_pass_retries_on_a_fresh_page(self):
        browser = MagicMock()
        context = MagicMock()
        failed_page = MagicMock()
        retry_page = MagicMock()
        browser.new_context = AsyncMock(return_value=context)
        context.new_page = AsyncMock(side_effect=[failed_page, retry_page])
        context.close = AsyncMock()
        failed_page.close = AsyncMock()

        cfg = crawler.CategoryConfig(
            category="Phones",
            soft_target=2,
            full_target=2,
            seed_urls=("https://example.test/phones",),
        )
        retry_result = crawler.PaginationResult(
            urls=(
                "https://example.test/p/phone-4001/",
                "https://example.test/p/phone-4002/",
            ),
            duplicates_skipped=1,
            pagination_rounds=2,
            last_raw_url_count=2,
            last_new_url_count=1,
            stop_reason="quota_reached",
        )

        with (
            patch(
                "crawler.collect_from_seed",
                new=AsyncMock(
                    side_effect=[RuntimeError("first page failed"), retry_result]
                ),
            ) as mock_collect,
            patch("crawler.append_urls") as mock_append,
        ):
            result = await crawler.crawl_category(
                browser=browser,
                site=crawler.SITES["carousell"],
                cfg=cfg,
                target=2,
                global_seen=set(),
                output_path=MagicMock(),
                delay_ms=0,
                max_rounds=10,
            )

        self.assertIs(mock_collect.await_args_list[0].kwargs["page"], failed_page)
        self.assertIs(mock_collect.await_args_list[1].kwargs["page"], retry_page)
        failed_page.close.assert_awaited_once_with()
        self.assertEqual(context.new_page.await_count, 2)
        context.close.assert_awaited_once_with()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["error"], "")
        self.assertEqual(result["collected"], 2)
        self.assertEqual(result["seed_pages_used"], 2)
        self.assertEqual(result["stop_reason"], "target_reached")
        mock_append.assert_called_once_with(
            unittest.mock.ANY,
            "Carousell",
            "Phones",
            list(retry_result.urls),
        )

    async def test_single_seed_partial_category_gets_second_pass_and_diagnostics(self):
        browser = MagicMock()
        context = MagicMock()
        initial_page = MagicMock()
        retry_page = MagicMock()
        final_page = MagicMock()
        browser.new_context = AsyncMock(return_value=context)
        context.new_page = AsyncMock(
            side_effect=[initial_page, retry_page, final_page]
        )
        context.close = AsyncMock()
        initial_page.close = AsyncMock()
        retry_page.close = AsyncMock()

        cfg = crawler.CategoryConfig(
            category="Phones",
            soft_target=3,
            full_target=3,
            seed_urls=("https://example.test/phones",),
        )
        first = crawler.PaginationResult(
            urls=("https://example.test/p/one",),
            duplicates_skipped=2,
            pagination_rounds=5,
            last_raw_url_count=11,
            last_new_url_count=0,
            stop_reason="pagination_stagnated",
            error=crawler.PAGINATION_STAGNATED_ERROR,
        )
        retry = crawler.PaginationResult(
            urls=("https://example.test/p/two",),
            duplicates_skipped=3,
            pagination_rounds=4,
            last_raw_url_count=13,
            last_new_url_count=1,
            stop_reason="max_rounds_reached",
        )

        with (
            patch(
                "crawler.collect_from_seed",
                new=AsyncMock(side_effect=[first, retry]),
            ) as mock_collect,
            patch("crawler.append_urls") as mock_append,
        ):
            result = await crawler.crawl_category(
                browser=browser,
                site=crawler.SITES["carousell"],
                cfg=cfg,
                target=3,
                global_seen=set(),
                output_path=MagicMock(),
                delay_ms=0,
                max_rounds=10,
            )

        self.assertEqual(mock_collect.await_count, 2)
        self.assertIs(mock_collect.await_args_list[0].kwargs["page"], initial_page)
        self.assertIs(mock_collect.await_args_list[1].kwargs["page"], retry_page)
        self.assertEqual(mock_collect.await_args_list[0].kwargs["quota"], 3)
        self.assertEqual(mock_collect.await_args_list[1].kwargs["quota"], 2)
        self.assertEqual(mock_collect.await_args_list[0].kwargs["collected_before"], 0)
        self.assertEqual(mock_collect.await_args_list[1].kwargs["collected_before"], 1)
        initial_page.close.assert_awaited_once_with()
        retry_page.close.assert_awaited_once_with()
        self.assertEqual(result["seed_pages_used"], 2)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["error"], crawler.PAGINATION_STAGNATED_ERROR)
        self.assertEqual(result["pagination_rounds"], 9)
        self.assertEqual(result["last_raw_url_count"], 13)
        self.assertEqual(result["last_new_url_count"], 1)
        self.assertEqual(result["stop_reason"], "pagination_stagnated")
        self.assertEqual(result["duplicates_skipped"], 5)
        self.assertEqual(result["collected"], 2)
        self.assertEqual(result["remaining"], 1)
        self.assertEqual(
            set(result),
            {
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
            },
        )
        self.assertEqual(
            mock_append.call_args_list,
            [
                call(
                    unittest.mock.ANY,
                    "Carousell",
                    "Phones",
                    ["https://example.test/p/one"],
                ),
                call(
                    unittest.mock.ANY,
                    "Carousell",
                    "Phones",
                    ["https://example.test/p/two"],
                ),
            ],
        )
        context.close.assert_awaited_once_with()


class RunStateLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_starting_state_precedes_csv_reset_and_running_state_follows_it(self):
        args = Namespace(
            site="carousell",
            mode="full",
            config=".tmp/run-state-config.csv",
            output=".tmp/run-state-urls.csv",
            summary=".tmp/run-state-summary.csv",
            headed=True,
            browser_executable=None,
            delay_ms=0,
            max_rounds=1,
        )
        config = crawler.CategoryConfig(
            category="Phones",
            soft_target=1,
            full_target=1,
            seed_urls=("https://example.test/phones",),
        )
        events = []
        state_snapshots = []

        def record_state(path, state):
            events.append(f"state:{state['status']}")
            state_snapshots.append((path, dict(state)))

        def load_config(path):
            events.append("load_config")
            return [config]

        def init_output(path):
            events.append("init_output")

        def write_summary(path, rows):
            events.append("write_summary")

        playwright_manager = MagicMock()
        playwright_manager.__aenter__ = AsyncMock(
            side_effect=RuntimeError("playwright unavailable")
        )
        playwright_manager.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("crawler.uuid.uuid4", return_value="run-state-id"),
            patch("crawler.time.time", side_effect=[100.0, 101.0]),
            patch("crawler.write_run_state", side_effect=record_state),
            patch("crawler.load_config", side_effect=load_config),
            patch("crawler.init_output", side_effect=init_output),
            patch("crawler.write_summary", side_effect=write_summary),
            patch("crawler.async_playwright", return_value=playwright_manager),
            self.assertRaisesRegex(RuntimeError, "playwright unavailable"),
        ):
            await crawler.run(args)

        self.assertEqual(
            events,
            [
                "state:starting",
                "load_config",
                "state:starting",
                "init_output",
                "write_summary",
                "state:running",
                "state:fatal",
            ],
        )
        self.assertIsNone(state_snapshots[0][1]["expected_total"])
        self.assertEqual(state_snapshots[1][1]["expected_total"], 1)
        self.assertEqual(state_snapshots[2][1]["status"], "running")
        self.assertEqual(state_snapshots[-1][1]["status"], "fatal")
        self.assertEqual(state_snapshots[-1][1]["exit_code"], 1)
        self.assertIn("playwright unavailable", state_snapshots[-1][1]["error"])
        self.assertEqual(
            state_snapshots[0][0],
            crawler.default_state_path(Path(args.summary).resolve()),
        )


if __name__ == "__main__":
    unittest.main()
