"""One-off: requeue needs_attention listings whose only gap is a seller/behavioural
field (account_age_days, active_listing_count) for which the seller screenshot was
already captured (seller_screenshot_path IS NOT NULL). These don't need a live
re-scrape -- the prior AI extraction just missed the field (stale-code run and/or an
older prompt). Moves them ATTENTION -> CAPTURED so the batch processor re-extracts
them with the current prompt and current gates.

Deliberately excludes listings with no seller_screenshot_path (seller page was never
captured -- e.g. Mudah access-denied) -- those require scripts/... seller retry queue,
not reprocessing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardianlens.db import transaction
from guardianlens.states import transition

MESSAGE_PREFIX = "Missing required seller/behavioural field(s):"


def main() -> None:
    with transaction() as con:
        rows = con.execute(
            """
            SELECT DISTINCT l.listing_id
            FROM listings l
            JOIN warnings w ON w.listing_id = l.listing_id
            WHERE l.status='needs_attention'
              AND w.resolved=0
              AND w.warning_type='missing_field'
              AND w.message LIKE ?
              AND l.seller_screenshot_path IS NOT NULL
            """,
            (MESSAGE_PREFIX + "%",),
        ).fetchall()
        listing_ids = [row["listing_id"] for row in rows]
        for listing_id in listing_ids:
            transition(
                listing_id,
                "captured",
                reason="requeue: seller screenshot already captured, re-extract with current prompt/gates",
                con=con,
            )
        print(f"Requeued {len(listing_ids)} listings from needs_attention to captured.")


if __name__ == "__main__":
    main()
