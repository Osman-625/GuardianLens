from __future__ import annotations

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import validate_outputs


class ValidateOutputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.config_path = self.root / "categories.csv"
        self.url_path = self.root / "urls.csv"
        self.summary_path = self.root / "summary.csv"

    def write_config(
        self,
        rows: list[dict[str, str]] | None = None,
        fieldnames: tuple[str, ...] = validate_outputs.CONFIG_FIELDS,
    ) -> None:
        if rows is None:
            rows = [
                {
                    "category": "Phones",
                    "soft_target": "1",
                    "full_target": "2",
                    "seed_urls": "https://example.test/phones",
                },
                {
                    "category": "Audio",
                    "soft_target": "1",
                    "full_target": "1",
                    "seed_urls": "https://example.test/audio",
                },
            ]
        self.write_csv(self.config_path, fieldnames, rows)

    def write_urls(
        self,
        rows: list[dict[str, str]] | None = None,
        fieldnames: tuple[str, ...] = validate_outputs.URL_FIELDS,
    ) -> None:
        if rows is None:
            rows = [
                {
                    "app": "Carousell",
                    "category": "Phones",
                    "product_url": "https://www.carousell.com.my/p/phone-one-1001/",
                },
                {
                    "app": "Carousell",
                    "category": "Phones",
                    "product_url": "https://www.carousell.com.my/p/phone-two-1002/",
                },
                {
                    "app": "Carousell",
                    "category": "Audio",
                    "product_url": "https://www.carousell.com.my/p/speaker-1003/",
                },
            ]
        self.write_csv(self.url_path, fieldnames, rows)

    def write_summary(
        self,
        rows: list[dict[str, str]] | None = None,
        fieldnames: tuple[str, ...] = validate_outputs.SUMMARY_FIELDS,
    ) -> None:
        if rows is None:
            rows = [self.summary_row("Phones", 2), self.summary_row("Audio", 1)]
        self.write_csv(self.summary_path, fieldnames, rows)

    @staticmethod
    def summary_row(category: str, target: int) -> dict[str, str]:
        return {
            "category": category,
            "target": str(target),
            "collected": str(target),
            "remaining": "0",
            "duplicates_skipped": "3",
            "seed_pages_used": "1",
            "status": "complete",
            "error": "",
            "pagination_rounds": "2",
            "last_raw_url_count": "20",
            "last_new_url_count": "5",
            "stop_reason": "target_reached",
        }

    @staticmethod
    def write_csv(
        path: Path,
        fieldnames: tuple[str, ...],
        rows: list[dict[str, str]],
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def validate(self, site: str = "carousell") -> validate_outputs.ValidationReport:
        return validate_outputs.validate_outputs(
            site=site,
            mode="full",
            url_path=self.url_path,
            summary_path=self.summary_path,
            config_path=self.config_path,
        )

    def test_certifies_exact_complete_carousell_outputs(self) -> None:
        self.write_config()
        self.write_urls()
        self.write_summary()

        report = self.validate()

        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.expected_total, 3)
        self.assertEqual(report.actual_total, 3)
        self.assertEqual(report.category_counts, {"Phones": 2, "Audio": 1})

    def test_requires_exact_url_and_summary_schemas(self) -> None:
        self.write_config()
        self.write_urls(
            fieldnames=(*validate_outputs.URL_FIELDS, "unexpected"),
            rows=[
                {
                    "app": "Carousell",
                    "category": "Phones",
                    "product_url": "https://www.carousell.com.my/p/phone-one-1001/",
                    "unexpected": "value",
                }
            ],
        )
        self.write_summary(
            fieldnames=(
                "target",
                "category",
                *validate_outputs.SUMMARY_FIELDS[2:],
            )
        )

        report = self.validate()

        self.assertFalse(report.ok)
        errors = "\n".join(report.errors)
        self.assertIn("URL CSV schema must be exactly", errors)
        self.assertIn("summary CSV schema must be exactly", errors)

    def test_rejects_untrimmed_noncanonical_and_duplicate_listing_id_rows(self) -> None:
        self.write_config(
            rows=[
                {
                    "category": "Phones",
                    "soft_target": "1",
                    "full_target": "4",
                    "seed_urls": "https://example.test/phones",
                }
            ]
        )
        self.write_urls(
            rows=[
                {
                    "app": " Carousell",
                    "category": "Phones",
                    "product_url": "https://www.carousell.com.my/p/phone-one-1001/",
                },
                {
                    "app": "Carousell",
                    "category": " Phones",
                    "product_url": "https://www.carousell.com.my/p/phone-two-1002/",
                },
                {
                    "app": "Carousell",
                    "category": "Phones",
                    "product_url": "https://www.carousell.com.my/p/other-slug-1001/",
                },
                {
                    "app": "Carousell",
                    "category": "Phones",
                    "product_url": "https://www.carousell.com.my/p/phone-four-1004/?ref=x",
                },
            ]
        )
        self.write_summary(rows=[self.summary_row("Phones", 4)])

        report = self.validate()

        errors = "\n".join(report.errors)
        self.assertIn("app must be trimmed", errors)
        self.assertIn("category must be trimmed", errors)
        self.assertIn("not canonical for the site", errors)
        self.assertIn("duplicate listing ID '1001'", errors)

    def test_rejects_duplicate_product_url(self) -> None:
        self.write_config(
            rows=[
                {
                    "category": "Phones",
                    "soft_target": "1",
                    "full_target": "2",
                    "seed_urls": "https://example.test/phones",
                }
            ]
        )
        duplicate = {
            "app": "Carousell",
            "category": "Phones",
            "product_url": "https://www.carousell.com.my/p/phone-one-1001/",
        }
        self.write_urls(rows=[duplicate, duplicate])
        self.write_summary(rows=[self.summary_row("Phones", 2)])

        report = self.validate()

        self.assertIn("duplicate product_url", "\n".join(report.errors))

    def test_rejects_partial_summary_and_failed_reconciliation(self) -> None:
        self.write_config()
        self.write_urls()
        phones = self.summary_row("Phones", 2)
        phones.update(
            {
                "collected": "1",
                "remaining": "1",
                "status": "partial",
                "error": "pagination_stagnated_no_new_urls",
                "stop_reason": "pagination_stagnated",
            }
        )
        self.write_summary(rows=[phones, self.summary_row("Audio", 1)])

        report = self.validate()

        errors = "\n".join(report.errors)
        self.assertIn("status must be 'complete'", errors)
        self.assertIn("error must be blank", errors)
        self.assertIn("remaining must be 0", errors)
        self.assertIn("stop_reason must be 'target_reached'", errors)
        self.assertIn("collected=1 does not match 2 URL rows", errors)
        self.assertIn("summary collected total 2 does not match URL CSV total 3", errors)

    def test_rejects_wrong_per_category_count_even_when_total_is_correct(self) -> None:
        self.write_config()
        rows = [
            {
                "app": "Carousell",
                "category": "Phones",
                "product_url": f"https://www.carousell.com.my/p/phone-{number}/",
            }
            for number in (1001, 1002, 1003)
        ]
        self.write_urls(rows=rows)
        self.write_summary()

        report = self.validate()

        errors = "\n".join(report.errors)
        self.assertIn("category 'Phones' must contain 2 rows; found 3", errors)
        self.assertIn("category 'Audio' must contain 1 rows; found 0", errors)

    def test_uses_mudah_normalizer_and_trailing_id_contract(self) -> None:
        self.write_config(
            rows=[
                {
                    "category": "Phones",
                    "soft_target": "1",
                    "full_target": "1",
                    "seed_urls": "https://example.test/phones",
                }
            ]
        )
        self.write_urls(
            rows=[
                {
                    "app": "Mudah",
                    "category": "Phones",
                    "product_url": "https://www.mudah.my/iphone-black-115391385.htm",
                }
            ]
        )
        self.write_summary(rows=[self.summary_row("Phones", 1)])

        report = self.validate(site="mudah")

        self.assertTrue(report.ok, report.errors)

    def test_cli_supports_site_mode_and_optional_paths(self) -> None:
        self.write_config()
        self.write_urls()
        self.write_summary()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = validate_outputs.main(
                [
                    "--site",
                    "carousell",
                    "--mode",
                    "full",
                    "--output",
                    str(self.url_path),
                    "--summary",
                    str(self.summary_path),
                    "--config",
                    str(self.config_path),
                ]
            )

        self.assertEqual(exit_code, 0, stderr.getvalue())
        self.assertIn("CERTIFIED site=carousell mode=full records=3", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_returns_nonzero_for_invalid_output(self) -> None:
        self.write_config()
        self.write_urls(rows=[])
        self.write_summary()
        stderr = io.StringIO()

        with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            exit_code = validate_outputs.main(
                [
                    "carousell",
                    "full",
                    "--urls",
                    str(self.url_path),
                    "--summary-csv",
                    str(self.summary_path),
                    "--config",
                    str(self.config_path),
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("VALIDATION FAILED", stderr.getvalue())
        self.assertIn("URL CSV total must be 3", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
