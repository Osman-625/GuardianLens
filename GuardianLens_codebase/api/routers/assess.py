# Assessment endpoints: submit a listing (multipart form with 1 to 10 photos), poll its processing
# stage, fetch the finished result, cancel it, and list the session's history. Submission validates
# every field before any scoring starts, and records whether it came from the browser extension or
# the manual form (and, for the extension, the per-field capture metadata).
from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, Response, UploadFile, status

from api.dependencies import (
    get_app_settings,
    get_rate_limiter,
    get_repository,
    parse_session,
    require_owned_assessment,
    require_trusted_origin,
    session_header_value,
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
from api.services.capture_meta import parse_capture_meta, parse_source
from api.services.images import ImageLimits, validate_and_reencode_images
from api.services.language import detect_supported_language
from api.services.orchestrator import run_development_assessment
from api.services.privacy import scrub_pii

router = APIRouter(prefix="/api/v1", tags=["assessments"])

# The largest price or seller count accepted. The models read these as 32-bit floats, and a
# number beyond about 3.4e38 makes the scoring fail, so a typo like 1e300 must be a 422.
MAX_NUMBER = 10_000_000
MAX_NUMBER_TEXT = f"{MAX_NUMBER:,}"

# A price as people write it: an optional RM or MYR, then digits with optional comma thousands and
# up to two decimals ("1250", "rm 1,250.50"). Anything else is refused rather than guessed: float()
# would read "1.250,00" as 1.25, a 1000-fold mistake that no one would see.
_PRICE = re.compile(
    r"(?:RM|MYR)?\s*(?P<whole>\d{1,3}(?:,\d{3})+|\d+)(?P<cents>\.\d{1,2})?", re.IGNORECASE
)


def _optional_int(value: str | None, field: str) -> int | None:
    """Reads an optional whole number from a form value.

    Returns None when the value is absent or empty; raises a 422 for text that is not a whole
    number, is negative, or is above MAX_NUMBER, naming `field`.
    """
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise AppError(422, "invalid_integer", "Enter a whole number.", field) from exc
    if parsed < 0:
        raise AppError(422, "negative_value", "Enter zero or a positive number.", field)
    if parsed > MAX_NUMBER:
        raise AppError(422, "value_too_large", f"Enter {MAX_NUMBER_TEXT} or less.", field)
    return parsed


def _optional_rating(value: str | None) -> float | None:
    """Reads an optional seller rating from a form value.

    Returns None when the value is absent or empty; raises a 422 unless it is a number from 0 to 5.
    """
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
    source: Annotated[str, Form()] = "manual",
    capture_meta: Annotated[str | None, Form()] = None,
) -> AssessAccepted:
    """Accepts a listing for assessment and starts scoring it in the background.

    The steps, in order: refuse a cross-site request, find the buyer's session and apply its rate
    limit, validate every field, re-encode the photos, create the session of a new buyer, save the
    assessment, and queue the scoring. The answer is the new assessment's id (202); the buyer then
    polls its status. (Before any of this, main.py's upload middleware has checked the upload's
    size and the per-address rate limit.)
    """
    # First, before any session is created or any upload is read: refuse a cross-site browser
    # request that would otherwise run on the visitor's cookie.
    require_trusted_origin(request)
    settings = get_app_settings(request)
    repository = get_repository(request)

    session_id = parse_session(request, required=False)
    if session_id is None:
        # A client that sent the header but whose token is unknown (for example the server
        # restarted) must be told, so it can mint a new session and retry. Silently creating
        # a cookie session would leave it holding a token that no longer matches anything.
        if session_header_value(request) is not None:
            raise AppError(401, "session_invalid", "Your session expired. Reconnect and try again.")
    else:
        get_rate_limiter(request).check(str(session_id))

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
    # Category is free text; only its length is limited.
    if len(category) > settings.guardianlens_category_max_length:
        raise AppError(
            422,
            "category_too_long",
            f"Use {settings.guardianlens_category_max_length} characters or fewer.",
            "category",
        )
    clean_source = parse_source(source)
    parsed_meta = parse_capture_meta(capture_meta, clean_source)
    if platform not in {"mudah", "carousell", "other"}:
        raise AppError(422, "invalid_platform", "Choose Mudah or Carousell.", "platform")
    written = _PRICE.fullmatch(price.strip())
    if written is None:
        raise AppError(422, "invalid_price", "Enter a valid non-negative price.", "price")
    numeric_price = float(written["whole"].replace(",", "") + (written["cents"] or ""))
    if numeric_price > MAX_NUMBER:
        message = f"Enter a price of {MAX_NUMBER_TEXT} or less."
        raise AppError(422, "invalid_price", message, "price")

    language = detect_supported_language(f"{title} {description}")
    if language == "unsupported":
        raise AppError(
            422,
            "unsupported_language",
            "Listings written mostly in Chinese or another non-Latin script are outside this "
            "prototype's supported language scope.",
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
    if session_id is None:
        # Only now that the form is valid: a refused first submission answers with an error that
        # carries no cookie, so a session made earlier would be one the buyer never receives.
        session_id = repository.create_session()
        response.set_cookie(
            key=settings.guardianlens_session_cookie,
            value=str(session_id),
            httponly=True,
            samesite="lax",
            secure=settings.guardianlens_env == "production",
        )
        get_rate_limiter(request).check(str(session_id))
    assessment = AssessmentRecord(
        session_id=session_id,
        platform=platform,
        title_scrubbed=scrub_pii(title),
        title_for_inference=title,
        description_for_inference=description,
        category=category,
        price=numeric_price,
        language_detected=language,
        seller=seller,
        images=clean_images,
        source=clean_source,
        capture_meta=parsed_meta,
    )
    repository.save_assessment(assessment)
    background_tasks.add_task(
        run_development_assessment, assessment, repository, request.app.state.trained_models
    )
    return AssessAccepted(assessment_id=assessment.id)


@router.get("/assess/{assessment_id}/status", response_model=AssessmentStatusResponse)
def get_status(request: Request, assessment_id: UUID) -> AssessmentStatusResponse:
    """Returns the processing status and current stage of one of the caller's assessments."""
    assessment = require_owned_assessment(request, assessment_id)
    return AssessmentStatusResponse(
        status=assessment.status,
        stage=assessment.stage,
        message=assessment.error_message,
    )


@router.get("/assess/{assessment_id}/result", response_model=AssessmentResultResponse)
def get_result(request: Request, assessment_id: UUID) -> AssessmentResultResponse:
    """Returns the finished result, or a 409 error while it is not ready or if the check failed."""
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
    """Marks a still-running assessment as abandoned; a finished one is left unchanged."""
    require_trusted_origin(request)
    assessment = require_owned_assessment(request, assessment_id)
    if assessment.status.value == "processing":
        assessment.status = AssessmentStatus.ABANDONED
        assessment.stage = None
        get_repository(request).save_assessment(assessment)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/session/history", response_model=list[HistoryItem])
def get_history(request: Request) -> list[HistoryItem]:
    """Lists the caller's finished assessments (title, score, band); empty without a session."""
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
