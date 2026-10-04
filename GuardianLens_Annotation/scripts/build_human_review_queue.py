"""Build the Pass 3 prioritized human review queue from the 3-way consensus join.

This is distinct from the existing scripts/build_review_queue.py, which orders listings by
rule_label alone (single source, kept unchanged as rule-only triage -- see
reports/annotation_workflow_audit.md, Method 4). This script consumes
scripts/compute_consensus.py's output (Claude + Codex + rule engine, joined) and assigns a
P0-P4 priority per this task's spec section 11.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

LOW_CONFIDENCE_THRESHOLD = 3.0


def _conf(row: dict, key: str) -> float | None:
    v = row.get(key)
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def assign_priority(row: dict) -> tuple[str, str]:
    if row.get("severe_disagreement"):
        return "P0", "severe contradiction: claude vs codex opposite ends (legitimate/scam_fraud)"

    claude_label = row.get("claude_label")
    codex_label = row.get("codex_label")
    if claude_label and codex_label and claude_label != codex_label:
        return "P1", f"AI disagreement: claude={claude_label} vs codex={codex_label}"

    if row.get("rule_ai_conflict"):
        return "P2", "claude/codex agree but rule engine disagrees"

    claude_conf = _conf(row, "claude_confidence")
    codex_conf = _conf(row, "codex_confidence")
    low_confidence = (claude_conf is not None and claude_conf < LOW_CONFIDENCE_THRESHOLD) or \
                      (codex_conf is not None and codex_conf < LOW_CONFIDENCE_THRESHOLD)
    insufficient = claude_label == "insufficient_evidence" or codex_label == "insufficient_evidence"
    needs_review_flag = row.get("annotation_readiness") == "needs_review"
    possible_duplicate = row.get("duplicate_status") == "possible_duplicate"

    if low_confidence or insufficient or needs_review_flag or possible_duplicate:
        reasons = []
        if low_confidence:
            reasons.append("low confidence")
        if insufficient:
            reasons.append("insufficient_evidence called")
        if needs_review_flag:
            reasons.append("annotation_readiness=needs_review")
        if possible_duplicate:
            reasons.append("possible_duplicate")
        return "P3", "; ".join(reasons)

    return "P4", "unanimous, high confidence, clean readiness -- QC sample candidate"


def build_queue(consensus_rows: list[dict], qc_sample_rate: float = 0.05, seed: int = 42) -> list[dict]:
    queue = []
    p4_rows = []
    for row in consensus_rows:
        priority, reason = assign_priority(row)
        out_row = dict(row)
        out_row["review_priority"] = priority
        out_row["review_reason"] = reason
        out_row["requires_human_review"] = priority != "P4"
        if priority == "P4":
            p4_rows.append(out_row)
        else:
            queue.append(out_row)

    rng = random.Random(seed)
    sample_size = max(1, int(len(p4_rows) * qc_sample_rate)) if p4_rows else 0
    qc_sample = rng.sample(p4_rows, min(sample_size, len(p4_rows))) if p4_rows else []
    qc_sample_ids = {id(row) for row in qc_sample}
    for row in p4_rows:
        if id(row) in qc_sample_ids:
            row["requires_human_review"] = True
            row["review_reason"] = "QC stratified sample of unanimous case: " + row["review_reason"]

    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
    queue.extend(p4_rows)
    queue.sort(key=lambda r: priority_order[r["review_priority"]])
    return queue


def _to_bool(value) -> bool:
    return str(value).strip().lower() == "true"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consensus", required=True, type=Path)
    parser.add_argument("--out", default=str(WORKSPACE / "reports" / "human_review_queue.csv"), type=Path)
    parser.add_argument("--qc-sample-rate", type=float, default=0.05)
    args = parser.parse_args()

    with args.consensus.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in ("ai_agreement", "three_way_agreement", "rule_ai_conflict", "severe_disagreement"):
            row[key] = _to_bool(row.get(key))

    if not rows:
        print("No consensus rows to queue.")
        return

    queue = build_queue(rows, qc_sample_rate=args.qc_sample_rate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(queue[0].keys()))
        w.writeheader()
        w.writerows(queue)

    counts: dict[str, int] = {}
    for row in queue:
        counts[row["review_priority"]] = counts.get(row["review_priority"], 0) + 1
    print(f"Wrote {len(queue)} rows to {args.out}. Priority counts: {counts}")


if __name__ == "__main__":
    main()
