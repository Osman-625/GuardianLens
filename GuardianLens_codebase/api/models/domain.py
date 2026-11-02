# The server's internal records, as plain dataclasses: an uploaded image, the seller details a
# buyer supplied, one assessment (inputs, progress, and result), and one piece of feedback.
# These are what the repositories store; the API's request and response shapes live in schemas.py.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from api.schemas import (
    AssessmentResultResponse,
    AssessmentStatus,
    FeedbackVerdict,
    PipelineStage,
)


@dataclass(slots=True)
class ImageInput:
    """One uploaded photo after validation and re-encoding, with its hash and pixel size."""

    filename: str
    mime: str
    content: bytes
    sha256: str
    width_px: int
    height_px: int


@dataclass(slots=True)
class SellerInput:
    """The optional seller details a buyer supplied; each is None when it is not known."""

    account_age_days: int | None = None
    rating: float | None = None
    review_count: int | None = None
    active_listing_count: int | None = None

    def missing_flags(self) -> dict[str, bool]:
        """Returns, for each seller field, whether it is missing (True) or was supplied (False)."""
        return {
            "account_age_days": self.account_age_days is None,
            "rating": self.rating is None,
            "review_count": self.review_count is None,
            "active_listing_count": self.active_listing_count is None,
        }


@dataclass(slots=True)
class AssessmentRecord:
    """One assessment: its session, inputs, progress, and result.

    The scrubbed title has contact details removed and is the one stored and shown in history.
    The `_for_inference` texts keep the buyer's own wording for the models to read; they are never
    stored.
    """

    session_id: UUID
    platform: str
    title_scrubbed: str
    title_for_inference: str
    description_for_inference: str
    category: str
    price: float
    language_detected: str
    seller: SellerInput
    images: list[ImageInput]
    id: UUID = field(default_factory=uuid4)
    status: AssessmentStatus = AssessmentStatus.PROCESSING
    stage: PipelineStage | None = PipelineStage.VISUAL
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    result: AssessmentResultResponse | None = None
    error_code: str | None = None
    error_message: str | None = None
    # Where the submission came from ("extension" or "manual") and how its values were
    # captured. Research metadata only: it is never read by the scoring pipeline.
    source: str = "manual"
    capture_meta: dict[str, object] | None = None


@dataclass(slots=True)
class FeedbackRecord:
    """The buyer's feedback on one assessment: a verdict and an optional scrubbed comment."""

    assessment_id: UUID
    verdict: FeedbackVerdict
    comment_scrubbed: str | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
