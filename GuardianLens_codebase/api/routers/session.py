"""Session endpoints for clients that cannot rely on the website's cookie.

The browser extension has its own origin, so it keeps an opaque session token and sends it in
the X-Session-Token header. These endpoints mint that token and let the website adopt it:

  POST /api/v1/session        mint a new anonymous session and return its token
  POST /api/v1/session/claim  turn a token into this browser's httpOnly cookie, so the website
                              shows the same checks as the extension

A session is anonymous: it holds no account, name, or contact detail. The token is a random
UUID, and holding it is what proves ownership of the session's assessments.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from api.dependencies import (
    check_ip_rate_limit,
    get_app_settings,
    get_repository,
    require_trusted_origin,
)
from api.errors import AppError
from api.schemas import SessionClaimRequest, SessionCreated

router = APIRouter(prefix="/api/v1", tags=["session"])


@router.post("/session", response_model=SessionCreated, status_code=status.HTTP_201_CREATED)
def create_session(request: Request) -> SessionCreated:
    """Mints a new anonymous session and returns its token. No cookie is set."""
    check_ip_rate_limit(request)
    session_id = get_repository(request).create_session()
    return SessionCreated(session_token=session_id)


@router.post("/session/claim", status_code=status.HTTP_204_NO_CONTENT)
def claim_session(request: Request, payload: SessionClaimRequest) -> Response:
    """Attaches an existing session to the caller's browser by setting the session cookie.

    A request from an origin the API does not serve is refused first, so a page on another site
    cannot make a visitor's browser adopt its session. An unknown token gets a generic "not
    found" error. That does reveal whether a token exists, so this route's protection is the
    token's size (a random UUID, 122 bits, which cannot be guessed), not indistinguishability.
    """
    require_trusted_origin(request)
    settings = get_app_settings(request)
    if not get_repository(request).session_exists(payload.token):
        raise AppError(404, "not_found", "The requested session was not found.")
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        key=settings.guardianlens_session_cookie,
        value=str(payload.token),
        httponly=True,
        samesite="lax",
        secure=settings.guardianlens_env == "production",
    )
    return response
