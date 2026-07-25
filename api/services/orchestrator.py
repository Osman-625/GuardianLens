from __future__ import annotations

import time
from datetime import UTC, datetime

from api.models.domain import AssessmentRecord
from api.repositories.base import AssessmentRepository
from api.schemas import (
    AssessmentResultResponse,
    AssessmentStatus,
    PipelineStage,
    RiskBand,
    SignalCard,
)
from api.services.pipelines import (
    SignalOutput,
    run_behavioural_stub,
    run_textual_stub,
    run_visual_stub,
)

DISCLAIMER = (
    "GuardianLens supports your judgement and cannot confirm whether a listing is fraudulent. "
    "Verify the seller and payment details independently before paying."
)
DEVELOPMENT_NOTICE = (
    "Development stub output. It is not produced by the trained GuardianLens models and must not "
    "be used as research evidence or as a real fraud assessment."
)
SUGGESTED_CHECKS = [
    "Compare the price with similar listings on the same marketplace.",
    "Ask for a new photo showing the item with a specific handwritten note.",
    "Keep communication and payment inside the marketplace where possible.",
    "Verify account or bank details independently using the official Semak Mule service.",
]


def _to_card(output: SignalOutput) -> SignalCard:
    return SignalCard(
        signal=output.signal,
        probability=output.probability,
        available=output.available,
        status_word=output.status_word,
        summary=output.summary,
        reasons=output.reasons,
        scope_note=output.scope_note,
    )


def _stub_band(score: int) -> RiskBand:
    if score <= 33:
        return RiskBand.LOW
    if score <= 66:
        return RiskBand.MODERATE
    return RiskBand.HIGH


def run_development_assessment(
    assessment: AssessmentRecord,
    repository: AssessmentRepository,
) -> None:
    """Run contract-complete development stubs in the five committed stages."""

    started = time.perf_counter()
    try:
        assessment.stage = PipelineStage.VISUAL
        repository.save_assessment(assessment)
        visual = run_visual_stub(assessment.images)

        assessment.stage = PipelineStage.TEXTUAL
        repository.save_assessment(assessment)
        textual = run_textual_stub(assessment.title_for_inference, assessment.description_for_inference)

        assessment.stage = PipelineStage.BEHAVIOURAL
        repository.save_assessment(assessment)
        behavioural = run_behavioural_stub(assessment.seller, assessment.price)

        assessment.stage = PipelineStage.FUSION
        repository.save_assessment(assessment)
        available = [
            output.probability
            for output in (visual, textual, behavioural)
            if output.available and output.probability is not None
        ]
        fused = sum(available) / len(available)
        score = round(fused * 100)
        band = _stub_band(score)

        assessment.stage = PipelineStage.EXPLANATION
        repository.save_assessment(assessment)
        missing_notices = [
            output.summary
            for output in (visual, textual, behavioural)
            if not output.available
        ]
        total_latency_ms = round((time.perf_counter() - started) * 1000)
        result = AssessmentResultResponse(
            assessment_id=assessment.id,
            title=assessment.title_scrubbed,
            score=score,
            band=band,
            signal_cards=[_to_card(output) for output in (visual, textual, behavioural)],
            missing_data_notices=missing_notices,
            suggested_checks=SUGGESTED_CHECKS,
            disclaimer=f"{DEVELOPMENT_NOTICE} {DISCLAIMER}",
            model_bundle_label="dev-stub-unvalidated",
            created_at=assessment.created_at,
            total_latency_ms=total_latency_ms,
            development_stub=True,
        )
        assessment.result = result
        assessment.status = AssessmentStatus.COMPLETE
        assessment.stage = None
        assessment.completed_at = datetime.now(UTC)
        assessment.title_for_inference = ""
        assessment.description_for_inference = ""
        for image in assessment.images:
            image.content = b""
        repository.save_assessment(assessment)
    except Exception:
        assessment.status = AssessmentStatus.FAILED
        assessment.stage = None
        assessment.error_code = "pipeline_failed"
        assessment.error_message = "The check could not be completed. Try again with the saved form."
        assessment.title_for_inference = ""
        assessment.description_for_inference = ""
        for image in assessment.images:
            image.content = b""
        repository.save_assessment(assessment)
        raise
