"""Direct-Anthropic-API runner for the claude_full_v1 annotation track (Pass 2, full dataset).

Mirrors `run_openai_pilot_annotation.py` exactly (same guideline load, same system prompt, same
11-column schema, same resumability), but calls the Anthropic Messages API directly with the
user's own Anthropic credit instead of dispatching Claude Agent subagents (that budget was fully
used during the pilot phase and dispatching ~2,209 subagents for the full run is not practical).
Reuses the exact request shape already proven in
`GuardianLens_Data_Collector_v_1.0.0/src/guardianlens/anthropic_extractor.py` (Messages API,
image + text content blocks). Reads that project's .env read-only for ANTHROPIC_API_KEY /
ANTHROPIC_MODEL and never writes to that repo.

Keeps the same blind, evidence-based labeling contract as the other tracks: same three guideline
docs, same annotator id (claude_full_v1), same 11-column pilot schema. Resumable: skips
listing_ids that already have a non-blank label.

Usage (from GuardianLens_Annotation/):
    python scripts/run_anthropic_full_annotation.py --limit 5      # small test batch first
    python scripts/run_anthropic_full_annotation.py                # process all remaining rows
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

ROOT = Path(__file__).resolve().parent.parent
COLLECTOR_ENV = ROOT.parent / "GuardianLens_Data_Collector_v_1.0.0" / ".env"
GUIDELINES_DIR = ROOT / "annotation" / "guidelines"
LISTINGS_CSV = ROOT / "data" / "annotation_ready" / "listings.csv"
IMAGES_DIR = ROOT / "data" / "annotation_ready" / "images"
DEFAULT_PILOT_CSV = ROOT / "annotation" / "runs" / "full_v1" / "claude_annotations.csv"

PILOT_COLUMNS = [
    "listing_id", "label", "confidence", "reason", "evidence_text",
    "evidence_image", "evidence_behavioral", "insufficient_evidence_reason",
    "annotator", "annotator_version", "timestamp",
]
VALID_LABELS = {"legitimate", "suspicious", "scam_fraud", "insufficient_evidence"}
ANNOTATOR = "claude_full_v1"
# See run_openai_pilot_annotation.py for why this must cover every image (max=12 as of the
# full_v1 run) -- capping lower silently reintroduces the "missed image" failure mode documented
# in DECISION_RULES.md v3 version history.
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


def image_blocks(row: dict) -> list[dict]:
    listing_dir = IMAGES_DIR / row["platform"] / row["listing_id"]
    if not listing_dir.is_dir():
        return []
    paths = sorted(p for p in listing_dir.iterdir() if p.is_file())[:MAX_IMAGES_PER_LISTING]
    blocks = []
    for p in paths:
        suffix = p.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        media_type = "image/jpeg" if suffix in {".jpg", ".jpeg"} else f"image/{suffix.lstrip('.')}"
        b64 = base64.standard_b64encode(p.read_bytes()).decode("ascii")
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })
    return blocks


def parse_json_object(text: str) -> dict:
    m = re.search(r"\{.*\}", text.strip(), re.DOTALL)
    if not m:
        raise ValueError(f"no JSON object found in model output: {text[:300]}")
    return json.loads(m.group(0))


def call_anthropic(client, model: str, system_prompt: str, row: dict) -> dict:
    content = image_blocks(row) + [{"type": "text", "text": build_user_text(row)}]
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": content}],
    )
    raw = "".join(block.text for block in response.content if block.type == "text")
    return parse_json_object(raw)


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
        "annotator_version": f"{model} (direct Anthropic API -- full-dataset Pass 2 run)",
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
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="max number of listings to annotate this run")
    ap.add_argument("--sleep", type=float, default=1.5, help="seconds to sleep between API calls")
    ap.add_argument("--model", default=None, help="override model (default: collector's ANTHROPIC_MODEL)")
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--pilot-csv", type=Path, default=DEFAULT_PILOT_CSV, help="target pilot/run CSV to fill (resumable)")
    ap.add_argument("--annotator", default=ANNOTATOR, help="value to write in the annotator column")
    args = ap.parse_args()
    pilot_csv_path = args.pilot_csv

    try:
        import anthropic
    except ImportError as e:
        raise SystemExit("Anthropic SDK is not installed in this interpreter") from e

    api_key = load_env_var(COLLECTOR_ENV, "ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(f"ANTHROPIC_API_KEY is empty in {COLLECTOR_ENV}")
    model = args.model or load_env_var(COLLECTOR_ENV, "ANTHROPIC_MODEL", "claude-opus-5")
    client = anthropic.Anthropic(api_key=api_key)

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
                parsed = call_anthropic(client, model, system_prompt, listing)
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
