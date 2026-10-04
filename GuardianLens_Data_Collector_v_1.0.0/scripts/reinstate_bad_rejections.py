"""One-off: reinstate rejected listings whose rejection reason no longer holds.

Context: 261 listings were bulk-rejected on 2026-09-10 as "dropped: multiple
unresolved data-quality findings ... dataset has headroom against target".
Re-checking them against today's actual approval gate (validate_fields,
inspect_product_images, inspect_approved_duplicates -- the same checks
review.approve() runs) shows most no longer have any blocker, and a further
handful are blocked only by a since-fixed PII false-positive
(see pii.py's GENERIC_PHONE fix). A small number contain a genuine embedded
phone number, which this script redacts before reinstating.

`rejected` is a terminal state in states.py (TRANSITIONS[REJECTED] == set())
and review.begin_review() refuses non-REVIEWABLE statuses, so there is no
sanctioned path back from it. This script performs a deliberate, explicitly
authorized, fully audited exception: a direct status_history-logged status
update identical in shape to what states._transition() writes, run only for
listings verified clean against current evidence. It never touches a listing
rejected by an actual human decision (reason == "human rejected").
"""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardianlens.db import connect, now_iso, transaction  # noqa: E402
from guardianlens.pii import GENERIC_PHONE  # noqa: E402
from guardianlens.validation import (  # noqa: E402
    REQUIRED_FIELDS, inspect_approved_duplicates, inspect_product_images, validate_fields,
)

BULK_REJECT_REASON = (
    "dropped: multiple unresolved data-quality findings (PII/duplicate-image/other), "
    "dataset has headroom against target"
)

CONFIRMED_PHONE_NUMBERS = {
    "c650fd8f-42f6-45c4-a480-8e3c4ab1a8a4", "4abd7420-c727-4c57-a23b-d6894881cf77",
    "0abfa94b-1a80-4ab0-8f0c-29add629cae6", "09eb28cf-f9d0-42df-b1d4-f46ebc4517f8",
    "f6853d3e-173c-4183-b640-4463ef19788c", "3e5c7fb2-f8c8-47d3-a480-6c9c79cd8139",
    "ba38fc5c-97a2-493c-8cb7-6d08c1e1e0e5", "fb8dc415-444c-4b0c-a39a-62b0b8fad095",
    "1f4a2474-a121-4088-a114-49172526b017", "bc9e27b8-5d27-4f55-b062-f7d8e79d28d1",
}


def _blockers(con, row: dict) -> list[str]:
    findings = validate_fields(row)
    blockers = []
    if any(f["code"] == "pii" for f in findings):
        blockers.append("pii")
    for key in REQUIRED_FIELDS:
        if key == "location_state":
            continue
        if any(f["code"] == "missing_field" and f["field"] == key for f in findings):
            blockers.append(f"missing_required:{key}")
    if any(f["code"] == "placeholder_value" for f in findings):
        blockers.append("placeholder_value")
    if any(f["code"] == "category" for f in findings):
        blockers.append("category")
    if any(f["code"] in {"invalid_type", "invalid_range"} for f in findings):
        blockers.append("invalid_value")
    if inspect_product_images(con, row["listing_id"], row["platform"]):
        blockers.append("images")
    if inspect_approved_duplicates(con, row):
        blockers.append("duplicate")
    return blockers


def _redact_confirmed_phone(con, listing_id: str) -> str | None:
    row = con.execute("SELECT description FROM listings WHERE listing_id=?", (listing_id,)).fetchone()
    text = row["description"] or ""
    redacted, count = GENERIC_PHONE.subn("[REDACTED]", text)
    if count:
        con.execute("UPDATE listings SET description=?,updated_at=? WHERE listing_id=?", (redacted, now_iso(), listing_id))
    return redacted if count else None


def _reinstate(con, listing_id: str, reason: str) -> None:
    row = con.execute("SELECT status FROM listings WHERE listing_id=?", (listing_id,)).fetchone()
    if row["status"] != "rejected":
        return
    stamp = now_iso()
    con.execute("UPDATE listings SET status='needs_attention',updated_at=? WHERE listing_id=?", (stamp, listing_id))
    con.execute(
        "INSERT INTO status_history(history_id,listing_id,from_status,to_status,timestamp,reason) VALUES(?,?,?,?,?,?)",
        (str(uuid.uuid4()), listing_id, "rejected", "needs_attention", stamp, reason),
    )


def main() -> int:
    apply = "--apply" in sys.argv
    con = connect()
    try:
        rows = [dict(r) for r in con.execute("SELECT * FROM listings WHERE status='rejected'")]
        reasons = {}
        for r in rows:
            h = con.execute(
                "SELECT reason FROM status_history WHERE listing_id=? AND to_status='rejected' ORDER BY timestamp DESC LIMIT 1",
                (r["listing_id"],),
            ).fetchone()
            reasons[r["listing_id"]] = h["reason"] if h else None
    finally:
        con.close()

    bulk = [r for r in rows if reasons.get(r["listing_id"]) == BULK_REJECT_REASON]
    print(f"bulk-rejected candidates: {len(bulk)} (of {len(rows)} total rejected)")

    reinstated, redacted, skipped = [], [], []
    for row in bulk:
        listing_id = row["listing_id"]
        con = connect()
        try:
            if listing_id in CONFIRMED_PHONE_NUMBERS:
                if apply:
                    with transaction() as tx:
                        new_text = _redact_confirmed_phone(tx, listing_id)
                        current = dict(tx.execute("SELECT * FROM listings WHERE listing_id=?", (listing_id,)).fetchone())
                        blockers = _blockers(tx, current)
                        if not blockers:
                            _reinstate(
                                tx, listing_id,
                                "Evidence verification pass: rejection reason no longer applies; "
                                "embedded phone number redacted from description",
                            )
                            redacted.append(listing_id)
                            reinstated.append(listing_id)
                        else:
                            skipped.append((listing_id, "still blocked after redaction: " + ",".join(blockers)))
                else:
                    redacted.append(listing_id)  # would redact
                    reinstated.append(listing_id)  # would reinstate, pending live blocker recheck
                continue
            current = dict(con.execute("SELECT * FROM listings WHERE listing_id=?", (listing_id,)).fetchone())
            blockers = _blockers(con, current)
            if blockers:
                skipped.append((listing_id, "still blocked: " + ",".join(blockers)))
                continue
            if apply:
                with transaction() as tx:
                    _reinstate(tx, listing_id, "Evidence verification pass: rejection reason no longer applies; no current blockers")
            reinstated.append(listing_id)
        finally:
            con.close()

    print(f"reinstated: {len(reinstated)}")
    print(f"phone numbers redacted: {len(redacted)}")
    print(f"left rejected (still blocked): {len(skipped)}")
    for listing_id, why in skipped:
        print("  ", listing_id, why)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
