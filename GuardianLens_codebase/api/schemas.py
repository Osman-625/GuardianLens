# The API's request and response shapes (Pydantic models) and the enums they share. These define
# the JSON the website and the extension rely on; the shared TypeScript types mirror them.
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AssessmentStatus(StrEnum):
    """Lifecycle of one assessment on the server."""

    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    ABANDONED = "abandoned"


class PipelineStage(StrEnum):
    """The five processing stages, in the order they run."""

    VISUAL = "visual"
    TEXTUAL = "textual"
    BEHAVIOURAL = "behavioural"
    FUSION = "fusion"
    EXPLANATION = "explanation"


class SignalName(StrEnum):
    """The three independent signals shown as cards."""

    VISUAL = "visual"
    TEXTUAL = "textual"
    BEHAVIOURAL = "behavioural"


class RiskBand(StrEnum):
    """The three risk bands the fused score maps to."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class FeedbackVerdict(StrEnum):
    """What a buyer can say about a result."""

    HELPFUL = "helpful"
    UNCLEAR = "unclear"
    POTENTIALLY_INCORRECT = "potentially_incorrect"


class ErrorDetail(BaseModel):
    """One error: a stable code, a plain message, and the form field it concerns (if any)."""

    code: str
    message: str
    field: str | None = None


class ErrorEnvelope(BaseModel):
    """The JSON body of every error response."""

    error: ErrorDetail


class AssessAccepted(BaseModel):
    """Response of POST /api/v1/assess: the id to poll for status and result."""

    assessment_id: UUID


class SessionCreated(BaseModel):
    """Response of POST /api/v1/session: the opaque token a header-transport client stores."""

    session_token: UUID


class SessionClaimRequest(BaseModel):
    """Body of POST /api/v1/session/claim.

    `token` is typed as a UUID, so a malformed value is rejected with a 422 before any lookup.
    """

    token: UUID


class AssessmentStatusResponse(BaseModel):
    """Progress of a running assessment: its status, the stage now running, and any message."""

    status: AssessmentStatus
    stage: PipelineStage | None = None
    message: str | None = None


class SignalReason(BaseModel):
    """One plain-language reason behind a signal: whether it raises or lowers the risk."""

    feature_key: str
    direction: Literal["raises", "lowers"]
    display_text: str
    rank: int = Field(ge=1)


class SignalCard(BaseModel):
    """One of the three signal cards on a result.

    `probability` is None and `available` is False when the signal could not be computed; that
    means "unknown", never "safe" and never "suspicious".
    """

    signal: SignalName
    probability: float | None = Field(default=None, ge=0, le=1)
    available: bool
    status_word: str
    summary: str
    reasons: list[SignalReason] = Field(default_factory=list)
    scope_note: str | None = None


class AssessmentResultResponse(BaseModel):
    """A finished assessment: score, band, signal cards, notices, checks, and the disclaimer.

    `score` is 100 minus the estimated risk percentage: 100 is the lowest estimated risk.
    """

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
    """Body of POST /api/v1/assess/{id}/feedback: a verdict and an optional short comment."""

    verdict: FeedbackVerdict
    comment: str | None = Field(default=None, max_length=1000)


class HistoryItem(BaseModel):
    """One row of the session history list."""

    assessment_id: UUID
    title: str
    score: int = Field(ge=0, le=100)
    band: RiskBand
    created_at: datetime


# --- Capture metadata (extension submissions) --------------------------------------------
# The extension reports where each submitted value came from. The allowed hosts and field
# names are fixed lists so that a listing URL, a seller name, or any other free text can
# never be stored through this field.
PlatformHost = Literal["mudah.my", "www.mudah.my", "carousell.com.my", "www.carousell.com.my"]
CaptureField = Literal[
    "title",
    "description",
    "price",
    "category",
    "platform",
    "images",
    "account_age_days",
    "rating",
    "review_count",
    "active_listing_count",
]
CaptureStatus = Literal["captured", "edited", "not_found"]


class CaptureMeta(BaseModel):
    """What the extension reports about how a submission was captured.

    Stored for research evaluation only; it never feeds the score. `extra="forbid"` rejects
    any key not listed here.
    """

    model_config = ConfigDict(extra="forbid")

    # Version of the extraction code that produced the capture. A plain version number only
    # ("1", "1.2", "1.2.3"): it is the one string in this model, so it must not be able to carry a
    # URL, a phone number, or any other free text past the personal-data scrub.
    adapter_version: str = Field(pattern=r"^[0-9]{1,3}(\.[0-9]{1,3}){0,2}$")
    # Host only. The listing URL is deliberately not accepted anywhere.
    platform_host: PlatformHost
    # Per-field origin: read from the page, edited by the buyer, or not found.
    fields: dict[CaptureField, CaptureStatus]


class HealthResponse(BaseModel):
    """Response of GET /health: the API's mode, active bundle, and model readiness."""

    status: Literal["ok"]
    environment: str
    stub_mode: bool
    inference_mode: Literal["stub", "trained"] = "stub"
    model_bundle_label: str | None = None
    missing_model_artifacts: list[str] = Field(default_factory=list)
    visual_model_ready: bool = False
