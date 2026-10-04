from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

CAROUSELL_BASE_URL = "https://www.carousell.com.my"
CAROUSELL_LISTING_RE = re.compile(r"^https://www\.carousell\.com\.my/p/[^/?#]+-\d+/?$")

MUDAH_BASE_URL = "https://www.mudah.my"
MUDAH_LISTING_RE = re.compile(r"^https://www\.mudah\.my/[^/?#]+-\d+\.htm$")


def normalize_listing_url(href: str | None) -> str | None:
    """Return a canonical Carousell Malaysia listing URL, or None."""
    if not href:
        return None

    absolute = urljoin(CAROUSELL_BASE_URL, href.strip())
    parts = urlsplit(absolute)

    if parts.scheme != "https" or parts.netloc.lower() != "www.carousell.com.my":
        return None

    clean = urlunsplit(("https", "www.carousell.com.my", parts.path, "", ""))
    if not clean.endswith("/"):
        clean += "/"

    return clean if CAROUSELL_LISTING_RE.match(clean) else None


def normalize_mudah_listing_url(href: str | None) -> str | None:
    """Return a canonical Mudah.my listing URL, or None."""
    if not href:
        return None

    absolute = urljoin(MUDAH_BASE_URL, href.strip())
    parts = urlsplit(absolute)

    if parts.scheme != "https" or parts.netloc.lower() not in ("www.mudah.my", "mudah.my"):
        return None

    clean = urlunsplit(("https", "www.mudah.my", parts.path, "", ""))
    return clean if MUDAH_LISTING_RE.match(clean) else None
