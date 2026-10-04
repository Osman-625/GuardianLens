"""Join Claude, Codex, and rule-engine annotation outputs into one per-listing consensus row.

None of the three sources is ground truth. The rule engine's own label vocabulary
(likely_legitimate/likely_scam/suspicious/insufficient_evidence, see
scripts/rule_engine/evaluator.py -- unchanged by this script) is mapped onto the canonical
vocabulary here (RULE_LABEL_MAP) so comparisons are meaningful; the mapping is documented
identically in annotation/guidelines/LABEL_SCHEMA.json.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

RULE_LABEL_MAP = {
    "likely_legitimate": "legitimate",
    "likely_scam": "scam_fraud",
    "suspicious": "suspicious",
    "insufficient_evidence": "insufficient_evidence",
}

SEVERE_PAIRS = {("legitimate", "scam_fraud"), ("scam_fraud", "legitimate")}


def _load(path: Path) -> dict[str, dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return {row["listing_id"]: row for row in csv.DictReader(f)}


def build_consensus(claude_csv: Path, codex_csv: Path, rule_csv: Path) -> list[dict]:
    claude_rows = _load(claude_csv)
    codex_rows = _load(codex_csv)
    rule_rows = _load(rule_csv)

    all_ids = sorted(set(claude_rows) | set(codex_rows) | set(rule_rows))
    out = []
    for lid in all_ids:
        c = claude_rows.get(lid, {})
        x = codex_rows.get(lid, {})
        r = rule_rows.get(lid, {})

        claude_label = c.get("label", "").strip() or None
        codex_label = x.get("label", "").strip() or None
        rule_label_raw = r.get("rule_label", "").strip() or None
        rule_label_mapped = RULE_LABEL_MAP.get(rule_label_raw) if rule_label_raw else None

        ai_agreement = bool(claude_label and codex_label and claude_label == codex_label)
        three_way_agreement = bool(
            claude_label and codex_label and rule_label_mapped
            and claude_label == codex_label == rule_label_mapped
        )
        rule_ai_conflict = bool(ai_agreement and rule_label_mapped and claude_label != rule_label_mapped)
        severe = bool(claude_label and codex_label and (claude_label, codex_label) in SEVERE_PAIRS)

        out.append({
            "listing_id": lid,
            "claude_label": claude_label,
            "claude_confidence": c.get("confidence", "").strip() or None,
            "codex_label": codex_label,
            "codex_confidence": x.get("confidence", "").strip() or None,
            "rule_label_raw": rule_label_raw,
            "rule_label_mapped": rule_label_mapped,
            "rule_confidence": r.get("label_confidence", "").strip() or None,
            "ai_agreement": ai_agreement,
            "three_way_agreement": three_way_agreement,
            "rule_ai_conflict": rule_ai_conflict,
            "severe_disagreement": severe,
        })
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claude", required=True, type=Path)
    parser.add_argument("--codex", required=True, type=Path)
    parser.add_argument("--rule", default=str(WORKSPACE / "output" / "weak_annotations.csv"), type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    rows = build_consensus(args.claude, args.codex, args.rule)
    if not rows:
        print("No rows to write (all three input files empty/nonexistent).")
        return
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} consensus rows to {args.out}")


if __name__ == "__main__":
    main()
