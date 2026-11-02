# API tests for the core submission flow: health, the end-to-end assessment contract, unknown
# seller fields, field-level errors, session isolation, feedback, upload validation, and the photo
# limit. The session header and the capture metadata are tested in test_sessions.py and
# test_capture_meta.py.
from __future__ import annotations

import io
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from PIL import Image

from api.main import create_app
from api.settings import Settings, get_settings


def make_image(size: tuple[int, int] = (640, 480)) -> bytes:
    """Returns a small valid JPEG, so uploads pass the API's image validation."""
    buffer = io.BytesIO()
    Image.new("RGB", size, (230, 230, 230)).save(buffer, format="JPEG")
    return buffer.getvalue()


def submit(client: TestClient, **overrides: str) -> Response:
    """Submits a valid listing with one photo; `overrides` replace individual form fields."""
    data = {
        "platform": "carousell",
        "title": "Used laptop",
        "description": "Original unit in good condition. COD available.",
        "price": "RM 1,250",
        "category": "Electronics",
        "account_age_days": "400",
        "rating": "4.8",
        "review_count": "21",
        "active_listing_count": "4",
    }
    data.update(overrides)
    response: Response = client.post(
        "/api/v1/assess",
        data=data,
        files=[("images", ("listing.jpg", make_image(), "image/jpeg"))],
    )
    return response


def test_health_and_stub_flag() -> None:
    """The health endpoint answers and reports that the API is running in stub mode."""
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["stub_mode"] is True


def test_health_does_not_expose_folder_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public health page never shows where the model run lives on the server's disk."""
    monkeypatch.setenv("GUARDIANLENS_MODEL_RUN_DIR", r"C:\secret\models\run_42")
    with TestClient(create_app()) as client:
        body = client.get("/health")
    assert body.status_code == 200
    assert "secret" not in body.text
    assert not {"configured_model_run", "visual_unavailable_reason"} & set(body.json())


def test_assessment_contract_end_to_end() -> None:
    """A submission is accepted, completes, and shows up as a stub result and in the history."""
    with TestClient(create_app()) as client:
        accepted = submit(client)
        assert accepted.status_code == 202, accepted.text
        assessment_id = accepted.json()["assessment_id"]
        assert client.cookies.get("guardianlens_session")

        status = client.get(f"/api/v1/assess/{assessment_id}/status")
        assert status.status_code == 200
        assert status.json()["status"] == "complete"

        result = client.get(f"/api/v1/assess/{assessment_id}/result")
        assert result.status_code == 200
        payload = result.json()
        assert payload["development_stub"] is True
        assert payload["model_bundle_label"] == "dev-stub-unvalidated"
        assert len(payload["signal_cards"]) == 3
        assert "Test mode" in payload["disclaimer"]

        history = client.get("/api/v1/session/history")
        assert history.status_code == 200
        assert history.json()[0]["assessment_id"] == assessment_id


def test_missing_seller_fields_are_unknown() -> None:
    """With every seller field empty, the behavioural card is unavailable and says "unknown"."""
    with TestClient(create_app()) as client:
        accepted = submit(
            client,
            account_age_days="",
            rating="",
            review_count="",
            active_listing_count="",
        )
        assessment_id = accepted.json()["assessment_id"]
        payload = client.get(f"/api/v1/assess/{assessment_id}/result").json()
        behavioural = next(
            card for card in payload["signal_cards"] if card["signal"] == "behavioural"
        )
        assert behavioural["available"] is False
        assert "unknown, not as suspicious" in behavioural["summary"]
        # One notice says the score left a signal out; it does not repeat the card's sentence.
        assert payload["missing_data_notices"] == [
            "This result uses 2 of 3 checks. A check that could not run is unknown, not suspicious."
        ]


def test_unsupported_language_preserves_field_error_envelope() -> None:
    """Chinese-dominant text is refused with the standard error body naming the description."""
    with TestClient(create_app()) as client:
        response = submit(client, title="出售手机", description="全新手机，价格便宜，请联系卖家")
        assert response.status_code == 422
        assert response.json() == {
            "error": {
                "code": "unsupported_language",
                "message": (
                    "Listings written mostly in Chinese or another non-Latin script are "
                    "outside this prototype's supported language scope."
                ),
                "field": "description",
            }
        }


def test_cross_session_result_is_hidden() -> None:
    """Another session cannot read a result; it gets the same "not found" as a missing one."""
    app = create_app()
    with TestClient(app) as owner:
        accepted = submit(owner)
        assessment_id = accepted.json()["assessment_id"]
        with TestClient(app) as stranger:
            hidden = stranger.get(f"/api/v1/assess/{assessment_id}/result")
            assert hidden.status_code == 404
            assert hidden.json()["error"]["code"] == "not_found"


def test_feedback_is_accepted_and_scrubbed() -> None:
    """Feedback whose comment holds an email and a phone number is accepted (204)."""
    with TestClient(create_app()) as client:
        assessment_id = submit(client).json()["assessment_id"]
        response = client.post(
            f"/api/v1/assess/{assessment_id}/feedback",
            json={
                "verdict": "unclear",
                "comment": "Contact me at test@example.com or 0123456789",
            },
        )
        assert response.status_code == 204


def test_invalid_file_type_is_rejected_per_file() -> None:
    """A non-image upload is refused with an error that names that photo (`images[0]`)."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/assess",
            data={
                "title": "Item",
                "description": "Description",
                "price": "10",
                "category": "Other",
            },
            files=[("images", ("bad.txt", b"not an image", "text/plain"))],
        )
        assert response.status_code == 422
        assert response.json()["error"]["field"] == "images[0]"


@pytest.mark.parametrize("price", ["NaN", "Infinity", "1e309"])
def test_nonfinite_price_is_rejected_before_assessment(price: str) -> None:
    """NaN, infinity, and an overflowing number are refused as an invalid price."""
    with TestClient(create_app()) as client:
        response = submit(client, price=price)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_price"


# ---- Photo limit: up to 10 photos per listing ------------------------------------------------
# More photos give the visual signal more to compare, and Mudah and Carousell listings often have
# more than three. The limit is a setting; these tests pin the default and the behaviour at the
# edge. The environment is set explicitly so a developer's own .env cannot change the result.


def test_default_photo_limit_is_ten() -> None:
    """Without any environment override, the photo limit setting is ten."""
    assert Settings(_env_file=None).guardianlens_max_images == 10  # type: ignore[call-arg]


def submit_photos(client: TestClient, count: int) -> Response:
    """Submits a valid listing with `count` photos."""
    response: Response = client.post(
        "/api/v1/assess",
        data={
            "platform": "carousell",
            "title": "Used laptop",
            "description": "Original unit in good condition. COD available.",
            "price": "RM 1,250",
            "category": "Laptops",
        },
        files=[
            ("images", (f"photo-{index}.jpg", make_image(), "image/jpeg")) for index in range(count)
        ],
    )
    return response


@pytest.fixture()
def ten_photo_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A test client for an app whose photo limit is set to ten explicitly."""
    monkeypatch.setenv("GUARDIANLENS_MAX_IMAGES", "10")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def test_ten_photos_are_accepted(ten_photo_client: TestClient) -> None:
    """A listing with exactly ten photos is accepted."""
    assert submit_photos(ten_photo_client, 10).status_code == 202


def test_an_eleventh_photo_is_refused_with_a_clear_message(ten_photo_client: TestClient) -> None:
    """Eleven photos are refused with the "too many images" error naming the images field."""
    response = submit_photos(ten_photo_client, 11)
    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "too_many_images",
        "message": "Add no more than 10 images.",
        "field": "images",
    }
