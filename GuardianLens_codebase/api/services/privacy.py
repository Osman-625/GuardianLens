# Removal of personal contact and financial details from text before it is stored. Each pattern
# below finds one kind of detail. Links go first, so a link that contains digits is replaced whole.
from __future__ import annotations

import re

# The email rule caps each side (64 and 255 are the email standard's own limits): without a cap a
# 5,000-character run like "a.a.a." took 0.4 s to scan, on the thread that serves every request.
#
# A web address, an email address, and any phone, account, or card number: 9 to 18 digits, written
# with or without a "+" in front and with a single space, dot, or dash between digits ("012-345
# 6789", "+60 12 345 6789", "1234 5678 9012"). The rule errs on the side of hiding: an odd list of
# numbers ("100 200 300") is blanked too, which is harmless because the scrubbed text is only
# stored and shown, never scored.
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]{1,64}@[A-Z0-9.-]{1,255}\.[A-Z]{2,}\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<!\d)\+?\d(?:[ .-]?\d){8,17}(?!\d)")


def scrub_pii(text: str) -> str:
    """Redacts common contact and financial identifiers before persistence.

    Links, emails, and phone, account, or card numbers are replaced with a bracketed label, and the
    whitespace is tidied to single spaces. Social handles (`@name`, `t.me/name`) are not caught.
    """

    cleaned = _URL.sub("[link redacted]", text)
    cleaned = _EMAIL.sub("[email redacted]", cleaned)
    cleaned = _NUMBER.sub("[number redacted]", cleaned)
    return " ".join(cleaned.split())
