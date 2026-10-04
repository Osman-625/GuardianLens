import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import monitor_progress


class MonitorCsvTests(unittest.TestCase):
    def test_load_categories_selects_requested_mode_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "categories.csv"
            config_path.write_text(
                "category,soft_target,full_target,seed_urls\n"
                " Phones ,9,90,https://example.test/phones\n"
                "Tablets,6,60,https://example.test/tablets\n",
                encoding="utf-8",
            )

            self.assertEqual(
                monitor_progress.load_categories(config_path, "soft"),
                [("Phones", 9), ("Tablets", 6)],
            )
            self.assertEqual(
                monitor_progress.load_categories(config_path, "full"),
                [("Phones", 90), ("Tablets", 60)],
            )

    def test_load_summary_and_count_urls_read_stable_snapshots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary_path = root / "summary.csv"
            output_path = root / "urls.csv"
            summary_path.write_text(
                "category,target,collected,status,error\n"
                "Phones,90,90,complete,\n"
                "Tablets,60,42,partial,pagination_stagnated_no_new_urls\n",
                encoding="utf-8",
            )
            with output_path.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(
                    output,
                    fieldnames=["app", "category", "product_url"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "app": "Carousell",
                        "category": "Phones",
                        "product_url": "https://example.test/p/phone-1/",
                    }
                )
                writer.writerow(
                    {"app": "Carousell", "category": "Phones", "product_url": ""}
                )

            summary = monitor_progress.load_summary(summary_path)

            self.assertEqual(summary["Phones"]["status"], "complete")
            self.assertEqual(summary["Tablets"]["collected"], "42")
            self.assertEqual(monitor_progress.count_urls(output_path), 1)

    def test_missing_snapshots_are_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.csv"

            self.assertEqual(monitor_progress.load_summary(missing), {})
            self.assertEqual(monitor_progress.count_urls(missing), 0)

    def test_count_urls_rejects_an_unexpected_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "urls.csv"
            output_path.write_text(
                "category,product_url\nPhones,https://example.test/p/phone-1/\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Unexpected URL CSV columns"):
                monitor_progress.count_urls(output_path)


class MonitorRunStateTests(unittest.TestCase):
    def test_load_run_state_handles_missing_valid_and_non_object_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "summary.csv.state.json"

            self.assertIsNone(monitor_progress.load_run_state(state_path))

            expected = {"run_id": "run-1", "status": "running"}
            state_path.write_text(json.dumps(expected), encoding="utf-8")
            self.assertEqual(monitor_progress.load_run_state(state_path), expected)

            state_path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Run state must be a JSON object"):
                monitor_progress.load_run_state(state_path)

    def test_state_matches_run_requires_site_mode_and_all_resolved_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.csv"
            output_path = root / "urls.csv"
            summary_path = root / "summary.csv"
            matching = {
                "site": "carousell",
                "mode": "full",
                "config_path": str(config_path),
                "output_path": str(output_path),
                "summary_path": str(summary_path),
            }

            self.assertTrue(
                monitor_progress.state_matches_run(
                    matching,
                    site="carousell",
                    mode="full",
                    config_path=config_path,
                    output_path=output_path,
                    summary_path=summary_path,
                )
            )

            for key, value in (
                ("site", "mudah"),
                ("mode", "soft"),
                ("config_path", str(root / "other-config.csv")),
                ("output_path", str(root / "other-urls.csv")),
                ("summary_path", str(root / "other-summary.csv")),
            ):
                mismatched = {**matching, key: value}
                with self.subTest(key=key):
                    self.assertFalse(
                        monitor_progress.state_matches_run(
                            mismatched,
                            site="carousell",
                            mode="full",
                            config_path=config_path,
                            output_path=output_path,
                            summary_path=summary_path,
                        )
                    )

            self.assertFalse(
                monitor_progress.state_matches_run(
                    {"site": "carousell", "mode": "full"},
                    site="carousell",
                    mode="full",
                    config_path=config_path,
                    output_path=output_path,
                    summary_path=summary_path,
                )
            )


class MonitorRenderTests(unittest.TestCase):
    def test_render_shows_pending_partial_error_and_exact_total(self):
        rendered = monitor_progress.render(
            site="carousell",
            categories=[("Phones", 90), ("Tablets", 60), ("Fashion", 50)],
            summary={
                "Phones": {"collected": "90", "status": "complete", "error": ""},
                "Tablets": {
                    "collected": "42",
                    "status": "partial",
                    "error": "pagination_stagnated_no_new_urls",
                },
            },
            total_urls=132,
            expected_total=200,
            elapsed=12.4,
            interval=5,
        )

        self.assertIn("carousell crawl progress", rendered)
        self.assertIn("Phones", rendered)
        self.assertIn("complete", rendered)
        self.assertIn("Tablets", rendered)
        self.assertIn("pagination_stagnated_no_new_urls", rendered)
        self.assertIn("Fashion", rendered)
        self.assertIn("pending", rendered)
        self.assertIn("TOTAL: 132/200 URLs collected (66.0%)", rendered)
        self.assertIn("Some categories reported errors", rendered)


class MonitorMainTests(unittest.TestCase):
    @staticmethod
    def _state(run_id, status):
        return {
            "run_id": run_id,
            "site": "carousell",
            "mode": "full",
            "config_path": str(monitor_progress.DEFAULT_CONFIGS["carousell"].resolve()),
            "output_path": str(
                (monitor_progress.OUTPUT_DIR / "carousell_urls_full.csv").resolve()
            ),
            "summary_path": str(
                (monitor_progress.OUTPUT_DIR / "carousell_summary_full.csv").resolve()
            ),
            "status": status,
        }

    def test_main_ignores_existing_terminal_run_and_adopts_new_run(self):
        argv = ["monitor_progress.py", "--site", "carousell", "--mode", "full"]
        old_terminal = self._state("old-run", "success")
        new_terminal = self._state("new-run", "success")
        with (
            patch.object(sys, "argv", argv),
            patch(
                "monitor_progress.load_categories",
                return_value=[("Phones", 2)],
            ),
            patch(
                "monitor_progress.load_summary",
                return_value={
                    "Phones": {
                        "collected": "2",
                        "status": "complete",
                        "error": "",
                    }
                },
            ),
            patch("monitor_progress.count_urls", return_value=2),
            patch(
                "monitor_progress.load_run_state",
                side_effect=[old_terminal, old_terminal, new_terminal],
            ) as mock_load_state,
            patch("monitor_progress.subprocess.run"),
            patch("monitor_progress.time.time", side_effect=[100.0, 101.0, 102.0]),
            patch("monitor_progress.time.sleep") as mock_sleep,
            patch("builtins.print") as mock_print,
        ):
            monitor_progress.main()

        self.assertEqual(mock_load_state.call_count, 3)
        mock_sleep.assert_called_once_with(5.0)
        messages = [str(args[0]) for args, _ in mock_print.call_args_list]
        self.assertTrue(
            any("Run complete: all category targets reached." in msg for msg in messages)
        )

    def test_main_adopts_starting_run_and_exits_only_for_same_run_terminal_state(self):
        argv = ["monitor_progress.py", "--site", "carousell", "--mode", "full"]
        starting = self._state("active-run", "starting")
        wrong_terminal = self._state("other-run", "success")
        running = self._state("active-run", "running")
        terminal = self._state("active-run", "shortfall")
        with (
            patch.object(sys, "argv", argv),
            patch(
                "monitor_progress.load_categories",
                return_value=[("Phones", 2)],
            ),
            patch(
                "monitor_progress.load_summary",
                return_value={
                    "Phones": {
                        "collected": "1",
                        "status": "partial",
                        "error": "pagination_stagnated_no_new_urls",
                    }
                },
            ) as mock_load_summary,
            patch("monitor_progress.count_urls", return_value=1) as mock_count_urls,
            patch(
                "monitor_progress.load_run_state",
                side_effect=[starting, starting, wrong_terminal, running, terminal],
            ),
            patch("monitor_progress.subprocess.run"),
            patch(
                "monitor_progress.time.time",
                side_effect=[100.0, 101.0, 102.0, 103.0, 104.0],
            ),
            patch("monitor_progress.time.sleep") as mock_sleep,
            patch("builtins.print") as mock_print,
        ):
            monitor_progress.main()

        self.assertEqual(mock_sleep.call_count, 3)
        self.assertEqual(mock_load_summary.call_count, 2)
        self.assertEqual(mock_count_urls.call_count, 2)
        messages = [str(args[0]) for args, _ in mock_print.call_args_list]
        self.assertTrue(any("Run finished with shortfalls" in msg for msg in messages))

    def test_main_reports_each_terminal_outcome(self):
        cases = (
            ("success", "", "Run complete: all category targets reached."),
            ("shortfall", "", "Run finished with shortfalls"),
            ("fatal", "browser crashed", "Run fatal: browser crashed"),
        )
        argv = ["monitor_progress.py", "--site", "carousell", "--mode", "full"]

        for status, error, expected_message in cases:
            with self.subTest(status=status):
                terminal = {**self._state(f"{status}-run", status), "error": error}
                with (
                    patch.object(sys, "argv", argv),
                    patch(
                        "monitor_progress.load_categories",
                        return_value=[("Phones", 2)],
                    ),
                    patch(
                        "monitor_progress.load_summary",
                        return_value={
                            "Phones": {
                                "collected": "2" if status == "success" else "1",
                                "status": "complete" if status == "success" else "partial",
                                "error": error,
                            }
                        },
                    ),
                    patch(
                        "monitor_progress.count_urls",
                        return_value=2 if status == "success" else 1,
                    ),
                    patch(
                        "monitor_progress.load_run_state",
                        side_effect=[None, terminal],
                    ),
                    patch("monitor_progress.subprocess.run"),
                    patch("monitor_progress.time.time", side_effect=[100.0, 101.0]),
                    patch("monitor_progress.time.sleep") as mock_sleep,
                    patch("builtins.print") as mock_print,
                ):
                    monitor_progress.main()

                mock_sleep.assert_not_called()
                messages = [
                    str(args[0]) for args, _ in mock_print.call_args_list
                ]
                self.assertTrue(
                    any(expected_message in message for message in messages),
                    messages,
                )


if __name__ == "__main__":
    unittest.main()
