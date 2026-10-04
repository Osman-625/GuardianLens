from __future__ import annotations

import math
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, Response, UploadFile, status

from api.dependencies import (
    get_app_settings,
    get_rate_limiter,
    get_repository,
    parse_session,
    require_owned_assessment,
)
from api.errors import AppError
from api.models.domain import AssessmentRecord, SellerInput
from api.schemas import (
    AssessAccepted,
    AssessmentResultResponse,
    AssessmentStatus,
    AssessmentStatusResponse,
    HistoryItem,
)
from api.services.images import ImageLimits, validate_and_reencode_images
from api.services.language import detect_supported_language
from api.services.orchestrator import run_development_assessment
from api.services.privacy import scrub_pii

router = APIRouter(prefix="/api/v1", tags=["assessments"])


def _optional_int(value: str | None, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise AppError(422, "invalid_integer", "Enter a whole number.", field) from exc
    if parsed < 0:
        raise AppError(422, "negative_value", "Enter zero or a positive number.", field)
    return parsed


def _optional_rating(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise AppError(422, "invalid_rating", "Enter a rating from 0 to 5.", "rating") from exc
    if not 0 <= parsed <= 5:
        raise AppError(422, "invalid_rating", "Enter a rating from 0 to 5.", "rating")
    return parsed


@router.post("/assess", response_model=AssessAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_assessment(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    images: Annotated[list[UploadFile], File(...)],
    title: Annotated[str, Form(...)],
    description: Annotated[str, Form(...)],
    price: Annotated[str, Form(...)],
    category: Annotated[str, Form(...)],
    platform: Annotated[str, Form()] = "other",
    account_age_days: Annotated[str | None, Form()] = None,
    rating: Annotated[str | None, Form()] = None,
    review_count: Annotated[str | None, Form()] = None,
    active_listing_count: Annotated[str | None, Form()] = None,
) -> AssessAccepted:
    settings = get_app_settings(request)
    repository = get_repository(request)

    session_id = parse_session(request, required=False)
    if session_id is None:
        session_id = repository.create_session()
        response.set_cookie(
            key=settings.guardianlens_session_cookie,
            value=str(session_id),
            httponly=True,
            samesite="lax",
            secure=settings.guardianlens_env == "production",
        )
    get_rate_limiter(request).check(session_id)

    title = title.strip()
    description = description.strip()
    category = category.strip()
    if not title:
        raise AppError(422, "title_required", "Enter the listing title.", "title")
    if len(title) > settings.guardianlens_title_max_length:
        raise AppError(
            422,
            "title_too_long",
            f"Use {settings.guardianlens_title_max_length} characters or fewer.",
            "title",
        )
    if not description:
        raise AppError(422, "description_required", "Enter the listing description.", "description")
    if len(description) > settings.guardianlens_description_max_length:
        raise AppError(
            422,
            "description_too_long",
            f"Use {settings.guardianlens_description_max_length} characters or fewer.",
            "description",
        )
    if not category:
        raise AppError(422, "category_required", "Choose a category.", "category")
    if platform not in {"mudah", "carousell", "other"}:
        raise AppError(422, "invalid_platform", "Choose Mudah or Carousell.", "platform")
    try:
        numeric_price = float(price.replace("RM", "").replace(",", "").strip())
    except ValueError as exc:
        raise AppError(422, "invalid_price", "Enter a valid non-negative price.", "price") from exc
    if not math.isfinite(numeric_price) or numeric_price < 0:
        raise AppError(422, "invalid_price", "Enter a valid non-negative price.", "price")

    language = detect_supported_language(f"{title} {description}")
    if language == "unsupported":
        raise AppError(
            422,
            "unsupported_language",
            "Chinese-dominant listings are outside this prototype's supported language scope.",
            "description",
        )

    clean_images = await validate_and_reencode_images(
        images,
        ImageLimits(
            max_images=settings.guardianlens_max_images,
            max_bytes=settings.guardianlens_max_image_bytes,
        ),
    )
    seller = SellerInput(
        account_age_days=_optional_int(account_age_days, "account_age_days"),
        rating=_optional_rating(rating),
        review_count=_optional_int(review_count, "review_count"),
        active_listing_count=_optional_int(active_listing_count, "active_listing_count"),
    )
    assessment = AssessmentRecord(
        session_id=session_id,
        platform=platform,
        title_scrubbed=scrub_pii(title),
        description_scrubbed=scrub_pii(description),
        title_for_inference=title,
        description_for_inference=description,
        category=category,
        price=numeric_price,
        language_detected=language,
        seller=seller,
        images=clean_images,
    )
    repository.save_assessment(assessment)
    background_tasks.add_task(run_development_assessment, assessment, repository)
    return AssessAccepted(assessment_id=assessment.id)


@router.get("/assess/{assessment_id}/status", response_model=AssessmentStatusResponse)
def get_status(request: Request, assessment_id: UUID) -> AssessmentStatusResponse:
    assessment = require_owned_assessment(request, assessment_id)
    return AssessmentStatusResponse(
        status=assessment.status,
        stage=assessment.stage,
        message=assessment.error_message,
    )


@router.get("/assess/{assessment_id}/result", response_model=AssessmentResultResponse)
def get_result(request: Request, assessment_id: UUID) -> AssessmentResultResponse:
    assessment = require_owned_assessment(request, assessment_id)
    if assessment.result is None:
        if assessment.status.value == "failed":
            raise AppError(
                409, "assessment_failed", assessment.error_message or "Assessment failed."
            )
        raise AppError(409, "result_not_ready", "The assessment result is not ready yet.")
    return assessment.result


@router.post("/assess/{assessment_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_assessment(request: Request, assessment_id: UUID) -> Response:
    assessment = require_owned_assessment(request, assessment_id)
    if assessment.status.value == "processing":
        assessment.status = AssessmentStatus.ABANDONED
        assessment.stage = None
        get_repository(request).save_assessment(assessment)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/session/history", response_model=list[HistoryItem])
def get_history(request: Request) -> list[HistoryItem]:
    session_id = parse_session(request, required=False)
    if session_id is None:
        return []
    records = get_repository(request).list_session_assessments(session_id)
    return [
        HistoryItem(
            assessment_id=record.id,
            title=record.title_scrubbed,
            score=record.result.score,
            band=record.result.band,
            created_at=record.created_at,
        )
        for record in records
        if record.result is not None
    ]
