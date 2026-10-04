"""One-off reconciliation: the 2026-08-29 18:43 re-extraction run (967 listings) executed
against a stale in-memory copy of processor.py in the running server process (started
2026-08-29 00:41, never restarted after that day's gate fixes). It regenerated
'Missing required seller/behavioural field(s): ...' warnings using the OLD
SELLER_SIGNAL_FIELDS (which still included seller_rating/review_count), so many warnings
now name fields that are no longer required, mixed in with fields that still are.

Unlike backfill_seller_rating_gate.py (which only matches the handful of exact obsolete
message strings), this recomputes each affected listing's warning against the CURRENT
SELLER_SIGNAL_FIELDS using the listing's actual column values, so compound stale messages
(e.g. "account_age_days, seller_rating, review_count, active_listing_count") are handled
correctly: the obsolete warning is resolved and, if fields are still genuinely missing,
replaced with a warning naming only those fields.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardianlens.db import transaction
from guardianlens.processor import SELLER_SIGNAL_FIELDS, add_warning
from guardianlens.states import transition

MESSAGE_PREFIX = "Missing required seller/behavioural field(s): "


def main() -> None:
    with transaction() as con:
        warning_rows = con.execute(
            "SELECT warning_id, listing_id FROM warnings "
            "WHERE warning_type='missing_field' AND resolved=0 AND message LIKE ?",
            (MESSAGE_PREFIX + "%",),
        ).fetchall()

        listing_ids = sorted({row["listing_id"] for row in warning_rows})
        resolved_count = 0
        reissued_count = 0
        promoted = 0

        for listing_id in listing_ids:
            stale_warning_ids = [
                row["warning_id"] for row in warning_rows if row["listing_id"] == listing_id
            ]
            for warning_id in stale_warning_ids:
                con.execute("UPDATE warnings SET resolved=1 WHERE warning_id=?", (warning_id,))
            resolved_count += len(stale_warning_ids)

            listing = con.execute(
                "SELECT status, account_age_days, seller_rating, review_count, active_listing_count "
                "FROM listings WHERE listing_id=?",
                (listing_id,),
            ).fetchone()
            if not listing:
                continue

            still_missing = [
                key for key in SELLER_SIGNAL_FIELDS if listing[key] in (None, "")
            ]
            if still_missing:
                add_warning(
                    con,
                    listing_id,
                    "missing_field",
                    MESSAGE_PREFIX + ", ".join(still_missing),
                )
                reissued_count += 1

            if listing["status"] != "needs_attention":
                continue
            remaining = con.execute(
                "SELECT COUNT(*) AS n FROM warnings WHERE listing_id=? AND resolved=0",
                (listing_id,),
            ).fetchone()["n"]
            if remaining == 0:
                transition(
                    listing_id,
                    "ready_for_review",
                    reason="reconcile: recomputed seller/behavioural gate against current SELLER_SIGNAL_FIELDS",
                    con=con,
                )
                promoted += 1

        print(f"Listings affected: {len(listing_ids)}")
        print(f"Stale warnings resolved: {resolved_count}")
        print(f"Warnings reissued with corrected field list: {reissued_count}")
        print(f"Promoted needs_attention -> ready_for_review: {promoted}")


if __name__ == "__main__":
    main()
