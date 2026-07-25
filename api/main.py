from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from api.errors import AppError
from api.repositories.memory import InMemoryAssessmentRepository
from api.repositories.supabase import SupabaseAssessmentRepository
from api.routers import admin, assess, feedback, health
from api.schemas import ErrorDetail, ErrorEnvelope
from api.services.rate_limit import SessionRateLimiter
from api.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    app.state.repository = (
        InMemoryAssessmentRepository()
        if settings.guardianlens_stub_mode
        else SupabaseAssessmentRepository()
    )
    app.state.rate_limiter = SessionRateLimiter(settings.guardianlens_rate_limit_per_minute)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="GuardianLens API",
        version="0.1.0",
        description=(
            "FYP2 first-draft API. Stub mode is contract-complete but does not contain trained models."
        ),
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.guardianlens_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Admin-Token"],
    )

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        del request
        first = exc.errors()[0] if exc.errors() else {}
        location = first.get("loc", ())
        field = str(location[-1]) if location else None
        payload = ErrorEnvelope(
            error=ErrorDetail(
                code="validation_error",
                message="Check the highlighted field and try again.",
                field=field,
            )
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    @application.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        del request
        payload = ErrorEnvelope(
            error=ErrorDetail(code=exc.code, message=exc.message, field=exc.field)
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        del request, exc
        payload = ErrorEnvelope(
            error=ErrorDetail(
                code="internal_error",
                message="The request could not be completed. Try again.",
                field=None,
            )
        )
        return JSONResponse(status_code=500, content=payload.model_dump())

    application.include_router(health.router)
    application.include_router(assess.router)
    application.include_router(feedback.router)
    application.include_router(admin.router)
    return application


app = create_app()
