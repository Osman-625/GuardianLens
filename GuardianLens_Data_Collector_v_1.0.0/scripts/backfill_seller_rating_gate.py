"""One-off backfill: seller_rating and review_count were dropped from SELLER_SIGNAL_FIELDS
(processor.py) since they're legitimately absent for zero-review Carousell sellers and for
every Mudah seller (Mudah's seller page has no rating/review system at all).

Resolves the now-obsolete 'Missing required seller/behavioural field(s): ...' warnings that
name only seller_rating and/or review_count, and promotes any needs_attention listing that
has no other unresolved blocking warning to ready_for_review.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardianlens.db import connect, transaction, now_iso
from guardianlens.states import transition

OBSOLETE_MESSAGES = {
    "Missing required seller/behavioural field(s): seller_rating",
    "Missing required seller/behavioural field(s): review_count",
    "Missing required seller/behavioural field(s): seller_rating, review_count",
}


def main() -> None:
    with transaction() as con:
        obsolete_warning_ids = [
            row["warning_id"]
            for row in con.execute(
                "SELECT warning_id FROM warnings "
                "WHERE warning_type='missing_field' AND resolved=0 AND message IN (?,?,?)",
                tuple(OBSOLETE_MESSAGES),
            )
        ]
        for warning_id in obsolete_warning_ids:
            con.execute("UPDATE warnings SET resolved=1 WHERE warning_id=?", (warning_id,))
        print(f"Resolved {len(obsolete_warning_ids)} obsolete seller_rating/review_count warnings.")

        affected_listing_ids = [
            row["listing_id"]
            for row in con.execute(
                "SELECT DISTINCT listing_id FROM warnings "
                "WHERE warning_type='missing_field' AND message IN (?,?,?)",
                tuple(OBSOLETE_MESSAGES),
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
                    reason="backfill: seller_rating/review_count dropped from required-field gate",
                    con=con,
                )
                promoted += 1
        print(f"Promoted {promoted} listings from needs_attention to ready_for_review.")


if __name__ == "__main__":
    main()
