"""Times real checks against a running API, for the NFR-02 evidence (a check within 10 seconds).

With the API running (and started, so its models are warm):

    python scripts/time_checks.py [--api http://localhost:8000] [--runs 10] [--photos 1]
                                  [--output docs/evidence/latency.json]

It submits `--runs` checks of a generated listing, waits for each result, and prints two times per
check: the server's own `total_latency_ms` and the wall-clock time the caller waited (upload,
scoring, and polling). The first check is listed apart, because any one-off cost left after
start-up lands there. A pause between checks keeps the run inside the per-session rate limit.
"""

from __future__ import annotations

import argparse
import io
import json
import statistics
import time
from pathlib import Path
from typing import Any

import httpx2
from PIL import Image

BUDGET_SECONDS = 10.0


def photo(index: int) -> bytes:
    """A small valid JPEG, a different colour for each index so the photos are not duplicates."""
    buffer = io.BytesIO()
    Image.new("RGB", (800, 800), (40 + 50 * index % 200, 90, 160)).save(buffer, format="JPEG")
    return buffer.getvalue()


def measure(client: httpx2.Client, runs: int, photos: int, pause: float) -> list[dict[str, float]]:
    """Submits `runs` checks and returns each one's server and wall-clock seconds."""
    results: list[dict[str, float]] = []
    form = {
        "platform": "carousell",
        "title": "Used laptop in good condition",
        "description": "Lenovo ThinkPad, 16GB RAM, 512GB SSD. Original charger included.",
        "price": "1250",
        "category": "Laptops",
    }
    files = [("images", (f"photo-{n}.jpg", photo(n), "image/jpeg")) for n in range(photos)]
    for run in range(runs):
        if run:
            time.sleep(pause)
        started = time.perf_counter()
        accepted = client.post("/api/v1/assess", data=form, files=files)
        accepted.raise_for_status()
        assessment_id = accepted.json()["assessment_id"]
        while client.get(f"/api/v1/assess/{assessment_id}/status").json()["status"] == "processing":
            time.sleep(0.1)
        wall = time.perf_counter() - started
        result = client.get(f"/api/v1/assess/{assessment_id}/result")
        result.raise_for_status()
        results.append({"server": result.json()["total_latency_ms"] / 1000, "wall": wall})
    return results


def summarise(results: list[dict[str, float]]) -> dict[str, Any]:
    """The first check, the median of the rest, the slowest, and whether all fit the budget."""
    walls = [item["wall"] for item in results]
    rest = walls[1:] or walls
    return {
        "checks": len(results),
        "first_wall_s": round(walls[0], 2),
        "median_wall_s": round(statistics.median(rest), 2),
        "max_wall_s": round(max(walls), 2),
        "within_budget": max(walls) <= BUDGET_SECONDS,
    }


def main() -> int:
    """Runs the measurement from the command line and prints the table and the summary."""
    parser = argparse.ArgumentParser(description="Time real GuardianLens checks.")
    parser.add_argument("--api", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--photos", type=int, default=1, help="photos per check (1 to 10)")
    parser.add_argument("--pause", type=float, default=11.0, help="seconds between checks")
    parser.add_argument("--output", type=Path, help="write the results as JSON to this file")
    args = parser.parse_args()

    with httpx2.Client(base_url=args.api, timeout=180) as client:
        results = measure(client, args.runs, args.photos, args.pause)
    for number, item in enumerate(results, 1):
        print(f"check {number:2d}: server {item['server']:5.1f}s  wall {item['wall']:5.1f}s")
    summary = summarise(results)
    print(json.dumps(summary, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"results": results, "summary": summary}, indent=2))
    return 0 if summary["within_budget"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
