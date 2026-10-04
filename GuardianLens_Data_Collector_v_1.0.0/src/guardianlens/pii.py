from __future__ import annotations
import re
from dataclasses import dataclass

EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
OBFUSCATED_EMAIL = re.compile(
    r"\b[A-Z0-9._%+-]{2,}\s*(?:\[at\]|\(at\)|\bat\b)\s*[A-Z0-9.-]+\s*"
    r"(?:\[dot\]|\(dot\)|\bdot\b)\s*[A-Z]{2,}\b",
    re.I,
)
PHONE = re.compile(r"(?<!\d)(?:\+?60|0)[\s.-]?(?:1\d|[3-9]\d)[\s.-]?\d{3,4}[\s.-]?\d{3,4}(?!\d)")
# Detection-only (never in PATTERNS / never auto-redacted -- see scrub_text):
# a loose net for phone-shaped numbers PHONE's rigid Malaysian grouping misses
# (foreign formats, or a seller spacing every digit like "0 1 2 2 5 8 1 9 3 7"
# to dodge simple filters), meant to escalate ambiguous cases for a human to
# judge rather than silently pass or redact them. The bug was that it bounded
# on character-span length, not actual digit count, so short digit runs
# padded with '.'/'-' -- a date ("13.4.2026", 7 digits), a year range
# ("2016-2021", 8 digits), a spec fragment ("1080) - 144", 7 digits) -- were
# wide enough to match even though no real phone number is 7-8 digits with
# that padding. Bounding on digit count (9-12, covering local and
# country-code formats) keeps a bare 10-digit serial or a spaced-out 11-digit
# number flagged while dates and specs fall under the floor.
GENERIC_PHONE = re.compile(r"(?<!\d)\+?\d(?:[\s.()-]?\d){8,11}(?!\d)")
BANK = re.compile(r"\b(?:bank\s*(?:account|acc)|acct|account\s*no\.?)[\s:#-]*[A-Z0-9 -]{6,24}\b", re.I)
CONTACT_HANDLE = re.compile(r"\b(?:whatsapp|telegram|wechat|contact\s*me|dm\s*me)\b[^\n]{0,80}", re.I)
CONTACT_LINK = re.compile(r"\b(?:wa\.me|t\.me|api\.whatsapp\.com)/[^\s]+", re.I)
SOCIAL_HANDLE = re.compile(r"(?<![\w@])@[A-Z0-9_][A-Z0-9_.-]{2,}\b", re.I)
ADDRESS_HINT = re.compile(
    r"\b(?:(?:no\.?\s*)?\d{1,5}[A-Za-z]?[,\s]+(?:jalan|lorong|persiaran|street|road|avenue|lane)\b[^\n]{0,100})",
    re.I,
)

PATTERNS = [
    ("email", EMAIL),
    ("obfuscated_email", OBFUSCATED_EMAIL),
    ("phone", PHONE),
    ("bank", BANK),
    ("contact_handle", CONTACT_HANDLE),
    ("contact_link", CONTACT_LINK),
    ("social_handle", SOCIAL_HANDLE),
    ("address", ADDRESS_HINT),
]

@dataclass
class ScrubResult:
    text: str
    matches: list[str]
    kinds: list[str]

def scrub_text(text: str | None) -> ScrubResult:
    if not text:
        return ScrubResult(text or "", [], [])
    cleaned = text
    matches: list[str] = []
    kinds: list[str] = []
    for kind, pattern in PATTERNS:
        found = pattern.findall(cleaned)
        for item in found:
            if isinstance(item, tuple):
                item = " ".join(item)
            matches.append(str(item))
            kinds.append(kind)
        cleaned = pattern.sub("[REDACTED]", cleaned)
    return ScrubResult(cleaned.strip(), matches, sorted(set(kinds)))

def residual_pii(text: str | None) -> list[str]:
    if not text:
        return []
    hits = []
    for name, pattern in [*PATTERNS, ("generic_phone", GENERIC_PHONE)]:
        if pattern.search(text):
            hits.append(name)
    return sorted(set(hits))

# Non-informative filler an AI extractor (or a hurried human edit) can emit in
# place of a real value. These must never be treated as legitimate listing data.
PLACEHOLDER_TOKENS = {
    "n/a", "n.a", "n.a.", "na", "none", "null", "undefined", "unknown",
    "tbd", "todo", "test", "testing", "sample", "sample product",
    "sample text", "example", "placeholder", "xxx", "xxxx", "xxxxx",
    "string", "text", "lorem ipsum", "not available", "not applicable",
    "no data", "no info", "no information", "-", "--", "...", "asdf",
    "asdfgh", "qwerty", "123456",
}
REPEATED_CHAR = re.compile(r"^(.)\1{2,}$")

def is_placeholder_value(value: object) -> bool:
    """True when a field holds filler text instead of a real extracted value."""
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered in PLACEHOLDER_TOKENS:
        return True
    alnum = re.sub(r"[^a-z0-9]", "", lowered)
    return bool(alnum) and bool(REPEATED_CHAR.match(alnum))
