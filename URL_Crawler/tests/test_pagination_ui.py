import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, call, patch

import crawler


class DismissPageOverlaysTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def make_page(dialog, close_buttons):
        page = MagicMock()
        page.locator.side_effect = lambda selector: (
            dialog if selector == '[role="dialog"]' else close_buttons
        )
        page.wait_for_timeout = AsyncMock()
        page.keyboard.press = AsyncMock()
        return page

    async def test_clicks_first_visible_dialog_close_button(self):
        dialog = MagicMock()
        dialog.count = AsyncMock(return_value=1)
        visible_dialog = MagicMock()
        visible_dialog.is_visible = AsyncMock(return_value=True)
        visible_dialog.wait_for = AsyncMock()
        dialog.nth.return_value = visible_dialog
        close_buttons = MagicMock()
        close_buttons.count = AsyncMock(return_value=2)
        hidden = MagicMock()
        hidden.is_visible = AsyncMock(return_value=False)
        visible = MagicMock()
        visible.is_visible = AsyncMock(return_value=True)
        visible.click = AsyncMock()
        close_buttons.nth.side_effect = [hidden, visible]
        page = self.make_page(dialog, close_buttons)

        with (
            patch("crawler.random.randint", return_value=200),
            patch("builtins.print") as mock_print,
        ):
            result = await crawler.dismiss_page_overlays(
                page, crawler.SITES["carousell"]
            )

        self.assertTrue(result)
        self.assertEqual(close_buttons.nth.call_args_list, [call(0), call(1)])
        visible.click.assert_awaited_once_with(timeout=2500)
        visible_dialog.wait_for.assert_awaited_once_with(
            state="hidden", timeout=3500
        )
        page.keyboard.press.assert_not_awaited()
        mock_print.assert_called_once_with(
            "      overlay selector='[role=\"dialog\"] button[aria-label=\"Close\"]' "
            "outcome=closed exception=''"
        )

    async def test_uses_escape_when_no_close_button_is_visible(self):
        dialog = MagicMock()
        dialog.count = AsyncMock(return_value=1)
        visible_dialog = MagicMock()
        visible_dialog.is_visible = AsyncMock(return_value=True)
        visible_dialog.wait_for = AsyncMock()
        dialog.nth.return_value = visible_dialog
        close_buttons = MagicMock()
        close_buttons.count = AsyncMock(return_value=1)
        hidden = MagicMock()
        hidden.is_visible = AsyncMock(return_value=False)
        close_buttons.nth.return_value = hidden
        page = self.make_page(dialog, close_buttons)

        with patch("builtins.print") as mock_print:
            result = await crawler.dismiss_page_overlays(
                page, crawler.SITES["carousell"]
            )

        self.assertTrue(result)
        page.keyboard.press.assert_awaited_once_with("Escape")
        visible_dialog.wait_for.assert_awaited_once_with(
            state="hidden", timeout=3500
        )
        mock_print.assert_called_once_with(
            "      overlay selector='Escape' outcome=closed exception=''"
        )

    async def test_uses_escape_when_close_button_click_fails(self):
        dialog = MagicMock()
        dialog.count = AsyncMock(return_value=1)
        visible_dialog = MagicMock()
        visible_dialog.is_visible = AsyncMock(return_value=True)
        visible_dialog.wait_for = AsyncMock()
        dialog.nth.return_value = visible_dialog
        close_buttons = MagicMock()
        close_buttons.count = AsyncMock(return_value=1)
        close_button = MagicMock()
        close_button.is_visible = AsyncMock(return_value=True)
        close_button.click = AsyncMock(side_effect=RuntimeError("click intercepted"))
        close_buttons.nth.return_value = close_button
        page = self.make_page(dialog, close_buttons)

        with (
            patch("crawler.random.randint", return_value=200),
            patch("builtins.print") as mock_print,
        ):
            result = await crawler.dismiss_page_overlays(
                page, crawler.SITES["carousell"]
            )

        self.assertTrue(result)
        page.keyboard.press.assert_awaited_once_with("Escape")
        visible_dialog.wait_for.assert_awaited_once_with(
            state="hidden", timeout=3500
        )
        messages = [args[0] for args, _ in mock_print.call_args_list]
        self.assertIn("outcome=close_button_failed", messages[0])
        self.assertIn("RuntimeError: click intercepted", messages[0])
        self.assertEqual(
            messages[1],
            "      overlay selector='Escape' outcome=closed exception=''",
        )


class TryShowMoreInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_clicks_a_visible_later_match(self):
        site = replace(
            crawler.SITES["carousell"], show_more_selectors=("show-more",)
        )
        page = MagicMock()
        matches = MagicMock()
        matches.count = AsyncMock(return_value=2)
        hidden = MagicMock()
        hidden.is_visible = AsyncMock(return_value=False)
        visible = MagicMock()
        visible.is_visible = AsyncMock(return_value=True)
        visible.click = AsyncMock()
        matches.nth.side_effect = [hidden, visible]
        page.locator.return_value = matches

        with (
            patch("crawler.prepare_for_click", new=AsyncMock()) as prepare,
            patch("builtins.print"),
        ):
            result = await crawler.try_show_more(page, site, delay_ms=500)

        self.assertTrue(result.clicked)
        self.assertEqual(result.selector, "show-more")
        self.assertEqual(result.attempts[0].outcome, "clicked")
        self.assertEqual(matches.nth.call_args_list, [call(0), call(1)])
        prepare.assert_awaited_once_with(page, visible, 500)
        visible.click.assert_awaited_once_with(timeout=2500)

    async def test_retries_click_after_dismissing_overlay(self):
        site = replace(
            crawler.SITES["carousell"], show_more_selectors=("show-more",)
        )
        page = MagicMock()
        matches = MagicMock()
        matches.count = AsyncMock(return_value=1)
        button = MagicMock()
        button.is_visible = AsyncMock(return_value=True)
        button.click = AsyncMock(
            side_effect=[RuntimeError("dialog intercepted click"), None]
        )
        matches.nth.return_value = button
        page.locator.return_value = matches

        with (
            patch("crawler.prepare_for_click", new=AsyncMock()) as prepare,
            patch(
                "crawler.dismiss_page_overlays", new=AsyncMock(return_value=True)
            ) as dismiss,
            patch("builtins.print"),
        ):
            result = await crawler.try_show_more(page, site, delay_ms=500)

        self.assertTrue(result.clicked)
        self.assertEqual(result.selector, "show-more")
        self.assertEqual(result.attempts[0].outcome, "clicked_after_overlay")
        self.assertEqual(prepare.await_args_list, [call(page, button, 500)] * 2)
        self.assertEqual(button.click.await_count, 2)
        dismiss.assert_awaited_once_with(page, site)


if __name__ == "__main__":
    unittest.main()
