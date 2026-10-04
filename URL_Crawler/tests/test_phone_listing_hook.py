import unittest
from unittest.mock import AsyncMock, MagicMock, call, patch

import crawler


class TrySelectAllPhoneListingsTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def make_page_without_listing_links():
        page = MagicMock()
        listing_links = MagicMock()
        listing_links.count = AsyncMock(return_value=0)
        listing_links.first.wait_for = AsyncMock()
        page.locator.return_value = listing_links
        page.wait_for_timeout = AsyncMock()
        return page, listing_links

    async def test_returns_early_when_phone_listing_links_are_already_present(self):
        page = MagicMock()
        listing_links = MagicMock()
        listing_links.count = AsyncMock(return_value=4)
        page.locator.return_value = listing_links

        with patch("builtins.print") as mock_print:
            result = await crawler.try_select_all_phone_listings(page, "Phones")

        self.assertIsNone(result)
        page.locator.assert_called_once_with('a[href*="/p/"]')
        page.get_by_role.assert_not_called()
        mock_print.assert_called_once_with(
            "    phone_all_tab outcome=already_all exception=''"
        )

    async def test_retries_exact_all_button_then_waits_for_listing_links(self):
        page, listing_links = self.make_page_without_listing_links()
        locator = MagicMock()
        locator.first.wait_for = AsyncMock(
            side_effect=[
                RuntimeError("first lookup failed"),
                RuntimeError("second lookup failed"),
                None,
            ]
        )
        locator.count = AsyncMock(return_value=1)
        button = MagicMock()
        button.is_visible = AsyncMock(return_value=True)
        button.click = AsyncMock()
        locator.nth.return_value = button
        page.get_by_role.return_value = locator

        with (
            patch("crawler.prepare_for_click", new=AsyncMock()) as prepare,
            patch("crawler.jittered_delay_ms", return_value=700),
            patch("builtins.print") as mock_print,
        ):
            await crawler.try_select_all_phone_listings(page, "Phones")

        self.assertEqual(
            page.get_by_role.call_args_list,
            [call("button", name="All", exact=True)] * 3,
        )
        self.assertEqual(locator.first.wait_for.await_count, 3)
        locator.first.wait_for.assert_awaited_with(state="visible", timeout=8000)
        locator.nth.assert_called_once_with(0)
        prepare.assert_awaited_once_with(page, button, 900)
        button.click.assert_awaited_once_with(timeout=3500)
        listing_links.first.wait_for.assert_awaited_once_with(
            state="attached", timeout=10000
        )
        self.assertEqual(page.wait_for_timeout.await_args_list, [call(700), call(700)])

        messages = [args[0] for args, _ in mock_print.call_args_list]
        self.assertEqual(len(messages), 3)
        self.assertIn("attempt=1 outcome=retry", messages[0])
        self.assertIn("attempt=2 outcome=retry", messages[1])
        self.assertEqual(
            messages[2],
            "    phone_all_tab attempt=3 outcome=switched_to_all exception=''",
        )

    async def test_raises_after_three_exact_all_attempts_are_exhausted(self):
        page, listing_links = self.make_page_without_listing_links()
        locator = MagicMock()
        locator.first.wait_for = AsyncMock()
        locator.count = AsyncMock(return_value=0)
        page.get_by_role.return_value = locator

        with (
            patch("crawler.prepare_for_click", new=AsyncMock()) as prepare,
            patch("crawler.jittered_delay_ms", return_value=650),
            patch("builtins.print") as mock_print,
            self.assertRaisesRegex(
                RuntimeError,
                "phone_all_tab_failed_after_3_attempts: RuntimeError: "
                "All button was not visible",
            ),
        ):
            await crawler.try_select_all_phone_listings(page, "Phones")

        self.assertEqual(
            page.get_by_role.call_args_list,
            [call("button", name="All", exact=True)] * 3,
        )
        self.assertEqual(locator.first.wait_for.await_count, 3)
        self.assertEqual(locator.count.await_count, 3)
        locator.nth.assert_not_called()
        prepare.assert_not_awaited()
        listing_links.first.wait_for.assert_not_awaited()
        self.assertEqual(
            page.wait_for_timeout.await_args_list,
            [call(650), call(650), call(650)],
        )
        messages = [args[0] for args, _ in mock_print.call_args_list]
        self.assertEqual(len(messages), 3)
        self.assertTrue(all("outcome=retry" in message for message in messages))

    async def test_ignores_non_phone_categories(self):
        page = MagicMock()

        result = await crawler.try_select_all_phone_listings(page, "Laptops")

        self.assertIsNone(result)
        page.locator.assert_not_called()
        page.get_by_role.assert_not_called()


if __name__ == "__main__":
    unittest.main()
