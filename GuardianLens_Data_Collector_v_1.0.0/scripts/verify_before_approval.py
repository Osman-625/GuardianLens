"""One-off evidence verification pass over ready_for_review and needs_attention.

For every candidate listing: recover fields that evidence actually supports
(deterministic rules first, corroborated AI extraction second, exactly the same
conservative acceptance logic attention_evidence.py already uses for the
needs-attention repair pipeline), null out fields nothing in evidence supports,
then run the standard review gate (begin_review -> inspect_listing -> approve or
park in needs_attention). Never invents a value; never treats missing as 0.

Default mode is a dry run (no DB writes). Pass --apply to commit.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardianlens.attention_evidence import (  # noqa: E402
    corroborated_ai_proposals, deterministic_proposals, load_evidence, protected_fields,
)
from guardianlens.config import get_active_provider, provider_configured, settings  # noqa: E402
from guardianlens.db import connect, now_iso, transaction  # noqa: E402
from guardianlens.extraction_contract import EXTRACTION_SCHEMA, normalize_extracted_listing  # noqa: E402
from guardianlens.pii import is_placeholder_value  # noqa: E402
from guardianlens.processor import _extractor_identity, default_extractor  # noqa: E402
from guardianlens import review  # noqa: E402
from guardianlens.review import _finish_review_session, _require_active_review  # noqa: E402
from guardianlens.states import transition as state_transition  # noqa: E402
from guardianlens.validation import (  # noqa: E402
    REQUIRED_FIELDS, TEXT_LIMITS, inspect_approved_duplicates, inspect_product_images, validate_fields,
)

TEXT_FIELDS = set(TEXT_LIMITS)
NUMERIC_SELLER_FIELDS = {"account_age_days", "seller_rating", "review_count", "active_listing_count"}
CANDIDATE_STATUSES = ("ready_for_review", "needs_attention")


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _gap_fields(row: dict) -> set[str]:
    """Every EXTRACTION_SCHEMA field that is missing, blank, placeholder, or an
    unverified sentinel zero -- i.e. every field this pass should re-check."""
    gaps = set()
    for field in EXTRACTION_SCHEMA:
        value = row.get(field)
        if _blank(value):
            gaps.add(field)
        elif field in TEXT_FIELDS and isinstance(value, str) and is_placeholder_value(value):
            gaps.add(field)
        elif field in NUMERIC_SELLER_FIELDS and value == 0:
            gaps.add(field)  # re-confirm: could be a genuine stated zero or a stale default
    return gaps


def _approval_blockers(con, row: dict) -> list[str]:
    """Exact mirror of review._approve_in_transaction's gate, read-only.

    inspect_listing() is a broader dashboard helper (it also surfaces
    non-blocking seller-signal gaps and unresolved operational warnings) and is
    not what approve() actually checks -- this must match approve() precisely,
    not the dashboard's superset.
    """
    findings = validate_fields(row)
    blockers = []
    if any(item["code"] == "pii" for item in findings):
        blockers.append("pii")
    for key in REQUIRED_FIELDS:
        if key == "location_state":
            continue
        if any(item["code"] == "missing_field" and item["field"] == key for item in findings):
            blockers.append(f"missing_field:{key}")
    if any(item["code"] == "placeholder_value" for item in findings):
        blockers.append("placeholder_value:" + ",".join(sorted(
            item["field"] for item in findings if item["code"] == "placeholder_value"
        )))
    if any(item["code"] == "category" for item in findings):
        blockers.append("category")
    invalid = next((item for item in findings if item["code"] in {"invalid_type", "invalid_range"}), None)
    if invalid:
        blockers.append(f"invalid_value:{invalid['field']}")
    image_findings = inspect_product_images(con, row["listing_id"], row["platform"])
    if image_findings:
        blockers.append("images:" + image_findings[0]["message"])
    duplicates = inspect_approved_duplicates(con, row)
    if duplicates:
        blockers.append("duplicate:" + duplicates[0]["code"])
    return blockers


class Budget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.spent = 0

    def available(self) -> bool:
        return self.spent < self.limit

    def spend(self) -> None:
        self.spent += 1


def _plan(con, row: dict, budget: Budget, use_ai: bool) -> dict:
    """Pure planning: no writes. Returns the proposed updates and bookkeeping."""
    evidence = load_evidence(row)
    protected = protected_fields(con, row["listing_id"])
    gaps = _gap_fields(row) - protected
    proposals = deterministic_proposals(row, evidence, gaps) if gaps else {}
    remaining = gaps - set(proposals)
    provider_failed = False
    # Only worth a provider call if at least one remaining field has a matching
    # evidence source -- e.g. a seller-only gap with no captured seller text/
    # screenshot can never be corroborated, so don't spend a call finding that out.
    seller_gaps = remaining & NUMERIC_SELLER_FIELDS
    listing_gaps = remaining - NUMERIC_SELLER_FIELDS
    ai_eligible = bool(
        remaining and evidence.get("screenshot_path")
        and ((seller_gaps and evidence["seller_text"]) or (listing_gaps and evidence["listing_text"]))
    )
    if remaining and use_ai and ai_eligible and budget.available() and provider_configured(get_active_provider()):
        try:
            extractor = default_extractor()
            extracted = normalize_extracted_listing(extractor.extract(
                evidence["screenshot_path"], row["platform"], row["page_title"],
                [entry["name"] for entry in settings.categories()], source_url=row["source_url"],
                visible_text=evidence["listing_text"], seller_visible_text=evidence["seller_text"],
                captured_at=evidence.get("seller_captured_at") or row["captured_at"],
            ))
            proposals.update(corroborated_ai_proposals(row, evidence, remaining, extracted, _extractor_identity(extractor)))
            budget.spend()
        except Exception as exc:  # provider/network/parsing failure; leave the gap for human review
            provider_failed = True
            remaining = remaining  # noqa: PLW0127 (explicit: unresolved by AI, unchanged)
    updates: dict = {}
    recovered: list[str] = []
    nulled: list[str] = []
    for field in gaps:
        if field in proposals:
            value = proposals[field]["value"]
            if row.get(field) != value:
                updates[field] = value
                recovered.append(field)
        else:
            current = row.get(field)
            if not _blank(current):
                # Present but unverifiable (placeholder text or an unconfirmed sentinel
                # zero) and no evidence supports a real value -- clear it, never fabricate.
                updates[field] = None
                nulled.append(field)
    return {
        "evidence": evidence, "gaps": gaps, "proposals": proposals, "updates": updates,
        "recovered": recovered, "nulled": nulled, "provider_failed": provider_failed,
        "ai_eligible": ai_eligible and bool(remaining if not proposals else True),
    }


def _park_needs_attention(listing_id: str, reason: str) -> None:
    """Close an open review session and park the record back in needs_attention.

    review.action() only exposes rejected/skipped/flagged/ready_for_review as
    human review outcomes -- under_review -> needs_attention is a state
    states.py allows (it's how the attention agent returns a record for more
    repair) but review.py never wires it up as a callable action. Mirror
    exactly what action() does for its other targets instead of guessing.
    """
    with transaction() as con:
        _require_active_review(con, listing_id)
        state_transition(listing_id, "needs_attention", reason, con=con)
        duration = _finish_review_session(con, listing_id)
        con.execute(
            "INSERT INTO review_actions(review_action_id,listing_id,action,finished_at,duration_seconds,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), listing_id, "needs_attention", now_iso(), duration, now_iso()),
        )


def _apply(listing_id: str, plan: dict) -> None:
    if plan["updates"]:
        detail = []
        if plan["recovered"]:
            detail.append("recovered " + ", ".join(sorted(plan["recovered"])) + " from captured evidence")
        if plan["nulled"]:
            detail.append("cleared " + ", ".join(sorted(plan["nulled"])) + " (no verifiable value in evidence)")
        reason = "Evidence verification pass: " + "; ".join(detail)
        review.edit_listing(listing_id, plan["updates"], reason=reason[:2000])


def process_one(listing_id: str, budget: Budget, use_ai: bool, apply: bool, resume: bool = False) -> dict:
    con = connect()
    try:
        row = con.execute("SELECT * FROM listings WHERE listing_id=?", (listing_id,)).fetchone()
        expected_statuses = ("under_review",) if resume else CANDIDATE_STATUSES
        if not row or row["status"] not in expected_statuses:
            return {"listing_id": listing_id, "outcome": "skipped_state_changed"}
        row = dict(row)
        origin = row["status"]
        session = con.execute(
            "SELECT 1 FROM review_actions WHERE listing_id=? AND action='review_session' AND finished_at IS NULL",
            (listing_id,),
        ).fetchone()
        if resume and not session:
            return {"listing_id": listing_id, "origin": origin, "outcome": "skipped_no_open_session"}
        if not resume and session:
            return {"listing_id": listing_id, "origin": origin, "outcome": "skipped_active_session"}
        plan = _plan(con, row, budget, use_ai)
    finally:
        con.close()

    result = {
        "listing_id": listing_id, "origin": origin, "recovered": plan["recovered"],
        "nulled": plan["nulled"], "provider_failed": plan["provider_failed"],
    }
    if not apply:
        con = connect()
        try:
            candidate = dict(row)
            candidate.update(plan["updates"])
            blockers = _approval_blockers(con, candidate)
        finally:
            con.close()
        result["outcome"] = "would_approve" if not blockers else "would_need_attention"
        result["remaining_findings"] = blockers
        return result

    if not resume:
        try:
            review.begin_review(listing_id)
        except ValueError as exc:
            result["outcome"] = "unverifiable"
            result["reason"] = f"could not open review session: {exc}"
            return result

    try:
        _apply(listing_id, plan)
        try:
            review.approve(listing_id)
            result["outcome"] = "approved"
        except ValueError as exc:
            _park_needs_attention(listing_id, f"Evidence verification pass: blockers remain - {exc}")
            result["outcome"] = "needs_attention"
            result["remaining_findings"] = [str(exc)]
    except Exception as exc:
        try:
            _park_needs_attention(listing_id, f"Evidence verification pass: could not approve - {exc}")
        except Exception:
            pass
        result["outcome"] = "needs_attention"
        result["reason"] = str(exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit changes (default: dry run)")
    parser.add_argument("--use-ai", action="store_true", help="Allow corroborated AI extraction for unresolved gaps")
    parser.add_argument("--api-call-budget", type=int, default=100)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--listing-id", action="append", dest="listing_ids")
    parser.add_argument("--resume", action="store_true",
                         help="Reprocess listings already stuck under_review with an open session from a prior run")
    parser.add_argument("--out", default=None, help="Write full per-record JSON results here")
    args = parser.parse_args()

    statuses = ("under_review",) if args.resume else CANDIDATE_STATUSES
    con = connect()
    try:
        placeholders = ",".join("?" * len(statuses))
        query = f"SELECT listing_id,status FROM listings WHERE status IN ({placeholders}) ORDER BY captured_at,listing_id"
        rows = con.execute(query, statuses).fetchall()
    finally:
        con.close()
    ids = [r["listing_id"] for r in rows]
    if args.listing_ids:
        wanted = set(args.listing_ids)
        ids = [i for i in ids if i in wanted]
    if args.limit:
        ids = ids[: args.limit]

    budget = Budget(args.api_call_budget)
    results = []
    for listing_id in ids:
        results.append(process_one(listing_id, budget, args.use_ai, args.apply, resume=args.resume))

    summary: dict = {"total": len(results), "api_calls_used": budget.spent}
    for r in results:
        summary[r["outcome"]] = summary.get(r["outcome"], 0) + 1
    field_recovered = {}
    field_nulled = {}
    for r in results:
        for f in r.get("recovered", []):
            field_recovered[f] = field_recovered.get(f, 0) + 1
        for f in r.get("nulled", []):
            field_nulled[f] = field_nulled.get(f, 0) + 1
    summary["fields_recovered_total"] = sum(field_recovered.values())
    summary["fields_nulled_total"] = sum(field_nulled.values())
    summary["fields_recovered_by_field"] = field_recovered
    summary["fields_nulled_by_field"] = field_nulled
    summary["by_origin"] = {}
    for r in results:
        origin = r.get("origin", "unknown")
        summary["by_origin"].setdefault(origin, {})
        summary["by_origin"][origin][r["outcome"]] = summary["by_origin"][origin].get(r["outcome"], 0) + 1

    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
