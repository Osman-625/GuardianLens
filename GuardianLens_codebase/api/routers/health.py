# The health endpoint: reports whether the API is up, which kind of scores it produces (development
# stub or trained), and whether the trained run's files and visual models are ready.
from __future__ import annotations

from fastapi import APIRouter, Request

from api.dependencies import get_app_settings
from api.schemas import HealthResponse
from api.services.trained_models import missing_artifacts

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Returns the API's status, inference mode, active bundle, and model readiness."""
    settings = get_app_settings(request)
    models = request.app.state.trained_models
    run_dir = settings.guardianlens_model_run_dir
    # Public page: no folder paths and no raw error text (the start-up log has the visual reason).
    return HealthResponse(
        status="ok",
        environment=settings.guardianlens_env,
        stub_mode=models is None,
        inference_mode=settings.guardianlens_inference_mode,
        model_bundle_label=models.label if models else "dev-stub-unvalidated",
        missing_model_artifacts=missing_artifacts(run_dir) if run_dir else [],
        visual_model_ready=bool(models and models.visual_engine),
    )
