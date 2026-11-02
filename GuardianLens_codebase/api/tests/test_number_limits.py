# Number-limit tests: a price or seller count above 10,000,000 is a 422 on that field. The saved
# models read these as 32-bit floats, so an absurd number (1e300) used to be accepted and then make
# the scoring fail; the limit stops it at validation instead.
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.main import create_app

FORM = {
    "title": "Used laptop",
    "description": "Original unit in good condition.",
    "price": "1250",
    "category": "Electronics",
}


def submit(**overrides: str) -> tuple[int, dict[str, str]]:
    """Submits a listing with the form overrides; returns the status and the error (if any)."""
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (230, 230, 230)).save(buffer, format="JPEG")
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/assess",
            data={**FORM, **overrides},
            files=[("images", ("listing.jpg", buffer.getvalue(), "image/jpeg"))],
        )
    return response.status_code, response.json().get("error", {})


@pytest.mark.parametrize("price", ["1e300", "1e39", "10000001", "RM 99,999,999,999"])
def test_an_absurd_price_is_a_422_on_the_price_field(price: str) -> None:
    """Above 10,000,000 (including the 1e300 that used to crash the scoring) is refused."""
    status, error = submit(price=price)
    assert (status, error["code"], error["field"]) == (422, "invalid_price", "price")


@pytest.mark.parametrize("price", ["0", "1250", "RM 1,250.50", "10000000"])
def test_a_normal_price_still_passes(price: str) -> None:
    """Zero up to and including the limit is accepted."""
    assert submit(price=price)[0] == 202


@pytest.mark.parametrize(
    ("written", "stored"),
    [
        ("1250", 1250.0),
        (" 1250 ", 1250.0),
        ("RM 1,250", 1250.0),
        ("RM1250.50", 1250.5),
        ("rm 1250", 1250.0),
        ("Rm1250", 1250.0),
        ("MYR 99", 99.0),
        ("myr99.9", 99.9),
        ("1,250,000.5", 1250000.5),
    ],
)
def test_prices_are_read_as_written(written: str, stored: float) -> None:
    """RM or MYR in any case is accepted, and the number stored is the number written."""
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (230, 230, 230)).save(buffer, format="JPEG")
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/assess",
            data={**FORM, "price": written},
            files=[("images", ("listing.jpg", buffer.getvalue(), "image/jpeg"))],
        )
        assert response.status_code == 202, response.text
        prices = app.state.repository._db.execute("SELECT price FROM assessments").fetchall()
        assert [row["price"] for row in prices] == [stored]


@pytest.mark.parametrize(
    "price",
    ["1.250,00", "1.250", "1,25", "RM 1 250", "1e3", "1_000", "0x10", "RM", "-5", "RM1,250 nego"],
)
def test_a_price_that_could_be_misread_is_refused_not_guessed(price: str) -> None:
    """European-style and other ambiguous spellings give a 422, never a silently wrong price."""
    status, error = submit(price=price)
    assert (status, error["code"], error["field"]) == (422, "invalid_price", "price")


@pytest.mark.parametrize("field", ["account_age_days", "review_count", "active_listing_count"])
def test_an_absurd_seller_count_is_a_422_on_that_field(field: str) -> None:
    """Counts above 10,000,000 are refused, naming the field; the limit itself is allowed."""
    status, error = submit(**{field: str(10**39)})
    assert (status, error["code"], error["field"]) == (422, "value_too_large", field)
    assert submit(**{field: "10000000"})[0] == 202
