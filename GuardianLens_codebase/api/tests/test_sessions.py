"""Tests for the header-based session transport and the session claim endpoint.

The browser extension cannot share the website's cookie, so it identifies its buyer with an
opaque token sent in the X-Session-Token header. These tests pin:
  - minting a session, and using the token to own and read assessments;
  - an unknown token on submit is rejected with `session_invalid` (so the client can mint a
    new session and retry), while reading someone else's data stays a generic "not found";
  - the claim endpoint turns a token into the website's httpOnly cookie;
  - CORS allows the session header for the website;
  - a browser request from an origin the API does not serve is refused before it changes anything.

One TestClient is used per test on purpose: the app opens its own in-memory database when it
starts up, so two clients would not share sessions. Which "browser" is calling is simulated by
sending the header, or not.
"""

from __future__ import annotations

import io
import json
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from PIL import Image

from api.main import create_app
from api.settings import Settings

COOKIE_NAME = "guardianlens_session"


def make_image() -> bytes:
    """A small valid JPEG, so the upload passes the API's image validation."""
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (230, 230, 230)).save(buffer, format="JPEG")
    return buffer.getvalue()


def submit_with_token(client: TestClient, token: str | None) -> Response:
    """Submits a minimal valid listing, identifying the buyer by header when a token is given."""
    headers = {"X-Session-Token": token} if token is not None else {}
    response: Response = client.post(
        "/api/v1/assess",
        data={
            "platform": "carousell",
            "title": "Used laptop",
            "description": "Original unit in good condition. COD available.",
            "price": "RM 1,250",
            "category": "Laptops",
        },
        files=[("images", ("listing.jpg", make_image(), "image/jpeg"))],
        headers=headers,
    )
    return response


def test_a_refused_first_submission_leaves_no_session_behind() -> None:
    """The error answer carries no cookie, so a session made for it would never reach the buyer."""
    with TestClient(create_app()) as client:
        refused = client.post(
            "/api/v1/assess",
            data={"title": "ok", "description": "ok", "price": "abc", "category": "Laptops"},
            files=[("images", ("listing.jpg", make_image(), "image/jpeg"))],
        )
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == "invalid_price"
        db = client.app.state.repository._db  # type: ignore[attr-defined]
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0

        accepted = submit_with_token(client, None)  # the same buyer, corrected: now one session
        assert accepted.status_code == 202
        assert COOKIE_NAME in accepted.cookies
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_create_session_returns_a_token() -> None:
    """Minting a session returns a UUID token and sets no cookie."""
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/session")
        assert response.status_code == 201
        # The token must be a UUID, and header clients must not be handed a cookie.
        UUID(response.json()["session_token"])
        assert COOKIE_NAME not in client.cookies


def test_header_token_owns_the_assessment() -> None:
    """An assessment submitted with a token can be read, and listed, by that same token."""
    with TestClient(create_app()) as client:
        token = client.post("/api/v1/session").json()["session_token"]
        accepted = submit_with_token(client, token)
        assert accepted.status_code == 202, accepted.text
        assessment_id = accepted.json()["assessment_id"]
        # A valid header token means no lazy cookie session is created.
        assert COOKIE_NAME not in client.cookies

        headers = {"X-Session-Token": token}
        result = client.get(f"/api/v1/assess/{assessment_id}/result", headers=headers)
        assert result.status_code == 200
        history = client.get("/api/v1/session/history", headers=headers).json()
        assert [item["assessment_id"] for item in history] == [assessment_id]


def test_unknown_header_token_on_submit_is_session_invalid() -> None:
    """A well-formed token the server does not know is answered with `session_invalid` (401)."""
    # Happens after a backend restart: the extension still holds a token the new process
    # does not know. The 401 tells the client to mint a new session and retry.
    with TestClient(create_app()) as client:
        response = submit_with_token(client, str(uuid4()))
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "session_invalid"


def test_malformed_header_token_on_submit_is_session_invalid() -> None:
    """A token that is not a UUID is answered with `session_invalid` (401) as well."""
    with TestClient(create_app()) as client:
        response = submit_with_token(client, "not-a-uuid")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "session_invalid"


def test_header_token_cannot_read_another_session() -> None:
    """A token cannot read another session's result; the answer is the generic "not found"."""
    with TestClient(create_app()) as client:
        first = client.post("/api/v1/session").json()["session_token"]
        second = client.post("/api/v1/session").json()["session_token"]
        assessment_id = submit_with_token(client, first).json()["assessment_id"]

        hidden = client.get(
            f"/api/v1/assess/{assessment_id}/result", headers={"X-Session-Token": second}
        )
        # Reads never reveal that an assessment exists for someone else.
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "not_found"


def test_claim_turns_a_token_into_the_cookie() -> None:
    """Claiming a token sets the session cookie, so the website then lists the same checks."""
    with TestClient(create_app()) as client:
        token = client.post("/api/v1/session").json()["session_token"]
        assessment_id = submit_with_token(client, token).json()["assessment_id"]
        # The "website" has no cookie yet, so it cannot see the extension's checks.
        assert COOKIE_NAME not in client.cookies
        assert client.get("/api/v1/session/history").json() == []

        claimed = client.post("/api/v1/session/claim", json={"token": token})

        assert claimed.status_code == 204
        assert client.cookies.get(COOKIE_NAME) == token
        history = client.get("/api/v1/session/history").json()
        assert [item["assessment_id"] for item in history] == [assessment_id]


def test_claim_unknown_token_is_not_found() -> None:
    """Claiming a token the server does not know is a 404 and sets no cookie."""
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/session/claim", json={"token": str(uuid4())})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert COOKIE_NAME not in client.cookies


def test_claim_rejects_a_malformed_token() -> None:
    """A claim whose token is not a UUID is refused as invalid input (422) before any lookup."""
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/session/claim", json={"token": "nope"})
        assert response.status_code == 422


def test_cors_allows_the_session_header() -> None:
    """The CORS preflight lists X-Session-Token among the headers a browser may send."""
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/v1/assess",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-session-token",
            },
        )
        assert response.status_code == 200
        allowed = response.headers["access-control-allow-headers"].lower()
        assert "x-session-token" in allowed


# ---- Origin guard ---------------------------------------------------------------------------
# A browser sends an Origin header on every cross-site POST. A page on another site could send the
# claim request with no Content-Type (which counts as a "simple" request, so the browser skips the
# CORS preflight) and the API would still run it. These tests pin that a request from an origin
# the API does not serve is refused before it can set a cookie or change anything, while clients
# that send no Origin (scripts) and the extension (which authenticates with the header) still work.
# The Origin headers of a page on another site, of the website, and of the browser extension.
EVIL = {"Origin": "https://evil.example"}
WEBSITE = {"Origin": "http://localhost:3000"}
EXTENSION = {"Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"}


def test_claim_refuses_a_foreign_origin_even_without_a_content_type() -> None:
    """A foreign-origin claim is refused and sets no cookie, even without a Content-Type."""
    with TestClient(create_app()) as client:
        token = client.post("/api/v1/session").json()["session_token"]
        # `content=` sends the JSON bytes with no Content-Type header at all.
        response = client.post(
            "/api/v1/session/claim", content=json.dumps({"token": token}), headers=EVIL
        )
        # 422: FastAPI no longer reads a JSON body that has no JSON Content-Type, so it stops the
        # request before the route's own origin check (403) would. Either way nothing is claimed.
        assert response.status_code in (403, 422)
        assert "set-cookie" not in response.headers
        assert COOKIE_NAME not in client.cookies


def test_claim_still_works_from_the_website_origin() -> None:
    """A claim from the website's own origin is accepted and sets the cookie."""
    with TestClient(create_app()) as client:
        token = client.post("/api/v1/session").json()["session_token"]
        response = client.post("/api/v1/session/claim", json={"token": token}, headers=WEBSITE)
        assert response.status_code == 204
        assert COOKIE_NAME in client.cookies


def test_cookie_authenticated_writes_refuse_a_foreign_origin() -> None:
    """Cancel, feedback, and submit from another site are refused; from the website they work."""
    with TestClient(create_app()) as client:
        # No header token, so this submit creates a cookie session (the website's path).
        accepted = submit_with_token(client, None)
        assert accepted.status_code == 202
        assessment_id = accepted.json()["assessment_id"]

        cancel = client.post(f"/api/v1/assess/{assessment_id}/cancel", headers=EVIL)
        feedback = client.post(
            f"/api/v1/assess/{assessment_id}/feedback",
            json={"verdict": "helpful", "comment": None},
            headers=EVIL,
        )
        submit = client.post(
            "/api/v1/assess",
            data={
                "platform": "carousell",
                "title": "Used laptop",
                "description": "Original unit in good condition.",
                "price": "RM 1,250",
                "category": "Laptops",
            },
            files=[("images", ("listing.jpg", make_image(), "image/jpeg"))],
            headers=EVIL,
        )
        assert [cancel.status_code, feedback.status_code, submit.status_code] == [403, 403, 403]
        # The same calls from the website's own origin are accepted.
        allowed = client.post(f"/api/v1/assess/{assessment_id}/cancel", headers=WEBSITE)
        assert allowed.status_code == 204


def test_extension_requests_are_not_blocked_by_the_origin_guard() -> None:
    """Requests from the extension's origin, authenticated by the session header, go through."""
    with TestClient(create_app()) as client:
        # The extension's origin is chrome-extension://<id>. It authenticates with the header,
        # which a page on another site cannot add without a CORS preflight, so the guard lets it
        # through.
        token = client.post("/api/v1/session", headers=EXTENSION).json()["session_token"]
        headers = {"X-Session-Token": token, **EXTENSION}
        accepted = client.post(
            "/api/v1/assess",
            data={
                "platform": "carousell",
                "title": "Used laptop",
                "description": "Original unit in good condition.",
                "price": "RM 1,250",
                "category": "Laptops",
                "source": "extension",
            },
            files=[("images", ("listing.jpg", make_image(), "image/jpeg"))],
            headers=headers,
        )
        assert accepted.status_code == 202, accepted.text
        assessment_id = accepted.json()["assessment_id"]
        cancel = client.post(f"/api/v1/assess/{assessment_id}/cancel", headers=headers)
        assert cancel.status_code == 204


def test_a_wildcard_allowed_origin_is_refused_because_the_api_sends_credentials() -> None:
    """The settings reject "*" as an allowed origin and accept a listed origin."""
    # CORS with credentials and "*" would let any website read the visitor's results, so the
    # settings refuse to start with it. A listed origin is fine.
    with pytest.raises(ValueError, match="wildcard"):
        Settings(_env_file=None, guardianlens_allowed_origins="*")  # type: ignore[arg-type, call-arg]
    ok = Settings(_env_file=None, guardianlens_allowed_origins="http://localhost:3000")  # type: ignore[arg-type, call-arg]
    assert ok.guardianlens_allowed_origins == ["http://localhost:3000"]
