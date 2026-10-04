from __future__ import annotations

import json
from pathlib import Path


def load_cross_listing_groups(validation_summary_path: str | Path) -> list[list[str]]:
    data = json.loads(Path(validation_summary_path).read_text(encoding="utf-8"))
    return [g["listing_ids"] for g in data.get("near_duplicate_cross_listing_groups", [])]


def build_listing_to_related(groups: list[list[str]]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for group in groups:
        group_set = set(group)
        for listing_id in group:
            mapping.setdefault(listing_id, set()).update(group_set - {listing_id})
    return mapping
