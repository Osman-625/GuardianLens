from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent

PRIORITY_ORDER = {
    "likely_scam": 0,
    "suspicious": 1,
    "conflicting": 2,        # critical/strong rules fired alongside a nonzero trust_score
    "high_risk_high_trust": 3,
    "insufficient_evidence": 4,
    "likely_legitimate_sample": 5,
}


def _priority_bucket(row: dict) -> str:
    label = row["rule_label"]
    critical = int(float(row.get("critical_rule_count") or 0))
    strong = int(float(row.get("strong_rule_count") or 0))
    trust = float(row.get("trust_score") or 0)
    if label == "likely_scam":
        return "likely_scam"
    if label == "suspicious":
        return "suspicious"
    if (critical > 0 or strong > 0) and trust >= 3:
        return "high_risk_high_trust"
    if label == "insufficient_evidence":
        return "insufficient_evidence"
    return "likely_legitimate_sample"


def build_queue(weak_annotations_path, random_seed: int = 42, legitimate_sample_rate: float = 1.0) -> list[dict]:
    """Default legitimate_sample_rate=1.0 means FULL COVERAGE - every row from
    weak_annotations.csv comes through, just re-ordered by review priority. Lower this only if
    the dataset grows large enough that even a re-ordered full list is impractical; the default
    exists so no row is silently dropped from what the human can choose to review."""
    with open(weak_annotations_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    buckets: dict[str, list[dict]] = {k: [] for k in PRIORITY_ORDER}
    for row in rows:
        buckets[_priority_bucket(row)].append(row)

    if legitimate_sample_rate < 1.0:
        rng = random.Random(random_seed)
        legit_bucket = buckets["likely_legitimate_sample"]
        sample_size = max(1, int(len(legit_bucket) * legitimate_sample_rate)) if legit_bucket else 0
        buckets["likely_legitimate_sample"] = rng.sample(legit_bucket, min(sample_size, len(legit_bucket)))

    queue = []
    for bucket_name in sorted(PRIORITY_ORDER, key=PRIORITY_ORDER.get):
        queue.extend(buckets[bucket_name])
    return queue


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weak-annotations", default=str(WORKSPACE / "output" / "weak_annotations.csv"))
    parser.add_argument("--out", default=str(WORKSPACE / "reports" / "review_queue.csv"))
    parser.add_argument("--legitimate-sample-rate", type=float, default=1.0,
                         help="1.0 (default) = full coverage, no rows dropped. Lower only if you "
                              "explicitly want to sample the likely_legitimate bucket.")
    args = parser.parse_args()

    queue = build_queue(args.weak_annotations, legitimate_sample_rate=args.legitimate_sample_rate)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(queue[0].keys()))
        writer.writeheader()
        writer.writerows(queue)
    print(f"Wrote {len(queue)} rows to {out_path}")


if __name__ == "__main__":
    main()
