from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+?6?0?1\d[\s.-]?){1}\d{7,8}(?!\d)")
_ACCOUNT = re.compile(r"\b\d{10,18}\b")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def scrub_pii(text: str) -> str:
    """Redact common contact and financial identifiers before persistence."""

    cleaned = _EMAIL.sub("[email redacted]", text)
    cleaned = _PHONE.sub("[phone redacted]", cleaned)
    cleaned = _ACCOUNT.sub("[number redacted]", cleaned)
    cleaned = _URL.sub("[link redacted]", cleaned)
    return " ".join(cleaned.split())
