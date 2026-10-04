from __future__ import annotations

from collections import defaultdict
from statistics import median

MIN_COMPARABLE_SAMPLE = 5


def compute_category_medians(rows: list[dict]) -> dict[tuple[str, str], float]:
    """category+platform -> median price, only for groups with >= MIN_COMPARABLE_SAMPLE prices."""
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        if row.get("price_missing") == "True" or not row.get("price"):
            continue
        key = (row.get("category"), row.get("platform"))
        try:
            buckets[key].append(float(row["price"]))
        except (TypeError, ValueError):
            continue
    return {k: median(v) for k, v in buckets.items() if len(v) >= MIN_COMPARABLE_SAMPLE}


def price_ratio_and_score(price: float | None, category: str, platform: str,
                           medians: dict[tuple[str, str], float]) -> tuple[float | None, str | None]:
    if price is None:
        return None, None
    m = medians.get((category, platform))
    if m is None or m == 0:
        return None, None
    ratio = price / m
    if ratio < 0.25:
        return ratio, "very_strong"
    if ratio < 0.40:
        return ratio, "strong"
    if ratio < 0.60:
        return ratio, "medium"
    if ratio < 0.75:
        return ratio, "weak"
    return ratio, None
