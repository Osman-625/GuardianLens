# Tests for the personal-data scrubber: the number formats Malaysian sellers really write are
# hidden, ordinary listing text is left alone, and a submitted title is stored scrubbed.
from __future__ import annotations

import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.main import create_app
from api.services.privacy import scrub_pii

HIDDEN = [
    "WhatsApp 012-345 6789",
    "call 0123456789",
    "+60 12 345 6789",
    "+6012-3456789",
    "wasap 012 3456 789",
    "hubungi 03-8888 1234",
    "Maybank 1234 5678 9012",
    "acc no 1234-5678-9012",
    "Maybank 5640 1234 5678 (Ali)",
    "CIMB 7612345678",
    "Maybank1234567890",
    "wa.me/60123456789",
    "https://wa.me/60123456789?text=hi",
    "mail ali@gmail.com now",
]

LEFT_ALONE = [
    "iPhone 13 Pro Max 256GB RM 4,500 nego",
    "Price RM1,250.50 only",
    "bought 12.05.2025, 2 years old",
    "Samsung S23 8GB 256GB 5G",
    "Size 120 x 60 x 75 cm",
    "RTX 3080 10GB, 750W PSU",
    "Model A2633, 2021",
]


@pytest.mark.parametrize("text", HIDDEN)
def test_contact_and_account_details_are_hidden(text: str) -> None:
    """No run of 9 or more digits, and no email, survives, whatever spaces or dashes split it."""
    cleaned = scrub_pii(text)
    assert "redacted" in cleaned
    assert sum(character.isdigit() for character in cleaned) < 9
    assert "@" not in cleaned


@pytest.mark.parametrize("text", LEFT_ALONE)
def test_ordinary_listing_text_is_unchanged(text: str) -> None:
    """Prices, dates, sizes, and model numbers are not mistaken for personal details."""
    assert scrub_pii(text) == text


@pytest.mark.parametrize("unit", ["a.", "a-", "+1", "1.1", "a@a.", "x"])
def test_the_longest_description_is_scrubbed_quickly(unit: str) -> None:
    """Text built to make a rule backtrack still scrubs in well under 100 ms (it was 400 ms)."""
    text = (unit * 5000)[:5000]
    started = time.perf_counter()
    scrub_pii(text)
    assert time.perf_counter() - started < 0.1


def test_a_link_with_digits_is_replaced_whole() -> None:
    """The link is removed first, so no half-redacted fragment is left behind."""
    assert scrub_pii("chat https://wa.me/60123456789 ok") == "chat [link redacted] ok"


def test_a_submitted_title_is_stored_without_the_phone_number() -> None:
    """What the history lists (the stored, scrubbed title) holds no phone number."""
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (230, 230, 230)).save(buffer, format="JPEG")
    with TestClient(create_app()) as client:
        accepted = client.post(
            "/api/v1/assess",
            data={
                "title": "Laptop WhatsApp 012-345 6789",
                "description": "Good condition.",
                "price": "1250",
                "category": "Electronics",
            },
            files=[("images", ("listing.jpg", buffer.getvalue(), "image/jpeg"))],
        )
        assert accepted.status_code == 202, accepted.text
        title = client.get("/api/v1/session/history").json()[0]["title"]
    assert title == "Laptop WhatsApp [number redacted]"
