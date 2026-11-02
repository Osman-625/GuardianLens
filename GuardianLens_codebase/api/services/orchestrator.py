# Runs one assessment through the five stages (visual, textual, behavioural, fusion, explanation)
# in the background and stores the outcome. It uses the trained models when they are loaded and
# the explicit development stubs otherwise. The buyer's raw text and the photo bytes are cleared
# as soon as the assessment ends, whether it succeeded or failed.
from __future__ import annotations

import time
from datetime import UTC, datetime

from api.models.domain import AssessmentRecord
from api.repositories.assessments import AssessmentRepository
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
from api.services.trained_models import TrainedModels

# What the API calls the model bundle while it serves placeholder scores (see /health).
STUB_BUNDLE_LABEL = "dev-stub-unvalidated"

# The caveat shown with every score, the extra warning shown only on stub scores, and the manual
# checks every result suggests.
DISCLAIMER = (
    "GuardianLens supports your judgement. It cannot confirm that a listing is fraudulent or safe. "
    "Verify the seller and payment details yourself before paying."
)
DEVELOPMENT_NOTICE = (
    "Test mode: this score is placeholder data. Do not use it as research evidence or to judge "
    "a real listing."
)
SUGGESTED_CHECKS = [
    "Compare the price with similar listings on the same marketplace.",
    "Ask for a new photo of the item next to a handwritten note.",
    "Keep chat and payment inside the marketplace where possible.",
    "Check the seller's account or bank details on the official Semak Mule service.",
]


def _to_card(output: SignalOutput) -> SignalCard:
    """Converts one signal's output into the card shown on the result."""
    return SignalCard(
        signal=output.signal,
        probability=output.probability,
        available=output.available,
        status_word=output.status_word,
        summary=output.summary,
        reasons=output.reasons,
        scope_note=output.scope_note,
    )


# The highest stub risk (0 to 100, higher is riskier) of the Low band and of the Moderate band.
# Placeholders that only exercise the interface. The score shown to the buyer is 100 minus the risk.
STUB_LOW_MAX = 33
STUB_MODERATE_MAX = 66


def _stub_band(risk: int) -> RiskBand:
    """Maps a stub risk to a band with the fixed development boundaries above."""
    if risk <= STUB_LOW_MAX:
        return RiskBand.LOW
    if risk <= STUB_MODERATE_MAX:
        return RiskBand.MODERATE
    return RiskBand.HIGH


class _Cancelled(Exception):
    """The buyer cancelled the check while it was running."""


def _raise_if_cancelled(assessment: AssessmentRecord, repository: AssessmentRepository) -> None:
    """Raises _Cancelled when the stored copy of the assessment has been marked abandoned."""
    stored = repository.get_assessment(assessment.id)
    if stored is not None and stored.status == AssessmentStatus.ABANDONED:
        raise _Cancelled


def _begin_stage(
    stage: PipelineStage, assessment: AssessmentRecord, repository: AssessmentRepository
) -> None:
    """Stops if the buyer cancelled; otherwise saves the stage as started, for the status page."""
    _raise_if_cancelled(assessment, repository)
    assessment.stage = stage
    repository.save_assessment(assessment)


def _clear_raw_inputs(assessment: AssessmentRecord) -> None:
    """Drops the buyer's raw wording and the photo bytes: they are only needed for scoring."""
    assessment.title_for_inference = ""
    assessment.description_for_inference = ""
    for image in assessment.images:
        image.content = b""


def run_development_assessment(
    assessment: AssessmentRecord,
    repository: AssessmentRepository,
    models: TrainedModels | None = None,
) -> None:
    """Runs the configured model bundle, or the explicit development stubs, for one assessment.

    Each stage is saved as it starts, so the status endpoint can report real progress. On success
    the result is stored and the assessment is marked complete; on any error it is marked failed
    with a plain message and the error is raised again. If the buyer cancels, the next stage
    check stops the run: the assessment stays abandoned, gets no result, and its raw inputs are
    cleared. The repository never overwrites a cancelled check, so a result that finishes just
    after the buyer pressed Cancel cannot undo it.
    """

    started = time.perf_counter()
    try:
        _begin_stage(PipelineStage.VISUAL, assessment, repository)
        visual = models.run_visual(assessment) if models else run_visual_stub(assessment.images)

        _begin_stage(PipelineStage.TEXTUAL, assessment, repository)
        textual = (
            models.run_textual(assessment)
            if models
            else run_textual_stub(
                assessment.title_for_inference, assessment.description_for_inference
            )
        )

        _begin_stage(PipelineStage.BEHAVIOURAL, assessment, repository)
        behavioural = (
            models.run_behavioural(assessment)
            if models
            else run_behavioural_stub(assessment.seller, assessment.price)
        )

        _begin_stage(PipelineStage.FUSION, assessment, repository)
        available = [
            output.probability
            for output in (visual, textual, behavioural)
            if output.available and output.probability is not None
        ]
        if models:
            score, band = models.fuse([visual, textual, behavioural])
        else:
            risk = round(sum(available) / len(available) * 100)
            score = 100 - risk
            band = _stub_band(risk)

        _begin_stage(PipelineStage.EXPLANATION, assessment, repository)
        outputs = (visual, textual, behavioural)
        unknown = sum(1 for output in outputs if not output.available)
        missing_notices = (
            [
                f"This result uses {len(outputs) - unknown} of {len(outputs)} checks. "
                "A check that could not run is unknown, not suspicious."
            ]
            if unknown
            else []
        )
        total_latency_ms = round((time.perf_counter() - started) * 1000)
        result = AssessmentResultResponse(
            assessment_id=assessment.id,
            title=assessment.title_scrubbed,
            score=score,
            band=band,
            signal_cards=[_to_card(output) for output in (visual, textual, behavioural)],
            missing_data_notices=missing_notices,
            suggested_checks=SUGGESTED_CHECKS,
            disclaimer=(DISCLAIMER if models else f"{DEVELOPMENT_NOTICE} {DISCLAIMER}"),
            model_bundle_label=models.label if models else STUB_BUNDLE_LABEL,
            created_at=assessment.created_at,
            total_latency_ms=total_latency_ms,
            development_stub=models is None,
        )
        _raise_if_cancelled(assessment, repository)
        assessment.result = result
        assessment.status = AssessmentStatus.COMPLETE
        assessment.stage = None
        assessment.completed_at = datetime.now(UTC)
        _clear_raw_inputs(assessment)
        repository.save_assessment(assessment)
    except _Cancelled:
        # Set again in case the stored copy is not this object: saving must not undo the cancel.
        assessment.status = AssessmentStatus.ABANDONED
        assessment.stage = None
        _clear_raw_inputs(assessment)
        repository.save_assessment(assessment)
    except Exception:
        assessment.status = AssessmentStatus.FAILED
        assessment.stage = None
        assessment.error_code = "pipeline_failed"
        assessment.error_message = (
            "The check could not be completed. Try again with the saved form."
        )
        _clear_raw_inputs(assessment)
        repository.save_assessment(assessment)
        raise
