# Shared request helpers for the routers: access to the app's repository, rate limiter, and
# settings; reading the anonymous session from the request (the X-Session-Token header sent by the
# browser extension, or the cookie set for the website); the ownership check that keeps one
# session's results invisible to another.
from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import Request

from api.errors import AppError
from api.models.domain import AssessmentRecord
from api.repositories.assessments import AssessmentRepository
from api.services.rate_limit import RateLimiter
from api.settings import Settings


def get_repository(request: Request) -> AssessmentRepository:
    """Returns the repository that the app opened at start-up."""
    return cast(AssessmentRepository, request.app.state.repository)


def get_rate_limiter(request: Request) -> RateLimiter:
    """Returns the per-session rate limiter that the app built at start-up."""
    return cast(RateLimiter, request.app.state.rate_limiter)


def check_ip_rate_limit(request: Request) -> None:
    """Counts this request against its network address, or raises a 429 when it is over.

    Call it before a session is created: a client that sends no cookie gets a new session every
    time, so only its address stays the same.
    """
    address = request.client.host if request.client else "unknown"
    cast(RateLimiter, request.app.state.ip_rate_limiter).check(address)


def get_app_settings(request: Request) -> Settings:
    """Returns the settings that the app loaded at start-up."""
    return cast(Settings, request.app.state.settings)


# Header the browser extension uses to send its session token. Starlette lower-cases header
# names when reading them, so the constant is lower case.
SESSION_HEADER = "x-session-token"


def session_header_value(request: Request) -> str | None:
    """Returns the X-Session-Token header value, or None when the client did not send one."""
    return request.headers.get(SESSION_HEADER) or None


def require_trusted_origin(request: Request) -> None:
    """Refuses a state-changing request that a browser sent from an origin this API does not serve.

    Browsers put an Origin header on every cross-site POST. A page on another site can send a POST
    with no Content-Type, which counts as a "simple" request: the browser skips the CORS
    preflight, and without this check the API would still run it. That would let the page use the
    visitor's cookie (or set a cookie, on the claim route) without the visitor knowing.

    The check passes when:
      - there is no Origin header (scripts, tests, same-origin tools: not a cross-site browser);
      - the request carries X-Session-Token (the browser extension; a page on another site cannot
        add that header without a preflight the CORS layer refuses); or
      - the Origin is one of the configured allowed origins (the website).

    Call it first in every route that changes data and can be authenticated by the cookie.
    """
    origin = request.headers.get("origin")
    if origin is None or session_header_value(request) is not None:
        return
    allowed = {item.rstrip("/") for item in get_app_settings(request).guardianlens_allowed_origins}
    if origin.rstrip("/") not in allowed:
        raise AppError(
            403, "origin_not_allowed", "This request came from an origin that is not allowed."
        )


def parse_session(request: Request, *, required: bool = True) -> UUID | None:
    """Identifies the buyer's session from the request.

    The extension sends its token in the X-Session-Token header; the website sends the httpOnly
    cookie. The header wins when both are present. A missing, malformed, or unknown value is
    handled the same way: with `required=True` it raises the generic "not found" error, so the
    existence of an assessment is never revealed to the wrong caller; otherwise it returns None.
    """
    settings = get_app_settings(request)
    raw = session_header_value(request) or request.cookies.get(settings.guardianlens_session_cookie)
    if not raw:
        if required:
            raise AppError(404, "not_found", "The requested assessment was not found.")
        return None
    try:
        session_id = UUID(raw)
    except ValueError as exc:
        if required:
            raise AppError(404, "not_found", "The requested assessment was not found.") from exc
        return None
    repository = get_repository(request)
    if not repository.session_exists(session_id):
        if required:
            raise AppError(404, "not_found", "The requested assessment was not found.")
        return None
    return session_id


def require_owned_assessment(request: Request, assessment_id: UUID) -> AssessmentRecord:
    """Returns the assessment when it belongs to the caller's session; otherwise raises "not found".

    An assessment that does not exist and one that belongs to another session are answered
    identically, so a caller can never learn that someone else's assessment exists.
    """
    session_id = parse_session(request, required=True)
    repository = get_repository(request)
    assessment = repository.get_assessment(assessment_id)
    if assessment is None or assessment.session_id != session_id:
        raise AppError(404, "not_found", "The requested assessment was not found.")
    return assessment
