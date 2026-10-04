from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
DEFAULT_CONFIGS = {
    "carousell": ROOT / "config" / "categories.csv",
    "mudah": ROOT / "config" / "categories_mudah.csv",
}
TERMINAL_RUN_STATUSES = {"success", "shortfall", "fatal", "interrupted"}


def load_categories(config_path: Path, mode: str) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    with config_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            target = int(row["soft_target"]) if mode == "soft" else int(row["full_target"])
            rows.append((row["category"].strip(), target))
    return rows


def load_summary(summary_path: Path) -> dict[str, dict[str, str]]:
    if not summary_path.exists():
        return {}
    with summary_path.open("r", encoding="utf-8", newline="") as f:
        return {row["category"]: row for row in csv.DictReader(f)}


def count_urls(output_path: Path) -> int:
    if not output_path.exists():
        return 0
    with output_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["app", "category", "product_url"]:
            raise ValueError(f"Unexpected URL CSV columns: {reader.fieldnames}")
        return sum(1 for row in reader if row.get("product_url"))


def load_run_state(state_path: Path) -> dict[str, object] | None:
    if not state_path.exists():
        return None
    with state_path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    if not isinstance(state, dict):
        raise ValueError("Run state must be a JSON object")
    return state


def state_matches_run(
    state: dict[str, object] | None,
    *,
    site: str,
    mode: str,
    config_path: Path,
    output_path: Path,
    summary_path: Path,
) -> bool:
    if state is None or state.get("site") != site or state.get("mode") != mode:
        return False
    expected_paths = {
        "config_path": config_path.resolve(),
        "output_path": output_path.resolve(),
        "summary_path": summary_path.resolve(),
    }
    try:
        return all(
            Path(str(state[key])).resolve() == expected
            for key, expected in expected_paths.items()
        )
    except (KeyError, OSError, TypeError, ValueError):
        return False


def render(site: str, categories: list[tuple[str, int]], summary: dict[str, dict[str, str]], total_urls: int, expected_total: int, elapsed: float, interval: float) -> str:
    lines = []
    lines.append(
        f"{site} crawl progress  |  elapsed {elapsed:6.0f}s  |  "
        f"refreshes every {interval:g}s  |  Ctrl+C to stop watching"
    )
    lines.append("-" * 78)
    lines.append(f"{'Category':<18}{'Target':>8}{'Collected':>11}{'Status':>12}  Error")
    lines.append("-" * 78)

    any_error = False
    for category, target in categories:
        row = summary.get(category)
        if row is None:
            lines.append(f"{category:<18}{target:>8}{'-':>11}{'pending':>12}")
            continue
        status = row["status"]
        collected = row["collected"]
        error = row.get("error") or ""
        marker = status
        if status in ("failed", "partial") and error:
            any_error = True
        lines.append(f"{category:<18}{target:>8}{collected:>11}{marker:>12}  {error[:60]}")

    lines.append("-" * 78)
    pct = (total_urls / expected_total * 100) if expected_total else 0
    lines.append(f"TOTAL: {total_urls}/{expected_total} URLs collected ({pct:.1f}%)")
    if any_error:
        lines.append("Some categories reported errors — see the Error column above.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live-watch a running crawl.")
    parser.add_argument("--site", choices=tuple(DEFAULT_CONFIGS.keys()), default="carousell")
    parser.add_argument("--mode", choices=("soft", "full"), default="full")
    parser.add_argument("--config", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    config_path = Path(args.config).resolve() if args.config else DEFAULT_CONFIGS[args.site]
    output_path = Path(args.output).resolve() if args.output else OUTPUT_DIR / f"{args.site}_urls_{args.mode}.csv"
    summary_path = Path(args.summary).resolve() if args.summary else OUTPUT_DIR / f"{args.site}_summary_{args.mode}.csv"
    state_path = Path(f"{summary_path}.state.json")

    categories = load_categories(config_path, args.mode)
    expected_total = sum(t for _, t in categories)
    start = time.time()
    summary: dict[str, dict[str, str]] = {}
    total_urls = 0
    adopted_run_id: str | None = None
    ignored_run_id: str | None = None

    try:
        initial_state = load_run_state(state_path)
    except (OSError, json.JSONDecodeError, ValueError):
        initial_state = None
    if state_matches_run(
        initial_state,
        site=args.site,
        mode=args.mode,
        config_path=config_path,
        output_path=output_path,
        summary_path=summary_path,
    ):
        initial_run_id = str(initial_state.get("run_id") or "")
        if initial_state.get("status") in ("starting", "running"):
            adopted_run_id = initial_run_id
        elif initial_state.get("status") in TERMINAL_RUN_STATUSES:
            ignored_run_id = initial_run_id

    try:
        while True:
            active_state: dict[str, object] | None = None
            try:
                candidate = load_run_state(state_path)
                if state_matches_run(
                    candidate,
                    site=args.site,
                    mode=args.mode,
                    config_path=config_path,
                    output_path=output_path,
                    summary_path=summary_path,
                ):
                    candidate_run_id = str(candidate.get("run_id") or "")
                    if adopted_run_id is None and candidate_run_id != ignored_run_id:
                        adopted_run_id = candidate_run_id
                        summary = {}
                        total_urls = 0
                    if candidate_run_id == adopted_run_id:
                        active_state = candidate

                if active_state and active_state.get("status") != "starting":
                    summary = load_summary(summary_path)
                    total_urls = count_urls(output_path)
            except (OSError, csv.Error, json.JSONDecodeError, KeyError, ValueError) as exc:
                print(f"Waiting for a stable run snapshot: {type(exc).__name__}: {exc}")
            elapsed = time.time() - start
            subprocess.run(["cmd", "/c", "cls"] if os.name == "nt" else ["clear"], check=False)
            print(
                render(
                    args.site,
                    categories,
                    summary,
                    total_urls,
                    expected_total,
                    elapsed,
                    args.interval,
                )
            )
            if active_state and active_state.get("status") in TERMINAL_RUN_STATUSES:
                status = str(active_state["status"])
                if status == "success":
                    print("\nRun complete: all category targets reached.")
                elif status == "shortfall":
                    print("\nRun finished with shortfalls; see the rows above.")
                else:
                    error = str(active_state.get("error") or "unknown error")
                    print(f"\nRun {status}: {error}")
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped watching (the crawl itself keeps running).")


if __name__ == "__main__":
    main()
