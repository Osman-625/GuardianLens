# Upload-size tests: a request that is too big (or does not say how big it is) is refused from its
# headers alone, before the server reads or stores any of it.
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app

ORIGIN = "http://localhost:3000"


def small_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """One photo of at most 1000 bytes: the whole upload may be about 1 MB (1000 + 1 MiB)."""
    monkeypatch.setenv("GUARDIANLENS_MAX_IMAGES", "1")
    monkeypatch.setenv("GUARDIANLENS_MAX_IMAGE_BYTES", "1000")


def test_an_oversized_upload_is_refused_before_it_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 1.2 MB body is a 413 with the error envelope; no session or rate-limit count is made."""
    small_limits(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/api/v1/assess", content=b"x" * 1_200_000)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"
        assert app.state.repository._db.execute("SELECT 1 FROM sessions").fetchall() == []
        assert app.state.ip_rate_limiter._events == {}


def test_an_upload_that_does_not_state_its_size_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A streamed body has no Content-Length, so its size cannot be checked: 411."""
    small_limits(monkeypatch)
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/assess", content=iter([b"x", b"y"]))
    assert response.status_code == 411
    assert response.json()["error"]["code"] == "length_required"


@pytest.mark.parametrize(
    "content_type",
    [
        "application/x-www-form-urlencoded",
        "application/json",
        "text/plain",
        "",
    ],
)
def test_only_a_multipart_form_is_accepted(content_type: str) -> None:
    """A urlencoded body of many tiny fields took 90+ seconds to parse; it is refused unread."""
    app = create_app()
    with TestClient(app) as client:
        headers = {"Content-Type": content_type} if content_type else {}
        response = client.post("/api/v1/assess", content=b"a=1&" * 1000, headers=headers)
        assert response.status_code == 415
        assert response.json()["error"]["code"] == "unsupported_media_type"
        assert app.state.repository._db.execute("SELECT 1 FROM sessions").fetchall() == []


def test_a_real_form_still_gets_through() -> None:
    """The check is on the type only: the website's and extension's multipart uploads pass."""
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/assess",
            data={"title": "t", "description": "d", "price": "1", "category": "c"},
            files=[("images", ("a.jpg", b"not an image", "image/jpeg"))],
        )
    assert response.status_code == 422  # reached the route; the photo check said no
    assert response.json()["error"]["code"] == "invalid_image"


def test_the_refusal_is_readable_by_the_website(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 413 carries the CORS header, so the browser shows the message, not a network error."""
    small_limits(monkeypatch)
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/assess", content=b"x" * 1_200_000, headers={"Origin": ORIGIN}
        )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_other_routes_are_not_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the upload route is checked."""
    small_limits(monkeypatch)
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/api/v1/session").status_code == 201
