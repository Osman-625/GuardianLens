"""One-off re-extraction pass: extraction_contract.py now teaches the AI extractor to count
non-SOLD listings for active_listing_count and to compute account_age_days from an absolute
join date using the listing's capture date. Neither fix helps listings already sitting in the
database with those fields null -- they need to be re-run through AI extraction.

This script:
  1. Finds needs_attention listings missing active_listing_count (Carousell) or account_age_days
     (Mudah) whose seller page was actually captured (so there is real text to re-extract from --
     access_denied failures are a separate, not-yet-built retry-capture problem).
  2. Moves them from needs_attention back to captured (a state transition added to states.py
     for exactly this: explicit reprocessing).
  3. Starts a normal processing run through the live GuardianLens server's /api/batch/start so
     progress is visible on the dashboard like any other run, instead of bypassing it.

Requires the GuardianLens server to be running (default http://127.0.0.1:8770).
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardianlens.db import transaction
from guardianlens.security import ensure_local_token
from guardianlens.states import transition

SERVER = "http://127.0.0.1:8770"

CANDIDATE_SQL = """
    SELECT l.listing_id
    FROM listings l
    JOIN capture_batch_items cbi ON cbi.listing_id = l.listing_id
    WHERE l.status = 'needs_attention'
      AND cbi.last_error_type IS NULL
      AND (
        (l.platform = 'carousell' AND l.active_listing_count IS NULL)
        OR (l.platform = 'mudah' AND l.account_age_days IS NULL)
      )
"""


def main() -> None:
    with transaction() as con:
        candidates = [row["listing_id"] for row in con.execute(CANDIDATE_SQL)]
        print(f"Found {len(candidates)} listings to re-extract.")
        for listing_id in candidates:
            transition(
                listing_id,
                "captured",
                reason="re-extraction: active_listing_count/account_age_days prompt fix",
                con=con,
            )
    print(f"Moved {len(candidates)} listings back to captured.")

    if not candidates:
        return

    token = ensure_local_token()
    request = urllib.request.Request(
        f"{SERVER}/api/batch/start",
        method="POST",
        headers={
            "X-GuardianLens-Token": token,
            "Content-Type": "application/json",
        },
        data=json.dumps({"duration_minutes": None, "item_limit": len(candidates)}).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print("Processing run started:", response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(f"Could not reach the GuardianLens server at {SERVER}: {exc}")
        print("Start it (run.bat) and then run: POST /api/batch/start (or use the dashboard).")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
