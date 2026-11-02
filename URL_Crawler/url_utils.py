"""Listing URL normalisation shared by the crawler and the output validator.

Each marketplace has one function that turns any link found on a page (relative, tracking
parameters, mixed case host) into a single canonical listing URL, or None when the link is not a
listing. Canonical URLs are what the crawler de-duplicates on and what validate_outputs.py checks.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

# Carousell Malaysia listing paths look like /p/<slug>-<numeric id>/ (trailing slash optional on input).
CAROUSELL_BASE_URL = "https://www.carousell.com.my"
CAROUSELL_LISTING_RE = re.compile(r"^https://www\.carousell\.com\.my/p/[^/?#]+-\d+/?$")

# Mudah listing paths look like /<slug>-<numeric id>.htm (no trailing slash).
MUDAH_BASE_URL = "https://www.mudah.my"
MUDAH_LISTING_RE = re.compile(r"^https://www\.mudah\.my/[^/?#]+-\d+\.htm$")


def normalize_listing_url(href: str | None) -> str | None:
    """Return a canonical Carousell Malaysia listing URL, or None."""
    if not href:
        return None

    # Resolve relative links against the site root, then reject anything off-site or non-https.
    absolute = urljoin(CAROUSELL_BASE_URL, href.strip())
    parts = urlsplit(absolute)

    if parts.scheme != "https" or parts.netloc.lower() != "www.carousell.com.my":
        return None

    # Drop query string and fragment (tracking parameters) and force a single trailing slash,
    # so two links to the same listing compare equal.
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

    # Mudah serves the same listing on the bare and the www host; both are accepted, and the
    # canonical form always uses www.
    if parts.scheme != "https" or parts.netloc.lower() not in ("www.mudah.my", "mudah.my"):
        return None

    clean = urlunsplit(("https", "www.mudah.my", parts.path, "", ""))
    return clean if MUDAH_LISTING_RE.match(clean) else None
