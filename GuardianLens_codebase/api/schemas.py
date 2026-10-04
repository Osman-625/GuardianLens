from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AssessmentStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    ABANDONED = "abandoned"


class PipelineStage(StrEnum):
    VISUAL = "visual"
    TEXTUAL = "textual"
    BEHAVIOURAL = "behavioural"
    FUSION = "fusion"
    EXPLANATION = "explanation"


class SignalName(StrEnum):
    VISUAL = "visual"
    TEXTUAL = "textual"
    BEHAVIOURAL = "behavioural"


class RiskBand(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class FeedbackVerdict(StrEnum):
    HELPFUL = "helpful"
    UNCLEAR = "unclear"
    POTENTIALLY_INCORRECT = "potentially_incorrect"


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class AssessAccepted(BaseModel):
    assessment_id: UUID


class AssessmentStatusResponse(BaseModel):
    status: AssessmentStatus
    stage: PipelineStage | None = None
    message: str | None = None


class SignalReason(BaseModel):
    feature_key: str
    direction: Literal["raises", "lowers"]
    display_text: str
    rank: int = Field(ge=1)


class SignalCard(BaseModel):
    signal: SignalName
    probability: float | None = Field(default=None, ge=0, le=1)
    available: bool
    status_word: str
    summary: str
    reasons: list[SignalReason] = Field(default_factory=list)
    scope_note: str | None = None


class AssessmentResultResponse(BaseModel):
    assessment_id: UUID
    title: str
    score: int = Field(ge=0, le=100)
    band: RiskBand
    signal_cards: list[SignalCard]
    missing_data_notices: list[str]
    suggested_checks: list[str]
    disclaimer: str
    model_bundle_label: str
    created_at: datetime
    total_latency_ms: int = Field(ge=0)
    development_stub: bool = False


class FeedbackRequest(BaseModel):
    verdict: FeedbackVerdict
    comment: str | None = Field(default=None, max_length=1000)


class HistoryItem(BaseModel):
    assessment_id: UUID
    title: str
    score: int = Field(ge=0, le=100)
    band: RiskBand
    created_at: datetime


class AdminBundleSummary(BaseModel):
    label: str
    is_active: bool
    development_stub: bool
    component_versions: dict[str, str]
    band_boundaries: dict[str, int] | None


class AdminRecordSummary(BaseModel):
    assessment_id: UUID
    title: str
    band: RiskBand | None
    score: int | None
    status: AssessmentStatus
    created_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok"]
    environment: str
    stub_mode: bool


JsonDict = dict[str, Any]
