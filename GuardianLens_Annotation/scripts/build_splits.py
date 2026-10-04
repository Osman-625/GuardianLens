"""Leakage-safe train/validation/test/clean_validation split preparation (spec section 16).

Does NOT train or evaluate any model. Splits by duplicate/repost GROUP, not by individual row, so
near-duplicate or reposted listings never cross a split boundary. Deterministic (seed=42).
`clean_validation` is the subset of `validation` whose group has exactly one member (no
duplicate/repost partner anywhere in the dataset) -- useful for a leakage-free validation read.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent


def assign_splits(rows: list[dict], group_of: dict[str, str], seed: int = 42,
                   ratios: dict[str, float] | None = None) -> dict[str, list[dict]]:
    ratios = ratios or {"train": 0.7, "validation": 0.15, "test": 0.15}

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[group_of.get(r["listing_id"], r["listing_id"])].append(r)

    group_ids = sorted(groups.keys())
    rng = random.Random(seed)
    rng.shuffle(group_ids)

    n = len(group_ids)
    n_train = int(n * ratios["train"])
    n_val = int(n * ratios["validation"])

    train_groups = set(group_ids[:n_train])
    val_groups = set(group_ids[n_train:n_train + n_val])
    test_groups = set(group_ids[n_train + n_val:])

    splits: dict[str, list[dict]] = {"train": [], "validation": [], "test": [], "clean_validation": []}
    for gid in train_groups:
        splits["train"].extend(groups[gid])
    for gid in val_groups:
        splits["validation"].extend(groups[gid])
        if len(groups[gid]) == 1:
            splits["clean_validation"].extend(groups[gid])
    for gid in test_groups:
        splits["test"].extend(groups[gid])

    return splits


def _load_dedup_groups(dedup_summary: dict) -> dict[str, str]:
    """Real key names verified directly against reports/dataset_validation_summary.json
    (2026-09-17): near_duplicate_cross_listing_groups (list of dicts with a listing_ids key)
    and possible_repost_candidates (list of plain listing_id-string lists, no dict wrapper)."""
    group_of: dict[str, str] = {}
    for gi, group in enumerate(dedup_summary.get("near_duplicate_cross_listing_groups", [])):
        for lid in group.get("listing_ids", []):
            group_of[lid] = f"dup_group_{gi}"
    for gi, listing_ids in enumerate(dedup_summary.get("possible_repost_candidates", [])):
        for lid in listing_ids:
            group_of.setdefault(lid, f"repost_group_{gi}")
    return group_of


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--final", required=True, type=Path)
    parser.add_argument("--dedup-summary", default=str(WORKSPACE / "reports" / "dataset_validation_summary.json"), type=Path)
    parser.add_argument("--out-dir", default=str(WORKSPACE / "data" / "final_labeled" / "splits"), type=Path)
    args = parser.parse_args()

    with args.final.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    dedup = json.loads(args.dedup_summary.read_text(encoding="utf-8"))
    group_of = _load_dedup_groups(dedup)

    splits = assign_splits(rows, group_of, seed=42)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, split_rows in splits.items():
        path = args.out_dir / f"{name}.csv"
        if not split_rows:
            path.write_text("", encoding="utf-8")
            continue
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(split_rows[0].keys()))
            w.writeheader()
            w.writerows(split_rows)

    manifest = {
        "seed": 42,
        "counts": {name: len(rs) for name, rs in splits.items()},
        "split_hash": hashlib.sha256(
            json.dumps(
                {n: sorted(r["listing_id"] for r in rs) for n, rs in splits.items()},
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    }
    (args.out_dir / "split_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
