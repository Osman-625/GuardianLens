from __future__ import annotations

from fastapi import APIRouter, Request

from api.dependencies import get_app_settings
from api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings = get_app_settings(request)
    return HealthResponse(
        status="ok",
        environment=settings.guardianlens_env,
        stub_mode=settings.guardianlens_stub_mode,
    )
