"""Verify approved listings against their live marketplace pages.

Standalone maintenance script -- runs independently of any Claude session. Fetches
each listing's live page directly (httpx, not routed through any AI provider),
compares deterministically against structured data already embedded in the page
(Carousell JSON-LD / Mudah __NEXT_DATA__), and escalates only real disagreements to
OpenAI for adjudication. Never mutates `listings` -- results go to
`live_verification_runs`/`live_verification_items` and a JSON report only.

Usage:
    python scripts/verify_approved_live.py                      # verify all approved listings
    python scripts/verify_approved_live.py --limit 30            # first 30 (by listing_id)
    python scripts/verify_approved_live.py --platform carousell
    python scripts/verify_approved_live.py --listing-id abc --listing-id def
    python scripts/verify_approved_live.py --recheck-days 0      # ignore prior checks, recheck everyone selected
    python scripts/verify_approved_live.py --resume <run-id>     # continue an interrupted run
    python scripts/verify_approved_live.py --report-only         # rebuild the report from the latest run, no fetching
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardianlens.config import settings  # noqa: E402
from guardianlens.db import connect, now_iso, transaction  # noqa: E402
from guardianlens.errors import ProviderOperationError  # noqa: E402
import guardianlens.live_verification as lv  # noqa: E402

REPORT_PATH = settings.data_dir / "reports" / "live_verification.json"


def _select_candidates(con, args) -> list[dict]:
    query = "SELECT * FROM listings WHERE status='approved'"
    params: list = []
    if args.platform:
        query += " AND platform=?"
        params.append(args.platform)
    if args.listing_ids:
        query += f" AND listing_id IN ({','.join('?' for _ in args.listing_ids)})"
        params.extend(args.listing_ids)
    query += " ORDER BY listing_id"
    rows = [dict(r) for r in con.execute(query, params)]

    if args.recheck_days > 0:
        cutoff = now_iso()
        import datetime
        cutoff_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=args.recheck_days)
        filtered = []
        for row in rows:
            checked_at = lv.last_checked_at(con, row["listing_id"])
            if checked_at is None:
                filtered.append(row)
                continue
            try:
                checked_dt = datetime.datetime.fromisoformat(checked_at)
            except ValueError:
                filtered.append(row)
                continue
            if checked_dt < cutoff_dt:
                filtered.append(row)
        rows = filtered

    if args.limit:
        rows = rows[: args.limit]
    return rows


def _already_recorded(con, run_id: str) -> set[str]:
    return {
        r["listing_id"]
        for r in con.execute("SELECT listing_id FROM live_verification_items WHERE run_id=?", (run_id,))
    }


def _write_report(con, run_id: str) -> dict:
    run = dict(con.execute("SELECT * FROM live_verification_runs WHERE run_id=?", (run_id,)).fetchone())
    items = [dict(r) for r in con.execute(
        "SELECT * FROM live_verification_items WHERE run_id=? ORDER BY checked_at", (run_id,)
    )]
    counts: dict[str, int] = {}
    findings = []
    for item in items:
        counts[item["outcome"]] = counts.get(item["outcome"], 0) + 1
        if item["outcome"] in (lv.OUTCOME_MISMATCH, lv.OUTCOME_BLOCKED, lv.OUTCOME_FETCH_FAILED):
            listing = con.execute(
                "SELECT source_url FROM listings WHERE listing_id=?", (item["listing_id"],)
            ).fetchone()
            findings.append({
                "listing_id": item["listing_id"],
                "source_url": listing["source_url"] if listing else None,
                "outcome": item["outcome"],
                "verdict": item["verdict"],
                "fields_in_disagreement": json.loads(item["fields_in_disagreement"] or "[]"),
                "details": item["details"],
                "tier": item["tier"],
            })
    report = {
        "generated_at": now_iso(),
        "run_id": run_id,
        "run_status": run["status"],
        "selection": json.loads(run["selection"]),
        "items_checked": len(items),
        "api_calls": run["api_calls"],
        "counts": counts,
        "pass": counts.get(lv.OUTCOME_MISMATCH, 0) == 0,
        "findings": findings,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    tmp = REPORT_PATH.with_name(f".{REPORT_PATH.name}.{nonce}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, REPORT_PATH)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--platform", choices=("carousell", "mudah"))
    parser.add_argument("--listing-id", action="append", dest="listing_ids")
    parser.add_argument("--recheck-days", type=int, default=30)
    parser.add_argument("--resume", dest="run_id")
    parser.add_argument("--api-call-limit", type=int, default=200)
    parser.add_argument("--rate-delay", type=float, default=lv.DEFAULT_RATE_DELAY_SECONDS)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    con = connect()
    try:
        if args.report_only:
            run_id = args.run_id
            if not run_id:
                row = con.execute(
                    "SELECT run_id FROM live_verification_runs ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if not row:
                    print("No live verification runs found yet.", file=sys.stderr)
                    return 1
                run_id = row["run_id"]
            report = _write_report(con, run_id)
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report["pass"] else 1

        candidates = _select_candidates(con, args)
        selection = {
            "platform": args.platform,
            "listing_ids": args.listing_ids,
            "recheck_days": args.recheck_days,
            "limit": args.limit,
        }

        if args.run_id:
            run_id = args.run_id
            run_row = con.execute(
                "SELECT * FROM live_verification_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if not run_row:
                print(f"No run found with id {run_id}", file=sys.stderr)
                return 1
            done = _already_recorded(con, run_id)
            candidates = [row for row in candidates if row["listing_id"] not in done]
            api_calls = run_row["api_calls"]
        else:
            with transaction() as tcon:
                run_id = lv.create_run(
                    tcon, selection=json.dumps(selection), item_limit=args.limit,
                    api_call_limit=args.api_call_limit, rate_delay_seconds=args.rate_delay,
                )
            api_calls = 0

        print(f"Run {run_id}: {len(candidates)} listing(s) to verify.", flush=True)

        client = None
        halted_message = None
        for index, row in enumerate(candidates):
            if api_calls >= args.api_call_limit:
                halted_message = f"api_call_limit ({args.api_call_limit}) reached"
                break
            try:
                if client is None and settings.openai_api_key:
                    client = lv.build_openai_client()
                comparison = lv.verify_listing(row, client=client)
            except ProviderOperationError as exc:
                if exc.classification.halt_batch:
                    halted_message = f"halted: {exc.classification.user_message}"
                    break
                comparison = lv.Comparison(
                    outcome=lv.OUTCOME_FETCH_FAILED, verdict=None,
                    details=f"adjudication failed: {exc.classification.user_message}",
                )

            api_called = comparison.tier == lv.TIER_OPENAI
            if api_called:
                api_calls += 1
            with transaction() as tcon:
                lv.record_item(tcon, run_id=run_id, listing_id=row["listing_id"], comparison=comparison, api_called=api_called)
                tcon.execute(
                    "UPDATE live_verification_runs SET api_calls=?,updated_at=? WHERE run_id=?",
                    (api_calls, now_iso(), run_id),
                )
            print(
                f"[{index + 1}/{len(candidates)}] {row['listing_id']} -> {comparison.outcome}"
                f"{' (' + comparison.details[:100] + ')' if comparison.details else ''}",
                flush=True,
            )
            if args.rate_delay > 0:
                time.sleep(args.rate_delay)

        with transaction() as tcon:
            lv.finish_run(
                tcon, run_id,
                status="failed" if halted_message else "completed",
                api_calls=api_calls, message=halted_message,
            )

        report = _write_report(con, run_id)
        print(f"\nRun {run_id} {'HALTED: ' + halted_message if halted_message else 'complete'}.")
        print(json.dumps(report["counts"], indent=2))
        if report["findings"]:
            print("\nNeeds attention:")
            for finding in report["findings"]:
                print(f"  {finding['outcome']}: {finding['listing_id']} - {finding['details']} ({finding['source_url']})")
        return 0 if report["pass"] and not halted_message else 1
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
