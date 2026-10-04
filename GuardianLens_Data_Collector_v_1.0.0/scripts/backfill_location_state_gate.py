"""One-off backfill: location_state was dropped from REQUIRED_FIELDS (processor.py).

Resolves the now-obsolete 'Missing required field: location_state' warnings and
promotes any needs_attention listing that has no other unresolved blocking
warning to ready_for_review.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardianlens.db import connect, transaction, now_iso
from guardianlens.states import transition

LOCATION_STATE_MESSAGE = "Missing required field: location_state"


def main() -> None:
    with transaction() as con:
        obsolete_warning_ids = [
            row["warning_id"]
            for row in con.execute(
                "SELECT warning_id FROM warnings "
                "WHERE warning_type='missing_field' AND message=? AND resolved=0",
                (LOCATION_STATE_MESSAGE,),
            )
        ]
        for warning_id in obsolete_warning_ids:
            con.execute(
                "UPDATE warnings SET resolved=1 WHERE warning_id=?",
                (warning_id,),
            )
        print(f"Resolved {len(obsolete_warning_ids)} obsolete location_state warnings.")

        affected_listing_ids = [
            row["listing_id"]
            for row in con.execute(
                "SELECT DISTINCT listing_id FROM warnings "
                "WHERE warning_type='missing_field' AND message=?",
                (LOCATION_STATE_MESSAGE,),
            )
        ]

        promoted = 0
        for listing_id in affected_listing_ids:
            listing = con.execute(
                "SELECT status FROM listings WHERE listing_id=?", (listing_id,)
            ).fetchone()
            if not listing or listing["status"] != "needs_attention":
                continue
            remaining = con.execute(
                "SELECT COUNT(*) AS n FROM warnings WHERE listing_id=? AND resolved=0",
                (listing_id,),
            ).fetchone()["n"]
            if remaining == 0:
                transition(
                    listing_id,
                    "ready_for_review",
                    reason="backfill: location_state dropped from required-field gate",
                    con=con,
                )
                promoted += 1
        print(f"Promoted {promoted} listings from needs_attention to ready_for_review.")


if __name__ == "__main__":
    main()
