# Application factory: builds the FastAPI app from the settings, opens the SQLite repository,
# configures CORS for the website and the extension, registers the error handlers that produce the
# API's error envelope, and mounts the routers.
from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.dependencies import check_ip_rate_limit
from api.errors import AppError
from api.repositories.assessments import AssessmentRepository
from api.routers import assess, feedback, health, session
from api.schemas import ErrorDetail, ErrorEnvelope
from api.services.rate_limit import RateLimiter
from api.services.trained_models import TrainedModels
from api.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Builds the app's shared services at start-up and keeps them on `app.state`.

    That is the settings, the saved models (only in trained mode, loaded and warmed up once here,
    so a missing file stops the start-up instead of failing a request, and the first buyer does not
    wait for the first model call), the repository, and the two rate limiters (per session and
    per network address).
    """
    settings = get_settings()
    app.state.settings = settings
    app.state.trained_models = (
        TrainedModels(settings) if settings.guardianlens_inference_mode == "trained" else None
    )
    if app.state.trained_models:
        app.state.trained_models.warm_up()
    app.state.repository = AssessmentRepository(settings.guardianlens_database_path)
    app.state.rate_limiter = RateLimiter(settings.guardianlens_rate_limit_per_minute)
    app.state.ip_rate_limiter = RateLimiter(settings.guardianlens_rate_limit_per_ip_per_minute)
    yield
    app.state.repository.close()


def _refusal(status_code: int, code: str, message: str) -> JSONResponse:
    """A response in the API's standard error envelope, for a request refused before any route."""
    payload = ErrorEnvelope(error=ErrorDetail(code=code, message=message, field=None))
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def create_app() -> FastAPI:
    """Creates the FastAPI application with its CORS rules, error handlers, and routers."""
    settings = get_settings()
    application = FastAPI(
        title="GuardianLens API",
        version="0.1.0",
        description=(
            "GuardianLens assessment API with explicit development stubs or "
            "saved TF-IDF, XGBoost, visual and calibrated fusion models."
        ),
        lifespan=lifespan,
    )

    # The most one check can upload: every photo at its size limit, plus 1 MB for the text fields
    # and the multipart framing.
    max_upload_bytes = (
        settings.guardianlens_max_images * settings.guardianlens_max_image_bytes + 1024 * 1024
    )

    # Added BEFORE the CORS layer, so CORS wraps it and the website can read a refusal.
    @application.middleware("http")
    async def limit_upload_size(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Refuses a bad upload from its headers, before any of it is read.

        In the route, FastAPI would already have copied the whole body to a temporary file and
        parsed it. So the length (browsers always state it), the content type, and the per-address
        rate limit are all checked here. Only a multipart form is accepted: a urlencoded body of
        many small fields keeps the server busy for minutes, and the website and extension never
        send one.
        """
        if request.method == "POST" and request.url.path == "/api/v1/assess":
            length = request.headers.get("content-length", "")
            if not length.isdigit():
                return _refusal(411, "length_required", "The upload must state its size.")
            if int(length) > max_upload_bytes:
                return _refusal(413, "request_too_large", "The upload is too large.")
            kind = request.headers.get("content-type", "").lower()
            if not kind.startswith("multipart/form-data"):
                return _refusal(415, "unsupported_media_type", "Send the listing as a form.")
            try:
                check_ip_rate_limit(request)
            except AppError as error:
                return _refusal(error.status_code, error.code, error.message)
        return await call_next(request)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.guardianlens_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Session-Token"],
    )

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Answers a request that failed validation with a 422 naming the first bad field."""
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
        """Answers a deliberate AppError with its own status, code, message, and field."""
        del request
        payload = ErrorEnvelope(
            error=ErrorDetail(code=exc.code, message=exc.message, field=exc.field)
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Answers any other failure with a generic 500 that reveals no internal detail."""
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
    application.include_router(session.router)
    return application


# The application object that uvicorn serves (`uvicorn api.main:app`).
app = create_app()
