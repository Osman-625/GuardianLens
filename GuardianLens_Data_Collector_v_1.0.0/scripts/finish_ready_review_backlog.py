"""Follow-up to auto_approve_missing_seller_or_location.py: finishes the remaining
`ready_for_review` listings that were skipped because location_state/seller_rating/
review_count was null on the row but restorable data existed elsewhere.

For each of location_state, seller_rating, review_count that is missing on a
ready_for_review listing:
  - Scan every recorded AI extraction attempt for that listing (oldest to newest) and
    take the most recent attempt that actually captured a non-empty value.
  - If one exists, restore it onto the listing (fixes the underlying data-loss bug).
  - If none exists in any attempt, the field is confirmed genuinely never captured and
    is left null.

The listing is then approved through the same full gate review.approve() uses (PII,
placeholder, category, numeric range, images, duplicates, and every OTHER required/
seller field), with only location_state/seller_rating/review_count allowed to stay
null -- and only once confirmed absent from every capture attempt. Restoration and
approval happen in one transaction per listing, so a listing that still fails the gate
for an unrelated reason has its restoration rolled back too and is left untouched in
ready_for_review for manual review.

Scope: status='ready_for_review' only. Nothing else is touched.

Usage:
    python scripts/finish_ready_review_backlog.py            # dry run, report only
    python scripts/finish_ready_review_backlog.py --apply    # actually restore/approve
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardianlens.db import connect, transaction, now_iso
from guardianlens.states import transition
from guardianlens.dedupe import metadata_signature
from guardianlens.validation import validate_fields, verify_product_images, inspect_approved_duplicates
from guardianlens.review import (
    begin_review, action,
    _finish_review_session, _cleanup_private_assets, _raise_cleanup_failures,
)
from guardianlens.collection_handoff import schedule_annotation_dataset_refresh

RELAXED_FIELDS = {"location_state", "seller_rating", "review_count"}


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _most_recent_captured_value(con, listing_id: str, field: str):
    best = None
    for row in con.execute(
        "SELECT structured_output FROM ai_extractions WHERE listing_id=? AND status='success' "
        "ORDER BY created_at ASC, rowid ASC",
        (listing_id,),
    ):
        if not row["structured_output"]:
            continue
        try:
            data = json.loads(row["structured_output"])
        except (TypeError, ValueError):
            continue
        value = data.get(field)
        if not _is_missing(value):
            best = value
    return best


def _evaluate(con, row: dict) -> tuple[bool, str]:
    findings = validate_fields(row)
    if any(f["code"] == "pii" for f in findings):
        return False, "residual PII check failed"

    blocking_missing = [
        f["field"] for f in findings
        if f["code"] == "missing_field" and f["field"] not in RELAXED_FIELDS
    ]
    if blocking_missing:
        return False, "required field missing: " + ", ".join(blocking_missing)

    placeholder_fields = [f["field"] for f in findings if f["code"] == "placeholder_value"]
    if placeholder_fields:
        return False, "placeholder or non-informative value present in: " + ", ".join(placeholder_fields)
    if any(f["code"] == "category" for f in findings):
        return False, "category is not in configured category list"
    invalid = next((f for f in findings if f["code"] in {"invalid_type", "invalid_range"}), None)
    if invalid:
        return False, invalid["message"]

    try:
        verify_product_images(con, row["listing_id"], row["platform"])
    except ValueError as exc:
        return False, str(exc)

    duplicates = inspect_approved_duplicates(con, row)
    if duplicates:
        return False, duplicates[0]["message"]

    return True, "eligible"


def _restore_and_approve(listing_id: str) -> tuple[bool, str, list[tuple[str, object]]]:
    with transaction() as con:
        row = dict(con.execute("SELECT * FROM listings WHERE listing_id=?", (listing_id,)).fetchone())
        restored: list[tuple[str, object]] = []
        still_null: list[str] = []
        for field in RELAXED_FIELDS:
            if not _is_missing(row.get(field)):
                continue
            value = _most_recent_captured_value(con, listing_id, field)
            if value is not None:
                restored.append((field, value))
                row[field] = value
            else:
                still_null.append(field)
        still_null.sort()
        if restored:
            assignments = ",".join(f"{field}=?" for field, _ in restored)
            con.execute(
                f"UPDATE listings SET {assignments},updated_at=? WHERE listing_id=?",
                (*[v for _, v in restored], now_iso(), listing_id),
            )

        ok, reason = _evaluate(con, row)
        if not ok:
            raise ValueError(reason)

        signature = metadata_signature(row["platform"], row["title"], row["description"], row["price"])
        approved_at = now_iso()
        con.execute(
            "UPDATE listings SET metadata_signature=?,approved_at=?,updated_at=? WHERE listing_id=?",
            (signature, approved_at, approved_at, listing_id),
        )
        reason_note = "auto-finished: "
        if restored:
            reason_note += "restored " + ", ".join(f"{f}={v!r}" for f, v in restored) + "; "
        if still_null:
            reason_note += "confirmed absent in every capture attempt: " + ", ".join(still_null)
        transition(listing_id, "approved", reason_note.strip("; "), con=con)
        duration = _finish_review_session(con, listing_id)
        con.execute(
            "INSERT INTO review_actions(review_action_id,listing_id,action,finished_at,duration_seconds,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), listing_id, "approve", approved_at, duration, approved_at),
        )
    try:
        _raise_cleanup_failures(listing_id, "approved", _cleanup_private_assets(listing_id, "approved"))
    finally:
        schedule_annotation_dataset_refresh("review_approved")
    return True, "approved", restored


def main() -> None:
    apply = "--apply" in sys.argv[1:]

    con = connect()
    try:
        candidates = [
            dict(r) for r in con.execute(
                "SELECT * FROM listings WHERE status='ready_for_review' AND "
                "(seller_rating IS NULL OR location_state IS NULL OR TRIM(location_state)='' OR review_count IS NULL)"
            )
        ]
        previews = []
        for row in candidates:
            restorable = []
            still_missing = []
            for field in RELAXED_FIELDS:
                if not _is_missing(row.get(field)):
                    continue
                value = _most_recent_captured_value(con, row["listing_id"], field)
                if value is not None:
                    restorable.append((field, value))
                else:
                    still_missing.append(field)
            preview_row = dict(row)
            for field, value in restorable:
                preview_row[field] = value
            ok, reason = _evaluate(con, preview_row)
            previews.append((row["listing_id"], restorable, still_missing, ok, reason))
    finally:
        con.close()

    print(f"Remaining ready_for_review listings needing completion: {len(candidates)}")
    will_restore_something = [p for p in previews if p[1]]
    print(f"  will restore a field from a prior capture attempt: {len(will_restore_something)}")
    eligible = [p for p in previews if p[3]]
    ineligible = [p for p in previews if not p[3]]
    print(f"  eligible for approval after restore/null: {len(eligible)}")
    print(f"  still blocked for another reason: {len(ineligible)}")
    for lid, restorable, still_missing, ok, reason in previews:
        detail = []
        if restorable:
            detail.append("restore " + ", ".join(f"{f}={v!r}" for f, v in restorable))
        if still_missing:
            detail.append("null " + ", ".join(still_missing))
        tag = "OK" if ok else f"BLOCKED ({reason})"
        print(f"  {lid}: {'; '.join(detail) or 'no field change'} -> {tag}")

    if not apply:
        print("\nDry run only -- no changes made. Re-run with --apply to restore/null and approve eligible listings.")
        return

    approved, failed = [], []
    for lid, restorable, still_missing, ok, reason in previews:
        if not ok:
            continue
        begin_review(lid)
        try:
            _, _, restored = _restore_and_approve(lid)
            approved.append((lid, restored))
        except Exception as exc:  # noqa: BLE001 - report and revert, never crash the batch
            action(lid, "ready_for_review", reason=f"auto-finish failed: {exc}")
            failed.append((lid, str(exc)))

    print(f"\nApproved: {len(approved)}")
    print(f"Failed and reverted to ready_for_review: {len(failed)}")
    for lid, reason in failed:
        print(f"  {lid}: {reason}")


if __name__ == "__main__":
    main()
