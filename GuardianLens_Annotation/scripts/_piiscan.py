"""Independent PII re-audit for the annotation workspace.

This is a deliberately separate, minimal reimplementation -- NOT an import of
the source repo's `pii.py`. The point of this workspace's validation pass is
to independently re-check the source's own PII scrubbing, not to trust it
blindly by reusing its exact code path. If both implementations agree the
text is clean, that's a much stronger signal than one scrubber checking its
own work.

Returns pattern-type labels found, never the matched text itself (the report
should say *that* a phone-shaped string was found in listing X, field Y --
not print the phone number into a report file).
"""

from __future__ import annotations

import re

PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "my_phone": re.compile(r"(?:\+?60|0)[\s-]?1[0-9](?:[\s-]?\d){7,8}\b"),
    "generic_phone_run": re.compile(r"(?<!\d)\d{9,12}(?!\d)"),
    "whatsapp_telegram_link": re.compile(
        r"(?:wa\.me/|api\.whatsapp\.com/|t\.me/)\S+", re.IGNORECASE
    ),
    "contact_handle_phrase": re.compile(
        r"\b(?:whatsapp|telegram|wechat|dm me|call me|contact me)\b[:\s]*@?\w*",
        re.IGNORECASE,
    ),
    "social_handle": re.compile(r"(?<!\w)@[A-Za-z0-9_.]{3,30}\b"),
    "address_hint": re.compile(
        r"\b(?:Jalan|Lorong|Persiaran|No\.?\s?\d+[A-Za-z]?,)\b", re.IGNORECASE
    ),
}


def scrub_findings(text: str | None) -> list[str]:
    """Return the list of pattern-type names that matched in `text`."""
    if not text:
        return []
    hits: list[str] = []
    for label, pattern in PATTERNS.items():
        if pattern.search(text):
            hits.append(label)
    return hits


# address_hint deliberately excluded from auto-redaction: manual review of
# every hit in this dataset (see reports/dataset_validation_report.md) showed
# these are public meetup-location mentions (malls, plazas, named streets --
# standard content in Malaysian marketplace listings for arranging a meeting
# point), not personal home addresses. Redacting them would destroy useful,
# non-sensitive context for annotators without any privacy benefit.
REDACT_LABELS = {
    "email", "my_phone", "whatsapp_telegram_link", "contact_handle_phrase", "social_handle",
}


def redact(text: str | None) -> tuple[str | None, list[str]]:
    """Return (redacted_text, pattern_types_found_and_redacted). Only used on COPIES."""
    if not text:
        return text, []
    all_hits = scrub_findings(text)
    redacted = text
    redacted_labels = []
    for label in REDACT_LABELS:
        pattern = PATTERNS[label]
        if pattern.search(redacted):
            redacted_labels.append(label)
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted, redacted_labels
