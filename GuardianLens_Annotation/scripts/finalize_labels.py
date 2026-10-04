"""Apply the documented finalization policy (this task's spec section 13).

Policy, in priority order:
1. If a human recorded human_final_label for a listing -> final_label = that, source = human_review.
2. Else if Claude and Codex unanimously agree -> final_label = that agreed label, source = unanimous_ai.
3. Else -> final_label = None, source = unresolved (never silently defaulted from rule_label,
   claude, or codex alone).

rule_label is never a final_label_source -- the rule engine is a reference input to human review
(via the consensus join / review queue), never a finalization authority on its own.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent


def finalize(consensus_rows: list[dict], reviewed_rows: list[dict]) -> list[dict]:
    reviewed_by_id = {r["listing_id"]: r for r in reviewed_rows if r.get("human_final_label", "").strip()}

    out = []
    for row in consensus_rows:
        lid = row["listing_id"]
        if lid in reviewed_by_id:
            final_label = reviewed_by_id[lid]["human_final_label"].strip()
            source = "human_review"
        elif row.get("claude_label") and row.get("codex_label") and row["claude_label"] == row["codex_label"]:
            final_label = row["claude_label"]
            source = "unanimous_ai"
        else:
            final_label = None
            source = "unresolved"

        out.append({"listing_id": lid, "final_label": final_label, "final_label_source": source})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consensus", required=True, type=Path)
    parser.add_argument("--reviewed", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    with args.consensus.open(encoding="utf-8-sig", newline="") as f:
        consensus_rows = list(csv.DictReader(f))
    with args.reviewed.open(encoding="utf-8-sig", newline="") as f:
        reviewed_rows = list(csv.DictReader(f))

    out = finalize(consensus_rows, reviewed_rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["listing_id", "final_label", "final_label_source"])
        w.writeheader()
        w.writerows(out)

    unresolved = sum(1 for r in out if r["final_label_source"] == "unresolved")
    print(f"Wrote {len(out)} rows. Unresolved (need human review before freeze): {unresolved}")


if __name__ == "__main__":
    main()
