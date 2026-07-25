from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import Request

from api.errors import AppError
from api.repositories.base import AssessmentRepository
from api.services.rate_limit import SessionRateLimiter
from api.settings import Settings


def get_repository(request: Request) -> AssessmentRepository:
    return cast(AssessmentRepository, request.app.state.repository)


def get_rate_limiter(request: Request) -> SessionRateLimiter:
    return cast(SessionRateLimiter, request.app.state.rate_limiter)


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def parse_session(request: Request, *, required: bool = True) -> UUID | None:
    settings = get_app_settings(request)
    raw = request.cookies.get(settings.guardianlens_session_cookie)
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


def require_owned_assessment(request: Request, assessment_id: UUID):
    session_id = parse_session(request, required=True)
    repository = get_repository(request)
    assessment = repository.get_assessment(assessment_id)
    if assessment is None or assessment.session_id != session_id:
        raise AppError(404, "not_found", "The requested assessment was not found.")
    return assessment


def require_dev_admin(request: Request) -> None:
    settings = get_app_settings(request)
    expected = settings.guardianlens_dev_admin_token
    provided = request.headers.get("x-admin-token")
    if not expected or provided != expected:
        raise AppError(403, "admin_forbidden", "Administrator access is required.")
