"""Control the running collector's attention agent without exposing its token."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from guardianlens.config import settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "repair", "status", "pause",
                                           "resume", "stop", "recover-sellers",
                                           "process-recovered"))
    parser.add_argument("--run-id")
    parser.add_argument("--recovery-batch-id")
    parser.add_argument("--listing-id", action="append", dest="listing_ids")
    parser.add_argument("--platform", choices=("mudah", "carousell"))
    parser.add_argument("--reason")
    parser.add_argument("--item-limit", type=int)
    parser.add_argument("--api-call-limit", type=int, default=25)
    parser.add_argument("--time-limit-minutes", type=int, default=60)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()

    def request(path: str, payload: dict | None = None) -> dict:
        headers = {}
        body = None
        if payload is not None:
            headers = {"Content-Type": "application/json",
                       "X-GuardianLens-Token": settings.token_path.read_text().strip()}
            body = json.dumps(payload).encode()
        req = Request(f"http://127.0.0.1:{settings.port}" + path, data=body, headers=headers)
        with urlopen(req, timeout=60) as response:
            return json.load(response)

    def summarize(snapshot: dict) -> dict:
        return {key: snapshot[key] for key in ("run", "batch", "progress") if key in snapshot}

    try:
        if args.command in {"inspect", "repair", "process-recovered"}:
            if args.command == "process-recovered" and not args.recovery_batch_id:
                parser.error("process-recovered requires --recovery-batch-id")
            payload = {"mode": "inspect" if args.command == "inspect" else "repair",
                       "listing_ids": args.listing_ids, "platform": args.platform,
                       "reason": args.reason, "item_limit": args.item_limit,
                       "api_call_limit": args.api_call_limit,
                       "time_limit_minutes": args.time_limit_minutes, "watch": args.watch,
                       "recovery_batch_id": args.recovery_batch_id}
            snapshot = request("/api/attention/start", payload)
        elif args.command == "status":
            suffix = "?run_id=" + quote(args.run_id, safe="") if args.run_id else ""
            snapshot = request("/api/attention/status" + suffix)
        else:
            if not args.run_id:
                parser.error(f"{args.command} requires --run-id")
            run_id = quote(args.run_id, safe="")
            endpoint = (f"/api/attention/{run_id}/recover-sellers"
                        if args.command == "recover-sellers"
                        else f"/api/attention/{run_id}/command/{args.command}")
            snapshot = request(endpoint, {})
        print(json.dumps(summarize(snapshot), ensure_ascii=True), flush=True)
        while args.wait and snapshot.get("run", {}).get("status") in {"running", "stopping"}:
            time.sleep(2)
            run_id = quote(snapshot["run"]["run_id"], safe="")
            updated = request("/api/attention/status?run_id=" + run_id)
            if summarize(updated) != summarize(snapshot):
                print(json.dumps(summarize(updated), ensure_ascii=True), flush=True)
            snapshot = updated
        return 1 if snapshot.get("run", {}).get("status") == "failed" else 0
    except HTTPError as exc:
        try:
            detail = json.load(exc).get("detail", "request rejected")
        except (ValueError, AttributeError):
            detail = "request rejected"
        print(f"Collector returned {exc.code}: {detail}", file=sys.stderr)
        return 1
    except (URLError, OSError):
        print(f"Cannot reach the collector on port {settings.port}; start it with run.bat.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
