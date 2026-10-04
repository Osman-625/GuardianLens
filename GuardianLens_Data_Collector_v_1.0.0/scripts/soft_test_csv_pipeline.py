"""Run 5+5 supplied CSV URLs through the isolated synthetic soft-test pipeline."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import random
import re
import sys
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardianlens.batch import BatchManager
from guardianlens.capture import create_capture
from guardianlens.config import settings
from guardianlens.db import connect, init_db
from guardianlens.models import CaptureRequest
from guardianlens.replay import ReplayManager, create_csv_batch, parse_csv_rows, validate_import_url
import guardianlens.processor as processor


DEFAULT_CAROUSELL = ROOT.parent / "URL_Crawler" / "output" / "carousell_urls_full.csv"
DEFAULT_MUDAH = ROOT.parent / "URL_Crawler" / "output" / "mudah_urls_full.csv"


class SoftTestExtractor:
    provider = "mock"
    model = "csv-soft-test-fixture"
    prompt_version = "soft_test_5x5_v1"

    def extract(
        self,
        _screenshot_path: Path,
        platform: str,
        _page_title: str | None,
        _categories: list[str],
        source_url: str | None = None,
        **_kwargs,
    ) -> dict:
        source_url = source_url or ""
        path = unquote(urlsplit(source_url).path)
        listing_number = int(re.search(r"(\d+)(?:/|\.htm)?$", path).group(1))
        slug = path.rsplit("/", 1)[-1].removesuffix(".htm")
        title = " ".join(slug.rsplit("-", 1)[0].split("-")).strip().title()
        record_token = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:8]
        return {
            "title": f"{title[:180]} Soft {record_token}",
            "description": f"Synthetic soft-test extraction for {platform} record {record_token}.",
            "category": None,
            "condition": "Used",
            "price": float(100 + listing_number % 10_000),
            "currency": "MYR",
            "location_state": "Selangor",
            "location_city": None,
            "account_age_days": 365 + listing_number % 2_000,
            "seller_rating": 4.8,
            "review_count": 10 + listing_number % 250,
            "active_listing_count": 1 + listing_number % 30,
            "language": "en",
        }


def _image_bytes(seed: int) -> bytes:
    rng = random.Random(seed)
    image = Image.frombytes("RGB", (360, 280), rng.randbytes(360 * 280 * 3))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=88)
    return output.getvalue()


def _data_url(data: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def _load_candidates(path: Path, platform: str) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows = parse_csv_rows(path.read_bytes())
    candidates = []
    seen_urls: set[str] = set()
    for row in rows:
        try:
            normalized, detected, listing_id = validate_import_url(row["source_url"])
        except ValueError:
            continue
        if detected != platform or not listing_id:
            continue
        if normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        candidates.append(
            {
                "platform": platform,
                "category": row.get("category") or "",
                "url": normalized,
            }
        )
    return candidates


def _sample_rows(carousell_path: Path, mudah_path: Path, count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for platform, path in (("carousell", carousell_path), ("mudah", mudah_path)):
        candidates = _load_candidates(path, platform)
        if len(candidates) < count:
            raise RuntimeError(f"{path.name} has only {len(candidates)} supported {platform} rows")
        rows.extend(rng.sample(candidates, count))
    rng.shuffle(rows)
    return rows


def _batch_csv(rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=("platform", "category", "url"))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def run(carousell_path: Path, mudah_path: Path, count: int, seed: int) -> dict:
    original_mode = settings.mode
    original_downloader = processor.download_image
    replay: ReplayManager | None = None
    batch: BatchManager | None = None
    object.__setattr__(settings, "mode", "soft_test")
    try:
        init_db()
        selected = _sample_rows(carousell_path, mudah_path, count, seed)
        snapshot = create_csv_batch(
            _batch_csv(selected),
            "soft_test_5x5_sources.csv",
            f"Soft test {count} Carousell + {count} Mudah",
        )
        batch_id = snapshot["batch"]["batch_id"]
        replay = ReplayManager()
        replay.start(batch_id)
        capture_index = 0
        while True:
            item = replay.claim_next()
            if not item:
                break
            replay.update_item(item["batch_item_id"], status="capturing")
            capture_index += 1
            captured = create_capture(
                CaptureRequest(
                    platform=item["platform"],
                    source_url=item["source_url"],
                    page_title=f"Soft-test {item['platform']} listing",
                    visible_text=(
                        "Synthetic soft-test page text. Used product in good condition. "
                        "Price and seller signals are visible."
                    ),
                    screenshot_data_url=_data_url(_image_bytes(10_000 + capture_index)),
                    image_urls=[f"https://soft-test.invalid/product-{capture_index}.jpg"],
                    listing_evidence={
                        "h1_text": "Soft-test product listing",
                        "has_price_signal": True,
                    },
                    capture_source="csv_batch",
                    batch_item_id=item["batch_item_id"],
                )
            )
            replay.update_item(
                item["batch_item_id"],
                status="captured",
                listing_id=captured["listing_id"],
            )

        capture_snapshot = replay.status(batch_id)
        if capture_snapshot["batch"]["status"] != "completed":
            raise RuntimeError("soft-test capture pass did not complete")

        def fixture_downloader(url: str) -> bytes:
            match = re.search(r"product-(\d+)\.jpg$", url)
            if not match:
                raise ValueError("unexpected soft-test image URL")
            return _image_bytes(20_000 + int(match.group(1)))

        processor.download_image = fixture_downloader
        batch = BatchManager()
        run_id = batch.start(
            duration_minutes=60,
            item_limit=count * 2,
            extractor_factory=SoftTestExtractor,
            capture_batch_id=batch_id,
        )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            processing = batch.status(batch_id)
            latest = processing["latest_run"]
            if latest and latest["status"] not in {"running", "paused", "stopping"}:
                break
            time.sleep(0.05)
        else:
            batch.stop()
            raise TimeoutError("soft-test preprocessing did not finish within 120 seconds")

        with closing(connect()) as con:
            listing_rows = [
                dict(row)
                for row in con.execute(
                    """SELECT listing_id,platform,source_url,status,category,csv_row
                       FROM listings WHERE capture_batch_id=? ORDER BY csv_row""",
                    (batch_id,),
                )
            ]
            platform_status = [
                dict(row)
                for row in con.execute(
                    """SELECT platform,status,COUNT(*) AS count FROM listings
                       WHERE capture_batch_id=? GROUP BY platform,status ORDER BY platform,status""",
                    (batch_id,),
                )
            ]
            image_count = con.execute(
                """SELECT COUNT(*) AS count FROM images image
                   JOIN listings listing ON listing.listing_id=image.listing_id
                   WHERE listing.capture_batch_id=?""",
                (batch_id,),
            ).fetchone()["count"]
            review_count = con.execute(
                """SELECT COUNT(*) AS count FROM listings
                   WHERE capture_batch_id=? AND status IN ('ready_for_review','needs_attention')""",
                (batch_id,),
            ).fetchone()["count"]

        expected = count * 2
        if capture_snapshot["progress"]["captured"] != expected:
            raise AssertionError("not every staged URL reached a captured checkpoint")
        if len(listing_rows) != expected or image_count != expected or review_count != expected:
            raise AssertionError("not every soft-test record reached the human-review queue")

        final_snapshot = replay.status(batch_id)
        report = {
            "result": "PASS",
            "mode": "soft_test",
            "capture_evidence": "synthetic; source URLs came from the supplied CSV files",
            "seed": seed,
            "per_platform": count,
            "batch_id": batch_id,
            "processing_run_id": run_id,
            "stage_file": final_snapshot["stage_file"],
            "capture": final_snapshot["progress"],
            "processing": final_snapshot["processing"],
            "image_count": image_count,
            "human_review_queue_count": review_count,
            "platform_status": platform_status,
            "listings": listing_rows,
            "source_files": [str(carousell_path.resolve()), str(mudah_path.resolve())],
        }
        report_path = settings.data_dir / "reports" / "csv_pipeline_5x5.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report["report_path"] = str(report_path.relative_to(settings.root))
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
    finally:
        if batch is not None:
            batch.stop()
        if replay is not None:
            replay.shutdown()
        processor.download_image = original_downloader
        object.__setattr__(settings, "mode", original_mode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--carousell", type=Path, default=DEFAULT_CAROUSELL)
    parser.add_argument("--mudah", type=Path, default=DEFAULT_MUDAH)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260828)
    args = parser.parse_args()
    if args.count < 1 or args.count > 50:
        parser.error("--count must be between 1 and 50")
    report = run(args.carousell, args.mudah, args.count, args.seed)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
