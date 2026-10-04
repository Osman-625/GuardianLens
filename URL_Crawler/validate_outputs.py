from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from url_utils import normalize_listing_url, normalize_mudah_listing_url


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"

URL_FIELDS = ("app", "category", "product_url")
SUMMARY_FIELDS = (
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
)
CONFIG_FIELDS = ("category", "soft_target", "full_target", "seed_urls")
SUMMARY_INTEGER_FIELDS = (
    "target",
    "collected",
    "remaining",
    "duplicates_skipped",
    "seed_pages_used",
    "pagination_rounds",
    "last_raw_url_count",
    "last_new_url_count",
)


@dataclass(frozen=True)
class SiteRules:
    app_name: str
    config_path: Path
    normalize: Callable[[str | None], str | None]
    listing_id_pattern: re.Pattern[str]


SITE_RULES = {
    "carousell": SiteRules(
        app_name="Carousell",
        config_path=ROOT / "config" / "categories.csv",
        normalize=normalize_listing_url,
        listing_id_pattern=re.compile(r"-(\d+)/$"),
    ),
    "mudah": SiteRules(
        app_name="Mudah",
        config_path=ROOT / "config" / "categories_mudah.csv",
        normalize=normalize_mudah_listing_url,
        listing_id_pattern=re.compile(r"-(\d+)\.htm$"),
    ),
}


@dataclass(frozen=True)
class ValidationReport:
    site: str
    mode: str
    url_path: Path
    summary_path: Path
    expected_total: int
    actual_total: int
    category_counts: dict[str, int]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def default_url_path(site: str, mode: str) -> Path:
    return OUTPUT_DIR / f"{site}_urls_{mode}.csv"


def default_summary_path(site: str, mode: str) -> Path:
    return OUTPUT_DIR / f"{site}_summary_{mode}.csv"


def _read_targets(config_path: Path, mode: str) -> tuple[dict[str, int], list[str]]:
    errors: list[str] = []
    targets: dict[str, int] = {}
    target_field = f"{mode}_target"

    try:
        with config_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if tuple(reader.fieldnames or ()) != CONFIG_FIELDS:
                return {}, [
                    f"config schema must be exactly {list(CONFIG_FIELDS)!r}; "
                    f"found {reader.fieldnames!r}"
                ]

            for row_number, row in enumerate(reader, start=2):
                category_value = row.get("category")
                category = category_value.strip() if category_value is not None else ""
                if not category:
                    errors.append(f"config row {row_number}: category is blank")
                    continue
                if category_value != category:
                    errors.append(
                        f"config row {row_number}: category must be trimmed; "
                        f"found {category_value!r}"
                    )
                if category in targets:
                    errors.append(
                        f"config row {row_number}: duplicate category {category!r}"
                    )
                    continue

                raw_target = row.get(target_field)
                try:
                    target = int(raw_target or "")
                except (TypeError, ValueError):
                    errors.append(
                        f"config row {row_number}: {target_field} must be an integer; "
                        f"found {raw_target!r}"
                    )
                    continue
                if target <= 0:
                    errors.append(
                        f"config row {row_number}: {target_field} must be positive; "
                        f"found {target}"
                    )
                    continue
                targets[category] = target
    except (OSError, UnicodeError, csv.Error) as exc:
        errors.append(f"cannot read config {config_path}: {type(exc).__name__}: {exc}")

    if not targets and not errors:
        errors.append(f"config {config_path} contains no categories")
    return targets, errors


def _schema_error(label: str, expected: tuple[str, ...], actual: list[str] | None) -> str:
    return f"{label} schema must be exactly {list(expected)!r}; found {actual!r}"


def _read_url_csv(
    path: Path,
    rules: SiteRules,
    targets: dict[str, int],
) -> tuple[int, Counter[str], list[str]]:
    errors: list[str] = []
    category_counts: Counter[str] = Counter()
    seen_urls: dict[str, int] = {}
    seen_ids: dict[str, tuple[int, str]] = {}
    total_rows = 0

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if tuple(reader.fieldnames or ()) != URL_FIELDS:
                return 0, category_counts, [
                    _schema_error("URL CSV", URL_FIELDS, reader.fieldnames)
                ]

            for row_number, row in enumerate(reader, start=2):
                total_rows += 1
                if None in row:
                    errors.append(f"URL row {row_number}: contains extra CSV fields")

                app = row.get("app")
                category = row.get("category")
                product_url = row.get("product_url")

                for field, value in (
                    ("app", app),
                    ("category", category),
                    ("product_url", product_url),
                ):
                    if value is None or not value.strip():
                        errors.append(f"URL row {row_number}: {field} is blank")
                    elif value != value.strip():
                        errors.append(
                            f"URL row {row_number}: {field} must be trimmed; found {value!r}"
                        )

                if app is not None and app.strip() and app != rules.app_name:
                    errors.append(
                        f"URL row {row_number}: app must be {rules.app_name!r}; found {app!r}"
                    )

                if category is not None and category.strip():
                    category_counts[category] += 1
                    if category not in targets:
                        errors.append(
                            f"URL row {row_number}: unexpected category {category!r}"
                        )

                if product_url is None or not product_url.strip():
                    continue

                canonical = rules.normalize(product_url)
                if canonical != product_url:
                    errors.append(
                        f"URL row {row_number}: product_url is not canonical for the site; "
                        f"found {product_url!r}, normalizer returned {canonical!r}"
                    )

                previous_row = seen_urls.get(product_url)
                if previous_row is not None:
                    errors.append(
                        f"URL row {row_number}: duplicate product_url first seen at "
                        f"row {previous_row}: {product_url!r}"
                    )
                else:
                    seen_urls[product_url] = row_number

                id_match = rules.listing_id_pattern.search(product_url)
                if id_match is None:
                    errors.append(
                        f"URL row {row_number}: product_url has no trailing numeric listing ID: "
                        f"{product_url!r}"
                    )
                    continue

                listing_id = id_match.group(1)
                previous_identity = seen_ids.get(listing_id)
                if previous_identity is not None:
                    previous_id_row, previous_url = previous_identity
                    if previous_url != product_url:
                        errors.append(
                            f"URL row {row_number}: duplicate listing ID {listing_id!r} "
                            f"first seen at row {previous_id_row}: {previous_url!r}"
                        )
                else:
                    seen_ids[listing_id] = (row_number, product_url)
    except (OSError, UnicodeError, csv.Error) as exc:
        errors.append(f"cannot read URL CSV {path}: {type(exc).__name__}: {exc}")

    return total_rows, category_counts, errors


def _parse_summary_integer(
    row: dict[str | None, str | list[str] | None],
    row_number: int,
    field: str,
    errors: list[str],
) -> int | None:
    raw_value = row.get(field)
    if not isinstance(raw_value, str):
        errors.append(f"summary row {row_number}: {field} is blank")
        return None
    if raw_value != raw_value.strip() or not raw_value:
        errors.append(
            f"summary row {row_number}: {field} must be a trimmed integer; "
            f"found {raw_value!r}"
        )
        return None
    try:
        value = int(raw_value)
    except ValueError:
        errors.append(
            f"summary row {row_number}: {field} must be an integer; found {raw_value!r}"
        )
        return None
    if value < 0:
        errors.append(
            f"summary row {row_number}: {field} must be non-negative; found {value}"
        )
        return None
    return value


def _read_summary_csv(
    path: Path,
    targets: dict[str, int],
    url_category_counts: Counter[str],
) -> tuple[dict[str, dict[str, int]], list[str]]:
    errors: list[str] = []
    summaries: dict[str, dict[str, int]] = {}

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if tuple(reader.fieldnames or ()) != SUMMARY_FIELDS:
                return {}, [
                    _schema_error("summary CSV", SUMMARY_FIELDS, reader.fieldnames)
                ]

            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    errors.append(f"summary row {row_number}: contains extra CSV fields")

                raw_category = row.get("category")
                category = raw_category if isinstance(raw_category, str) else ""
                if not category.strip():
                    errors.append(f"summary row {row_number}: category is blank")
                    continue
                if category != category.strip():
                    errors.append(
                        f"summary row {row_number}: category must be trimmed; "
                        f"found {category!r}"
                    )
                if category not in targets:
                    errors.append(
                        f"summary row {row_number}: unexpected category {category!r}"
                    )
                if category in summaries:
                    errors.append(
                        f"summary row {row_number}: duplicate category {category!r}"
                    )
                    continue

                integers: dict[str, int] = {}
                for field in SUMMARY_INTEGER_FIELDS:
                    value = _parse_summary_integer(row, row_number, field, errors)
                    if value is not None:
                        integers[field] = value
                summaries[category] = integers

                status = row.get("status")
                error = row.get("error")
                stop_reason = row.get("stop_reason")
                if status != "complete":
                    errors.append(
                        f"summary row {row_number} ({category}): status must be "
                        f"'complete'; found {status!r}"
                    )
                if error != "":
                    errors.append(
                        f"summary row {row_number} ({category}): error must be blank; "
                        f"found {error!r}"
                    )
                if stop_reason != "target_reached":
                    errors.append(
                        f"summary row {row_number} ({category}): stop_reason must be "
                        f"'target_reached'; found {stop_reason!r}"
                    )

                target = integers.get("target")
                collected = integers.get("collected")
                remaining = integers.get("remaining")
                expected_target = targets.get(category)
                actual_category_count = url_category_counts.get(category, 0)

                if expected_target is not None and target != expected_target:
                    errors.append(
                        f"summary row {row_number} ({category}): target must be "
                        f"{expected_target}; found {target!r}"
                    )
                if expected_target is not None and collected != expected_target:
                    errors.append(
                        f"summary row {row_number} ({category}): collected must be "
                        f"{expected_target}; found {collected!r}"
                    )
                if remaining != 0:
                    errors.append(
                        f"summary row {row_number} ({category}): remaining must be 0; "
                        f"found {remaining!r}"
                    )
                if target is not None and collected is not None and remaining is not None:
                    if remaining != max(0, target - collected):
                        errors.append(
                            f"summary row {row_number} ({category}): remaining does not "
                            f"reconcile with target-collected"
                        )
                if collected is not None and collected != actual_category_count:
                    errors.append(
                        f"summary row {row_number} ({category}): collected={collected} "
                        f"does not match {actual_category_count} URL rows"
                    )
    except (OSError, UnicodeError, csv.Error) as exc:
        errors.append(f"cannot read summary CSV {path}: {type(exc).__name__}: {exc}")

    missing_categories = [category for category in targets if category not in summaries]
    if missing_categories:
        errors.append(f"summary CSV is missing categories: {missing_categories!r}")

    return summaries, errors


def validate_outputs(
    site: str,
    mode: str,
    url_path: str | Path | None = None,
    summary_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> ValidationReport:
    if site not in SITE_RULES:
        raise ValueError(f"site must be one of {sorted(SITE_RULES)!r}; found {site!r}")
    if mode not in ("soft", "full"):
        raise ValueError(f"mode must be 'soft' or 'full'; found {mode!r}")

    rules = SITE_RULES[site]
    resolved_url_path = Path(url_path) if url_path is not None else default_url_path(site, mode)
    resolved_summary_path = (
        Path(summary_path)
        if summary_path is not None
        else default_summary_path(site, mode)
    )
    resolved_config_path = Path(config_path) if config_path is not None else rules.config_path

    targets, config_errors = _read_targets(resolved_config_path, mode)
    expected_total = sum(targets.values())
    total_rows, category_counts, url_errors = _read_url_csv(
        resolved_url_path,
        rules,
        targets,
    )

    errors = [*config_errors, *url_errors]
    if total_rows != expected_total:
        errors.append(
            f"URL CSV total must be {expected_total} from config; found {total_rows}"
        )
    for category, target in targets.items():
        actual = category_counts.get(category, 0)
        if actual != target:
            errors.append(
                f"URL CSV category {category!r} must contain {target} rows; found {actual}"
            )

    summaries, summary_errors = _read_summary_csv(
        resolved_summary_path,
        targets,
        category_counts,
    )
    errors.extend(summary_errors)

    if summaries:
        summary_target_total = sum(
            values.get("target", 0) for values in summaries.values()
        )
        summary_collected_total = sum(
            values.get("collected", 0) for values in summaries.values()
        )
        if summary_target_total != expected_total:
            errors.append(
                f"summary target total must be {expected_total}; found {summary_target_total}"
            )
        if summary_collected_total != total_rows:
            errors.append(
                f"summary collected total {summary_collected_total} does not match "
                f"URL CSV total {total_rows}"
            )

    return ValidationReport(
        site=site,
        mode=mode,
        url_path=resolved_url_path.resolve(),
        summary_path=resolved_summary_path.resolve(),
        expected_total=expected_total,
        actual_total=total_rows,
        category_counts=dict(category_counts),
        errors=tuple(errors),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Strictly certify a completed crawler URL CSV and summary CSV."
    )
    parser.add_argument("site_pos", nargs="?", choices=sorted(SITE_RULES), help=argparse.SUPPRESS)
    parser.add_argument("mode_pos", nargs="?", choices=("soft", "full"), help=argparse.SUPPRESS)
    parser.add_argument("--site", choices=sorted(SITE_RULES))
    parser.add_argument("--mode", choices=("soft", "full"))
    parser.add_argument(
        "--urls",
        "--output",
        "--url-csv",
        dest="url_path",
        help="URL CSV path; defaults to output/<site>_urls_<mode>.csv.",
    )
    parser.add_argument(
        "--summary",
        "--summary-csv",
        dest="summary_path",
        help="Summary CSV path; defaults to output/<site>_summary_<mode>.csv.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        help="Optional category config override (primarily for isolated validation runs).",
    )
    return parser


def _resolve_cli_choice(
    parser: argparse.ArgumentParser,
    name: str,
    flag_value: str | None,
    positional_value: str | None,
) -> str:
    if flag_value and positional_value and flag_value != positional_value:
        parser.error(
            f"conflicting {name} values: positional {positional_value!r} and "
            f"--{name} {flag_value!r}"
        )
    value = flag_value or positional_value
    if value is None:
        parser.error(f"{name} is required (pass --{name} or the positional value)")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    site = _resolve_cli_choice(parser, "site", args.site, args.site_pos)
    mode = _resolve_cli_choice(parser, "mode", args.mode, args.mode_pos)

    report = validate_outputs(
        site=site,
        mode=mode,
        url_path=args.url_path,
        summary_path=args.summary_path,
        config_path=args.config_path,
    )
    if not report.ok:
        print(
            f"VALIDATION FAILED site={site} mode={mode} "
            f"errors={len(report.errors)}",
            file=sys.stderr,
        )
        for error in report.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        f"CERTIFIED site={site} mode={mode} records={report.actual_total} "
        f"categories={len(report.category_counts)}"
    )
    print(f"URL CSV: {report.url_path}")
    print(f"Summary CSV: {report.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
