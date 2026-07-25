from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from api.dependencies import get_repository, require_owned_assessment
from api.models.domain import FeedbackRecord
from api.schemas import FeedbackRequest
from api.services.privacy import scrub_pii

router = APIRouter(prefix="/api/v1", tags=["feedback"])


@router.post("/assess/{assessment_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def save_feedback(request: Request, assessment_id: UUID, payload: FeedbackRequest) -> Response:
    require_owned_assessment(request, assessment_id)
    comment = scrub_pii(payload.comment) if payload.comment else None
    feedback = FeedbackRecord(
        assessment_id=assessment_id,
        verdict=payload.verdict,
        comment_scrubbed=comment,
        updated_at=datetime.now(UTC),
    )
    get_repository(request).save_feedback(feedback)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
