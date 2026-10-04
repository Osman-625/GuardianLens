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
    filename: str
    mime: str
    content: bytes
    sha256: str
    width_px: int
    height_px: int


@dataclass(slots=True)
class SellerInput:
    account_age_days: int | None = None
    rating: float | None = None
    review_count: int | None = None
    active_listing_count: int | None = None

    def missing_flags(self) -> dict[str, bool]:
        return {
            "account_age_days": self.account_age_days is None,
            "rating": self.rating is None,
            "review_count": self.review_count is None,
            "active_listing_count": self.active_listing_count is None,
        }


@dataclass(slots=True)
class AssessmentRecord:
    session_id: UUID
    platform: str
    title_scrubbed: str
    description_scrubbed: str
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


@dataclass(slots=True)
class FeedbackRecord:
    assessment_id: UUID
    verdict: FeedbackVerdict
    comment_scrubbed: str | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
