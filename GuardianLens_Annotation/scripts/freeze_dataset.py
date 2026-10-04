"""Freeze the finalized labeled dataset (this task's spec section 15).

Refuses to run while any row's final_label_source is still "unresolved" -- Pass 3 human review
must be complete first. Writes data/annotation_ready/ is never touched; output goes to
data/final_labeled/ only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent


def build_manifest(final_rows: list[dict], version: str) -> dict:
    return {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "row_count": len(final_rows),
        "label_distribution": dict(Counter(r["final_label"] for r in final_rows)),
        "platform_distribution": dict(Counter(r.get("platform", "unknown") for r in final_rows)),
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", required=True, type=Path)
    parser.add_argument("--listings", default=str(WORKSPACE / "data" / "annotation_ready" / "listings.csv"), type=Path)
    parser.add_argument("--out-dir", default=str(WORKSPACE / "data" / "final_labeled"), type=Path)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()

    with args.final.open(encoding="utf-8-sig", newline="") as f:
        final_rows = list(csv.DictReader(f))
    with args.listings.open(encoding="utf-8-sig", newline="") as f:
        listings_by_id = {row["listing_id"]: row for row in csv.DictReader(f)}

    for r in final_rows:
        r["platform"] = listings_by_id.get(r["listing_id"], {}).get("platform", "unknown")

    unresolved = [r for r in final_rows if r.get("final_label_source") == "unresolved"]
    if unresolved:
        print(f"REFUSING TO FREEZE: {len(unresolved)} rows still unresolved. Run Pass 3 human review first.")
        raise SystemExit(1)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"guardianlens_labeled_{args.version}.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(final_rows[0].keys()))
        w.writeheader()
        w.writerows(final_rows)

    manifest = build_manifest(final_rows, version=args.version)
    (out_dir / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    checksum_line = f"{_sha256(out_csv)}  {out_csv.name}\n"
    (out_dir / "checksums.sha256").write_text(checksum_line, encoding="utf-8")

    print(f"Froze {len(final_rows)} rows to {out_csv}")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
