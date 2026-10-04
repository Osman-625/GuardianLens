"""Direct-OpenAI-API fallback for the codex_pilot annotation track.

Why this exists: the `codex:codex-rescue` dispatch path (Codex CLI) hit its usage limit after
10/120 pilot listings. Rather than burning more Claude Agent subagent dispatches (a separate,
already-fully-used budget -- claude_pilot.csv is 120/120), this calls OpenAI's API directly with
the user's own OpenAI credit, reusing the exact request shape already proven in
`GuardianLens_Data_Collector_v_1.0.0/src/guardianlens/openai_extractor.py` (Responses API,
input_text + input_image data URLs). It reads that project's .env read-only for OPENAI_API_KEY /
OPENAI_MODEL and never writes to that repo.

Keeps the same blind, evidence-based labeling contract as the Claude/Codex tracks: same three
guideline docs, same annotator id (codex_pilot_v1 -- this is still the "second independent AI
track", just executed via direct API instead of the Codex CLI when the CLI is rate-limited), same
11-column pilot schema. Resumable: skips listing_ids that already have a non-blank label.

Usage (from GuardianLens_Annotation/):
    python scripts/run_openai_pilot_annotation.py --limit 5      # small test batch first
    python scripts/run_openai_pilot_annotation.py                # process all remaining rows
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
COLLECTOR_ENV = ROOT.parent / "GuardianLens_Data_Collector_v_1.0.0" / ".env"
GUIDELINES_DIR = ROOT / "annotation" / "guidelines"
LISTINGS_CSV = ROOT / "data" / "annotation_ready" / "listings.csv"
IMAGES_DIR = ROOT / "data" / "annotation_ready" / "images"
DEFAULT_PILOT_CSV = ROOT / "annotation" / "pilot" / "codex_pilot.csv"

PILOT_COLUMNS = [
    "listing_id", "label", "confidence", "reason", "evidence_text",
    "evidence_image", "evidence_behavioral", "insufficient_evidence_reason",
    "annotator", "annotator_version", "timestamp",
]
VALID_LABELS = {"legitimate", "suspicious", "scam_fraud", "insufficient_evidence"}
ANNOTATOR = "codex_pilot_v1"
# Must cover every image in the dataset's largest listing (max=12 as of the full_v1 run) --
# capping lower silently reintroduces the exact "missed image" failure mode that caused 2 of the
# 3 severe pilot-v2 disagreements (an unrelated item photo past this cutoff). See
# DECISION_RULES.md v4 version history.
MAX_IMAGES_PER_LISTING = 20
LISTING_FIELDS = [
    "listing_id", "platform", "category", "title", "description", "condition",
    "price", "currency", "location_state", "location_city", "language",
    "account_age_days", "seller_rating", "review_count", "active_listing_count",
    "image_count", "reused_image_indicator",
]


def load_env_var(env_path: Path, key: str, default: str = "") -> str:
    if not env_path.is_file():
        raise SystemExit(f"collector .env not found at {env_path}")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            v = v.strip().strip('"').strip("'")
            return v or default
    return default


def load_system_prompt() -> str:
    parts = [
        (GUIDELINES_DIR / name).read_text(encoding="utf-8")
        for name in ("ANNOTATION_GUIDE.md", "DECISION_RULES.md", "EVIDENCE_RULES.md")
    ]
    guidelines = "\n\n---\n\n".join(parts)
    return (
        "You are an independent AI annotator for the GuardianLens fraud-risk annotation pilot. "
        "You are one of several independent annotators labeling this dataset blind -- do not "
        "reference, mention, or speculate about any other annotator's output or identity.\n\n"
        f"{guidelines}\n\n---\n\n"
        "Respond with ONLY a single-line JSON object (no markdown fences, no commentary before or "
        "after) with exactly these keys: listing_id, label, confidence, reason, evidence_text, "
        "evidence_image, evidence_behavioral, insufficient_evidence_reason.\n"
        "- label: one of legitimate, suspicious, scam_fraud, insufficient_evidence\n"
        "- confidence: integer 1-5\n"
        "- reason, evidence_text, evidence_image, evidence_behavioral, "
        "insufficient_evidence_reason: strings (use \"\" when a field genuinely does not apply)"
    )


def build_user_text(row: dict) -> str:
    lines = [f"{f}: {row.get(f, '')}" for f in LISTING_FIELDS]
    return "Listing record (from data/annotation_ready/listings.csv):\n" + "\n".join(lines)


def image_data_urls(row: dict) -> list[str]:
    listing_dir = IMAGES_DIR / row["platform"] / row["listing_id"]
    if not listing_dir.is_dir():
        return []
    paths = sorted(p for p in listing_dir.iterdir() if p.is_file())[:MAX_IMAGES_PER_LISTING]
    urls = []
    for p in paths:
        suffix = p.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else f"image/{suffix.lstrip('.')}"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        urls.append(f"data:{mime};base64,{b64}")
    return urls


def extract_output_text(data: dict) -> str:
    if data.get("output_text"):
        return data["output_text"]
    for item in data.get("output", []):
        for c in item.get("content", []):
            if c.get("type") in ("output_text", "text"):
                return c.get("text", "")
    raise ValueError(f"no output_text found in response: {json.dumps(data)[:500]}")


def parse_json_object(text: str) -> dict:
    m = re.search(r"\{.*\}", text.strip(), re.DOTALL)
    if not m:
        raise ValueError(f"no JSON object found in model output: {text[:300]}")
    return json.loads(m.group(0))


def call_openai(api_key: str, model: str, system_prompt: str, row: dict) -> dict:
    content = [{"type": "input_text", "text": build_user_text(row)}]
    for url in image_data_urls(row):
        content.append({"type": "input_image", "image_url": url, "detail": "high"})
    payload = {
        "model": model,
        "instructions": system_prompt,
        "input": [{"role": "user", "content": content}],
    }
    resp = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=180,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")
    return parse_json_object(extract_output_text(resp.json()))


def validate_and_build_row(parsed: dict, listing_id: str, model: str, annotator: str = ANNOTATOR) -> dict:
    label = str(parsed.get("label", "")).strip()
    if label not in VALID_LABELS:
        raise ValueError(f"invalid label {label!r}")
    confidence = int(parsed.get("confidence"))
    if not 1 <= confidence <= 5:
        raise ValueError(f"confidence out of range: {confidence}")
    reason = str(parsed.get("reason", "")).strip()
    if len(reason) < 10:
        raise ValueError(f"reason too short: {reason!r}")
    return {
        "listing_id": listing_id,
        "label": label,
        "confidence": confidence,
        "reason": reason,
        "evidence_text": str(parsed.get("evidence_text", "") or ""),
        "evidence_image": str(parsed.get("evidence_image", "") or ""),
        "evidence_behavioral": str(parsed.get("evidence_behavioral", "") or ""),
        "insufficient_evidence_reason": str(parsed.get("insufficient_evidence_reason", "") or ""),
        "annotator": annotator,
        "annotator_version": f"{model} (direct OpenAI API -- Codex CLI usage-limit fallback)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def read_csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PILOT_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in PILOT_COLUMNS})
    # OneDrive (this project lives under OneDrive\Desktop) can transiently hold the
    # target file open while syncing, which makes os.replace() raise
    # PermissionError: [WinError 5] Access is denied. Retry with backoff instead of
    # letting one sync hiccup kill an hours-long annotation run.
    last_err: Exception | None = None
    for attempt in range(1, 6):
        try:
            tmp.replace(path)
            return
        except (PermissionError, OSError) as e:
            last_err = e
            wait = min(2 ** attempt, 20)
            print(f"WRITE-RETRY {attempt}/5: {e} (sleeping {wait}s)", file=sys.stderr)
            time.sleep(wait)
    raise last_err  # noqa: RSE102 - re-raise the last real error after exhausting retries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="max number of listings to annotate this run")
    ap.add_argument("--sleep", type=float, default=1.5, help="seconds to sleep between API calls")
    ap.add_argument("--model", default=None, help="override model (default: collector's OPENAI_MODEL)")
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--pilot-csv", type=Path, default=DEFAULT_PILOT_CSV, help="target pilot/run CSV to fill (resumable)")
    ap.add_argument("--annotator", default=ANNOTATOR, help="value to write in the annotator column")
    args = ap.parse_args()
    pilot_csv_path = args.pilot_csv

    api_key = load_env_var(COLLECTOR_ENV, "OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(f"OPENAI_API_KEY is empty in {COLLECTOR_ENV}")
    model = args.model or load_env_var(COLLECTOR_ENV, "OPENAI_MODEL", "gpt-5.6-luna")

    system_prompt = load_system_prompt()
    listings_by_id = {r["listing_id"]: r for r in read_csv_rows(LISTINGS_CSV)}
    pilot_rows = read_csv_rows(pilot_csv_path)
    pilot_by_id = {r["listing_id"]: r for r in pilot_rows}

    pending = [r["listing_id"] for r in pilot_rows if not r.get("label", "").strip()]
    if args.limit is not None:
        pending = pending[: args.limit]

    print(f"model={model}  pending={len(pending)}  total_pilot_rows={len(pilot_rows)}", file=sys.stderr)

    done = 0
    failed: list[str] = []
    for listing_id in pending:
        listing = listings_by_id.get(listing_id)
        if listing is None:
            print(f"SKIP {listing_id}: not found in listings.csv", file=sys.stderr)
            failed.append(listing_id)
            continue

        last_err = None
        for attempt in range(1, args.max_retries + 1):
            try:
                parsed = call_openai(api_key, model, system_prompt, listing)
                row = validate_and_build_row(parsed, listing_id, model, args.annotator)
                pilot_by_id[listing_id].update(row)
                done += 1
                print(f"OK  [{done}/{len(pending)}] {listing_id} -> {row['label']} (conf {row['confidence']})", file=sys.stderr)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                wait = 2 ** attempt
                print(f"RETRY {attempt}/{args.max_retries} {listing_id}: {e} (sleeping {wait}s)", file=sys.stderr)
                time.sleep(wait)
        else:
            print(f"FAIL {listing_id}: {last_err}", file=sys.stderr)
            failed.append(listing_id)

        write_csv_rows(pilot_csv_path, [pilot_by_id[r["listing_id"]] for r in pilot_rows])
        time.sleep(args.sleep)

    print(f"\nDone. annotated={done} failed={len(failed)}", file=sys.stderr)
    if failed:
        print("Failed listing_ids:", ", ".join(failed), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
