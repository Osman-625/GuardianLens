"""One-off remediation: approve `ready_for_review` listings that are blocked ONLY by a
missing seller_rating and/or location_state, provided the underlying captured data
(every AI extraction attempt on record for that listing) genuinely never contained a
value for that field.

Scope is deliberately narrow:
  - Only listings with status='ready_for_review' are touched. needs_attention and every
    other bucket is left untouched.
  - Any OTHER blocking finding (another missing required/seller field, PII, placeholder
    value, bad category, invalid type/range, broken images, duplicate) still blocks
    approval exactly as review.approve() would block it manually.
  - If seller_rating/location_state is null on the listing row but a *prior* AI
    extraction attempt for that same listing actually captured a value (a reprocessing
    data-loss case), the listing is skipped for manual review instead of being
    null-approved, since real data appears to exist and was lost rather than never
    captured.

Usage:
    python scripts/auto_approve_missing_seller_or_location.py            # dry run, report only
    python scripts/auto_approve_missing_seller_or_location.py --apply    # actually approve
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

RELAXED_FIELDS = {"location_state", "seller_rating"}


def _field_ever_captured(con, listing_id: str, field: str) -> bool:
    """True if ANY recorded AI extraction attempt for this listing has a real value."""
    for row in con.execute(
        "SELECT structured_output FROM ai_extractions WHERE listing_id=? AND status='success'",
        (listing_id,),
    ):
        if not row["structured_output"]:
            continue
        try:
            data = json.loads(row["structured_output"])
        except (TypeError, ValueError):
            continue
        value = data.get(field)
        if value is not None and not (isinstance(value, str) and not value.strip()):
            return True
    return False


def _evaluate(con, row: dict) -> tuple[bool, str]:
    """Non-mutating check: would this listing be safe to auto-approve? Mirrors
    review._approve_in_transaction's gate, except missing_field findings for
    RELAXED_FIELDS are allowed once confirmed absent from every capture attempt."""
    findings = validate_fields(row)
    if any(f["code"] == "pii" for f in findings):
        return False, "residual PII check failed"

    blocking_missing = [
        f["field"] for f in findings
        if f["code"] == "missing_field" and f["field"] not in RELAXED_FIELDS
    ]
    if blocking_missing:
        return False, "required field missing: " + ", ".join(blocking_missing)

    relaxed_missing = [
        f["field"] for f in findings
        if f["code"] == "missing_field" and f["field"] in RELAXED_FIELDS
    ]
    if not relaxed_missing:
        return False, "not missing seller_rating or location_state (out of scope for this script)"

    for field in relaxed_missing:
        if _field_ever_captured(con, row["listing_id"], field):
            return False, (
                f"{field} is null on the listing but a prior AI extraction attempt captured "
                "a value for it -- looks like a data-loss bug, needs manual review, not auto-approval"
            )

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

    return True, "eligible: missing only " + ", ".join(relaxed_missing) + " (confirmed absent in every capture attempt)"


def _approve_relaxed(listing_id: str) -> None:
    with transaction() as con:
        row = dict(con.execute("SELECT * FROM listings WHERE listing_id=?", (listing_id,)).fetchone())
        ok, reason = _evaluate(con, row)
        if not ok:
            raise ValueError(reason)
        signature = metadata_signature(row["platform"], row["title"], row["description"], row["price"])
        approved_at = now_iso()
        con.execute(
            "UPDATE listings SET metadata_signature=?,approved_at=?,updated_at=? WHERE listing_id=?",
            (signature, approved_at, approved_at, listing_id),
        )
        transition(
            listing_id, "approved",
            "auto-approved: missing only seller_rating/location_state, confirmed absent in every capture attempt",
            con=con,
        )
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


def main() -> None:
    apply = "--apply" in sys.argv[1:]

    con = connect()
    try:
        candidates = [
            dict(r) for r in con.execute(
                "SELECT * FROM listings WHERE status='ready_for_review' AND "
                "(seller_rating IS NULL OR location_state IS NULL OR TRIM(location_state)='')"
            )
        ]
        evaluations = [(row["listing_id"], *_evaluate(con, row)) for row in candidates]
    finally:
        con.close()

    eligible = [(lid, reason) for lid, ok, reason in evaluations if ok]
    skipped = [(lid, reason) for lid, ok, reason in evaluations if not ok]

    print(f"ready_for_review listings missing seller_rating and/or location_state: {len(candidates)}")
    print(f"  eligible for auto-approval: {len(eligible)}")
    print(f"  skipped (needs manual review): {len(skipped)}")
    if skipped:
        print("\nSkipped listings and why:")
        for lid, reason in skipped:
            print(f"  {lid}: {reason}")

    if not apply:
        print("\nDry run only -- no changes made. Re-run with --apply to approve the eligible listings.")
        return

    approved, failed = [], []
    for listing_id, _ in eligible:
        begin_review(listing_id)
        try:
            _approve_relaxed(listing_id)
            approved.append(listing_id)
        except Exception as exc:  # noqa: BLE001 - report and revert, never crash the batch
            action(listing_id, "ready_for_review", reason=f"auto-approve failed: {exc}")
            failed.append((listing_id, str(exc)))

    print(f"\nApproved: {len(approved)}")
    print(f"Failed and reverted to ready_for_review: {len(failed)}")
    for lid, reason in failed:
        print(f"  {lid}: {reason}")


if __name__ == "__main__":
    main()
