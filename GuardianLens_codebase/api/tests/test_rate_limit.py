# Rate-limit tests: one session is limited, and so is one network address. The second matters
# because a session costs nothing to create: a client that sends no cookie gets a fresh session
# (and a fresh per-session allowance) on every request.
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from PIL import Image

from api.errors import AppError
from api.main import create_app
from api.services.rate_limit import RateLimiter

FORM = {
    "title": "Used laptop",
    "description": "Original unit in good condition.",
    "price": "1250",
    "category": "Electronics",
}


def submit(client: TestClient) -> Response:
    """Submits a valid listing with one photo."""
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (230, 230, 230)).save(buffer, format="JPEG")
    response: Response = client.post(
        "/api/v1/assess",
        data=FORM,
        files=[("images", ("listing.jpg", buffer.getvalue(), "image/jpeg"))],
    )
    return response


class Clock:
    """A settable stand-in for time.monotonic."""

    now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_limit_is_a_rolling_minute_and_quiet_keys_are_forgotten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key is allowed again after a minute, and the table does not keep keys that went quiet."""
    clock = Clock()
    monkeypatch.setattr("api.services.rate_limit.time.monotonic", clock)
    limiter = RateLimiter(2)
    limiter.check("a")
    limiter.check("a")
    with pytest.raises(AppError) as over:
        limiter.check("a")
    assert over.value.status_code == 429

    clock.now += 30
    limiter.check("b")
    clock.now += 31  # "a" last seen 61 s ago, "b" 31 s ago
    limiter.check("a")  # allowed again
    limiter.check("c")  # this call also does the minute's sweep: "b" is still inside its window
    assert set(limiter._events) == {"a", "b", "c"}

    clock.now += 61  # everyone is now quiet for over a minute
    limiter.check("d")
    assert set(limiter._events) == {"d"}


def test_one_session_is_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the same cookie, the check after the per-session limit is a 429."""
    monkeypatch.setenv("GUARDIANLENS_RATE_LIMIT_PER_MINUTE", "2")
    with TestClient(create_app()) as client:
        statuses = [submit(client).status_code for _ in range(3)]
    assert statuses == [202, 202, 429]


def test_a_client_that_sends_no_cookie_is_limited_by_its_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each request gets a new session, so only the network address can stop the flood."""
    monkeypatch.setenv("GUARDIANLENS_RATE_LIMIT_PER_IP_PER_MINUTE", "3")
    app = create_app()
    with TestClient(app):  # keeps the app (and its database) open while four fresh clients post
        statuses = [submit(TestClient(app)).status_code for _ in range(4)]
    assert statuses == [202, 202, 202, 429]


def test_the_address_limit_is_applied_before_the_upload_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An over-limit address is refused from its headers alone. Garbage that the route would call
    a 422 gets the 429 instead, which shows the route (and the parsing before it) never ran."""
    monkeypatch.setenv("GUARDIANLENS_RATE_LIMIT_PER_IP_PER_MINUTE", "1")
    with TestClient(create_app()) as client:
        assert submit(client).status_code == 202
        refused = client.post(
            "/api/v1/assess",
            content=b"this is not a form",
            headers={"Content-Type": "multipart/form-data; boundary=x"},
        )
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "rate_limit_exceeded"


def test_each_upload_counts_once_against_the_address_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A limit of 2 allows exactly two uploads: the check must not be counted twice per request."""
    monkeypatch.setenv("GUARDIANLENS_RATE_LIMIT_PER_IP_PER_MINUTE", "2")
    app = create_app()
    with TestClient(app):
        statuses = [submit(TestClient(app)).status_code for _ in range(3)]
    assert statuses == [202, 202, 429]


def test_minting_sessions_is_limited_by_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /session is free to call, so it is counted against the address too."""
    monkeypatch.setenv("GUARDIANLENS_RATE_LIMIT_PER_IP_PER_MINUTE", "2")
    with TestClient(create_app()) as client:
        statuses = [client.post("/api/v1/session").status_code for _ in range(3)]
    assert statuses == [201, 201, 429]
