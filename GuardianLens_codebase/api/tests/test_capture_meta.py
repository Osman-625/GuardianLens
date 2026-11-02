"""Tests for the `source` and `capture_meta` fields of POST /api/v1/assess, and the category limit.

The extension tells the API where each submitted value came from (read from the page, edited by
the buyer, or not found) so the research analysis can describe how data was captured. That record
must stay safe to store, so these tests pin that:
  - `source` is one of two fixed values and defaults to "manual";
  - `capture_meta` accepts only a fixed set of keys and a fixed set of platform hosts, so a
    listing URL (or any other free text) can never be stored through it;
  - capture details are accepted only from the extension, and are size limited;
  - the source and the capture details are stored with the assessment;
  - category is free text but length limited.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from PIL import Image

from api.main import create_app
from api.models.domain import AssessmentRecord

# A complete, valid capture_meta payload that individual tests then break on purpose.
VALID_META = {
    "adapter_version": "1",
    "platform_host": "www.carousell.com.my",
    "fields": {
        "title": "captured",
        "description": "captured",
        "price": "edited",
        "category": "captured",
        "platform": "captured",
        "images": "captured",
        "account_age_days": "not_found",
        "rating": "not_found",
        "review_count": "not_found",
        "active_listing_count": "not_found",
    },
}


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """A client for a fresh app with its own in-memory database."""
    with TestClient(create_app()) as test_client:
        yield test_client


def post_listing(client: TestClient, **extra: str) -> Response:
    """Submits a minimal valid listing; `extra` fields override or add form fields."""
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (230, 230, 230)).save(buffer, format="JPEG")
    data = {
        "platform": "carousell",
        "title": "Used laptop",
        "description": "Original unit in good condition.",
        "price": "RM 1,250",
        "category": "Laptops",
    }
    data.update(extra)
    response: Response = client.post(
        "/api/v1/assess",
        data=data,
        files=[("images", ("listing.jpg", buffer.getvalue(), "image/jpeg"))],
    )
    return response


def stored(client: TestClient, response: Response) -> AssessmentRecord:
    """Reads back, from the database, the assessment that a submission created."""
    found = client.app.state.repository.get_assessment(  # type: ignore[attr-defined]
        UUID(response.json()["assessment_id"])
    )
    assert found is not None
    return found  # type: ignore[no-any-return]


def test_source_defaults_to_manual(client: TestClient) -> None:
    """A submission without a `source` is recorded as manual."""
    response = post_listing(client)
    assert response.status_code == 202
    assert stored(client, response).source == "manual"


def test_extension_source_with_capture_meta_is_accepted(client: TestClient) -> None:
    """An extension submission with valid capture details is accepted and recorded as such."""
    response = post_listing(client, source="extension", capture_meta=json.dumps(VALID_META))
    assert response.status_code == 202, response.text
    record = stored(client, response)
    assert record.source == "extension"
    assert record.capture_meta == VALID_META


def test_extension_source_without_capture_meta_is_accepted(client: TestClient) -> None:
    """Capture details are optional: an extension submission without them is accepted."""
    assert post_listing(client, source="extension").status_code == 202


def test_unknown_source_is_rejected(client: TestClient) -> None:
    """A `source` other than extension or manual is refused with a message naming the field."""
    response = post_listing(client, source="bot")
    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "invalid_source",
        "message": "Source must be extension or manual.",
        "field": "source",
    }


def test_capture_meta_rejects_an_unknown_key(client: TestClient) -> None:
    """Capture details with a key outside the fixed list are refused."""
    # The model forbids extra keys, so a listing URL cannot ride along in a made-up field.
    bad = {**VALID_META, "listing_url": "https://www.carousell.com.my/p/x-1/"}
    response = post_listing(client, source="extension", capture_meta=json.dumps(bad))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_capture_meta"


def test_capture_meta_rejects_a_url_as_the_host(client: TestClient) -> None:
    """The platform host must be one of the four known hosts, never a full URL."""
    bad = {**VALID_META, "platform_host": "https://www.carousell.com.my/p/x-1/"}
    response = post_listing(client, source="extension", capture_meta=json.dumps(bad))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_capture_meta"


def test_capture_meta_rejects_text_that_is_not_json(client: TestClient) -> None:
    """Capture details that are not valid JSON are refused with an error on `capture_meta`."""
    response = post_listing(client, source="extension", capture_meta="{not json")
    assert response.status_code == 422
    assert response.json()["error"]["field"] == "capture_meta"


def test_capture_meta_rejects_an_oversized_payload(client: TestClient) -> None:
    """Capture details longer than 2,000 characters are refused before they are parsed."""
    response = post_listing(client, source="extension", capture_meta="x" * 2001)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_capture_meta"


def test_manual_source_cannot_carry_capture_meta(client: TestClient) -> None:
    """Capture details are only accepted together with the extension source."""
    response = post_listing(client, source="manual", capture_meta=json.dumps(VALID_META))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_capture_meta"


def test_category_is_free_text_but_length_limited(client: TestClient) -> None:
    """Any category is accepted up to 80 characters; a longer one is refused."""
    # Any category text is fine, including ones the models were not trained on.
    assert post_listing(client, category="Pets and aquarium supplies").status_code == 202
    too_long = post_listing(client, category="x" * 81)
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "category_too_long"
    assert too_long.json()["error"]["field"] == "category"


@pytest.mark.parametrize(
    "free_text",
    [
        "https://carousell.com.my/p/12345678",  # a listing URL
        "+60123456789",  # a phone number
        "a@b.co",  # an email address
        "seller Ali sold me a fake phone",  # a sentence
        "1.2.3.4.5",  # not a version
    ],
)
def test_capture_meta_adapter_version_cannot_carry_free_text(
    client: TestClient, free_text: str
) -> None:
    """The adapter version must be a plain version number, never a URL, contact, or sentence."""
    # The version is the one string field in capture_meta, so it must be a plain version number:
    # otherwise a script could store 40 characters of anything, past the personal-data scrub.
    bad = {**VALID_META, "adapter_version": free_text}
    response = post_listing(client, source="extension", capture_meta=json.dumps(bad))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_capture_meta"


@pytest.mark.parametrize("version", ["1", "12", "1.2", "1.2.3"])
def test_capture_meta_accepts_a_plain_version_number(client: TestClient, version: str) -> None:
    """Version numbers with one, two, or three parts are accepted."""
    ok = {**VALID_META, "adapter_version": version}
    response = post_listing(client, source="extension", capture_meta=json.dumps(ok))
    assert response.status_code == 202, response.text
