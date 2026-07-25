from __future__ import annotations

import io

from fastapi.testclient import TestClient
from httpx import Response
from PIL import Image

from api.main import create_app


def make_image(size: tuple[int, int] = (640, 480)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (230, 230, 230)).save(buffer, format="JPEG")
    return buffer.getvalue()


def submit(client: TestClient, **overrides: str) -> Response:
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
    return client.post(
        "/api/v1/assess",
        data=data,
        files=[("images", ("listing.jpg", make_image(), "image/jpeg"))],
    )


def test_health_and_stub_flag() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["stub_mode"] is True


def test_assessment_contract_end_to_end() -> None:
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
        assert "not produced by the trained" in payload["disclaimer"]

        history = client.get("/api/v1/session/history")
        assert history.status_code == 200
        assert history.json()[0]["assessment_id"] == assessment_id


def test_missing_seller_fields_are_unknown() -> None:
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


def test_unsupported_language_preserves_field_error_envelope() -> None:
    with TestClient(create_app()) as client:
        response = submit(client, title="出售手机", description="全新手机，价格便宜，请联系卖家")
        assert response.status_code == 422
        assert response.json() == {
            "error": {
                "code": "unsupported_language",
                "message": (
                    "Chinese-dominant listings are outside this prototype's supported language scope."
                ),
                "field": "description",
            }
        }


def test_cross_session_result_is_hidden() -> None:
    app = create_app()
    with TestClient(app) as owner:
        accepted = submit(owner)
        assessment_id = accepted.json()["assessment_id"]
        with TestClient(app) as stranger:
            hidden = stranger.get(f"/api/v1/assess/{assessment_id}/result")
            assert hidden.status_code == 404
            assert hidden.json()["error"]["code"] == "not_found"


def test_feedback_is_accepted_and_scrubbed() -> None:
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
