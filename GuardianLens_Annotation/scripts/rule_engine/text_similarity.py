from __future__ import annotations

import re
from collections import defaultdict

_WS_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+")


def normalize_for_comparison(text: str) -> str:
    text = text.lower()
    text = _URL_RE.sub("[URL]", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _shingles(text: str, k: int = 5) -> set[str]:
    words = text.split()
    if len(words) < k:
        return {text} if text else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def jaccard_similarity(shingles_a: set[str], shingles_b: set[str]) -> float:
    if not shingles_a or not shingles_b:
        return 0.0
    intersection = len(shingles_a & shingles_b)
    if intersection == 0:
        return 0.0
    return intersection / len(shingles_a | shingles_b)


def find_near_duplicate_groups(listing_id_to_text: dict[str, str], threshold: float = 0.6) -> dict[str, list[str]]:
    """O(n^2) pairwise comparison over precomputed shingle sets - fine for ~2,209 rows
    (shingle sets are computed once per listing, not per pair, so the cost is O(n) shingling +
    O(n^2) set-intersection, which finishes in seconds, not the O(n^2 * shingling) a naive
    per-pair implementation would incur)."""
    ids = [lid for lid, text in listing_id_to_text.items() if text]
    shingle_cache = {lid: _shingles(listing_id_to_text[lid]) for lid in ids}
    result: dict[str, list[str]] = defaultdict(list)
    for i, lid_a in enumerate(ids):
        shingles_a = shingle_cache[lid_a]
        if not shingles_a:
            continue
        for lid_b in ids[i + 1:]:
            shingles_b = shingle_cache[lid_b]
            if not shingles_b:
                continue
            if jaccard_similarity(shingles_a, shingles_b) >= threshold:
                result[lid_a].append(lid_b)
                result[lid_b].append(lid_a)
    return dict(result)
