from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MatchResult:
    category: str
    strength: str
    matched_phrases: tuple[str, ...]


def _phrase_regex(phrase: str) -> re.Pattern:
    # Phrases already containing regex metacharacters (e.g. "\\btac\\b") are used as-is;
    # plain phrases get \b-bounded automatically so "tac" never matches inside "contact".
    if any(ch in phrase for ch in r"\.^$*+?{}[]|()"):
        return re.compile(phrase, re.IGNORECASE)
    escaped = re.escape(phrase)
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


def match_keywords(text: str, patterns: dict) -> list[MatchResult]:
    if not text:
        return []
    results: list[MatchResult] = []
    for category, strengths in patterns.items():
        for strength, phrases in strengths.items():
            hits = []
            for phrase in phrases:
                match = _phrase_regex(phrase).search(text)
                if match:
                    # Record the actual substring found in the text (e.g. "TAC"), not the
                    # pattern definition (e.g. "\\btac\\b") - the latter is meaningless as
                    # human-facing evidence.
                    hits.append(match.group())
            if hits:
                results.append(MatchResult(category=category, strength=strength, matched_phrases=tuple(hits)))
    return results


def has_combo(matches: list[MatchResult], required_categories: list[str]) -> bool:
    present = {m.category for m in matches}
    return all(c in present for c in required_categories)
