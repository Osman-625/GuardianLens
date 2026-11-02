# Feedback endpoint: saves the buyer's one-tap verdict (helpful, unclear, or potentially incorrect)
# and an optional comment on a finished assessment. Only the session that owns the assessment can
# give feedback, a request from an origin the API does not serve is refused, and the comment is
# scrubbed of personal details before it is stored.
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from api.dependencies import get_repository, require_owned_assessment, require_trusted_origin
from api.models.domain import FeedbackRecord
from api.schemas import FeedbackRequest
from api.services.privacy import scrub_pii

router = APIRouter(prefix="/api/v1", tags=["feedback"])


@router.post("/assess/{assessment_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def save_feedback(request: Request, assessment_id: UUID, payload: FeedbackRequest) -> Response:
    """Stores the buyer's verdict and scrubbed comment for one of the caller's assessments."""
    require_trusted_origin(request)
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
