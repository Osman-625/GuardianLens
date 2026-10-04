"""Verify a sample of approved listings against the live marketplace page using OpenAI's
web_search tool (Responses API), instead of local browser automation.

Usage:
    python scripts/verify_via_openai.py [N]     # verify first N records (default: all)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openai import OpenAI
from guardianlens.config import settings

SAMPLE_PATH = ROOT / "scripts" / "_verify_sample_100.json"
RESULTS_PATH = ROOT / "scripts" / "_verify_results_100.json"


def _parse_verdict(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    text = text.strip()
    return json.loads(text)


def verify_one(client: OpenAI, model: str, rec: dict) -> dict:
    prompt = f"""Visit this URL and read the live page: {rec['source_url']}
This is a {rec['platform']} Malaysia marketplace listing page.

Compare the LIVE page content against these stored values:
- title: {rec.get('title')}
- price: {rec.get('price')} {rec.get('currency')}
- condition: {rec.get('condition')}
- category: {rec.get('category')}
- location_state: {rec.get('location_state')}

Respond with ONLY a raw JSON object (no markdown code fences, no extra text) with exactly these keys:
{{"verdict": "MATCH" | "MISMATCH" | "UNAVAILABLE", "details": "<short explanation, empty string if MATCH>"}}

Rules:
- MISMATCH only for real disagreements (wrong price, wrong condition, wrong location/state). Ignore wording/casing/formatting differences.
- UNAVAILABLE if the listing is deleted, sold, delisted, or the page could not be loaded/is blocked.
"""
    response = client.responses.create(
        model=model,
        tools=[{"type": "web_search"}],
        input=prompt,
    )
    return _parse_verdict(response.output_text)


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None

    with open(SAMPLE_PATH, encoding="utf-8") as f:
        sample = json.load(f)
    if limit:
        sample = sample[:limit]

    client = OpenAI(api_key=settings.openai_api_key)
    model = settings.openai_model

    results = []
    for i, rec in enumerate(sample):
        try:
            verdict = verify_one(client, model, rec)
        except Exception as exc:  # noqa: BLE001
            verdict = {"verdict": "ERROR", "details": str(exc)[:400]}
        row = {"listing_id": rec["listing_id"], "source_url": rec["source_url"], **verdict}
        results.append(row)
        print(f"[{i+1}/{len(sample)}] {rec['listing_id']} -> {row.get('verdict')} {row.get('details','')[:120]}", flush=True)

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    counts: dict[str, int] = {}
    for r in results:
        counts[r.get("verdict", "ERROR")] = counts.get(r.get("verdict", "ERROR"), 0) + 1
    print("\nFinal counts:", counts)
    for r in results:
        if r.get("verdict") in ("MISMATCH", "UNAVAILABLE", "ERROR"):
            print(f"{r['verdict']}: {r['listing_id']} - {r.get('details')} ({r['source_url']})")


if __name__ == "__main__":
    main()
