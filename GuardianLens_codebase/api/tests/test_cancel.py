# Cancel tests: a check the buyer cancelled must stay cancelled. The scoring task re-reads the
# status before every stage and before saving, so it neither finishes a result nor undoes the
# cancel, and it still clears the buyer's raw wording and photo bytes.
from __future__ import annotations

from api.models.domain import AssessmentRecord, ImageInput, SellerInput
from api.repositories.assessments import AssessmentRepository
from api.schemas import AssessmentStatus
from api.services.orchestrator import run_development_assessment


def make_record(repository: AssessmentRepository) -> AssessmentRecord:
    """Stores a fresh, still-processing assessment with one photo and raw wording."""
    record = AssessmentRecord(
        session_id=repository.create_session(),
        platform="other",
        title_scrubbed="Used laptop",
        title_for_inference="Used laptop",
        description_for_inference="Good condition.",
        category="Electronics",
        price=1250.0,
        language_detected="en",
        seller=SellerInput(),
        images=[ImageInput("a.jpg", "image/jpeg", b"photo-bytes", "0" * 64, 640, 480)],
    )
    repository.save_assessment(record)
    return record


def assert_cancelled_and_cleared(record: AssessmentRecord) -> None:
    """The check ended abandoned, with no result, and the raw inputs are gone."""
    assert record.status == AssessmentStatus.ABANDONED
    assert record.result is None
    assert record.stage is None
    assert record.title_for_inference == record.description_for_inference == ""
    assert record.images[0].content == b""


def test_a_check_cancelled_before_it_starts_is_not_scored() -> None:
    """Cancel can land before the background task begins; the task must respect it."""
    repository = AssessmentRepository(":memory:")
    record = make_record(repository)
    record.status = AssessmentStatus.ABANDONED
    repository.save_assessment(record)  # what the cancel endpoint does

    run_development_assessment(record, repository, None)

    assert_cancelled_and_cleared(record)


def test_a_check_cancelled_mid_run_stays_cancelled() -> None:
    """Cancel during scoring stops the run at the next stage, with no result stored."""

    class CancelsAfterTwoSaves(AssessmentRepository):
        saves = 0

        def save_assessment(self, assessment: AssessmentRecord) -> None:
            super().save_assessment(assessment)
            self.saves += 1
            if self.saves == 2:  # the buyer presses Cancel while the textual stage is starting
                cancelled = self.get_assessment(assessment.id)
                assert cancelled is not None
                cancelled.status = AssessmentStatus.ABANDONED
                super().save_assessment(cancelled)

    repository = CancelsAfterTwoSaves(":memory:")
    record = make_record(repository)

    run_development_assessment(record, repository, None)

    assert_cancelled_and_cleared(record)
    stored = repository.get_assessment(record.id)
    assert stored is not None and stored.status == AssessmentStatus.ABANDONED
    assert repository.list_session_assessments(record.session_id)[0].result is None


def test_an_uncancelled_check_still_completes_and_clears_its_inputs() -> None:
    """The cancel checks do not get in the way of a normal run."""
    repository = AssessmentRepository(":memory:")
    record = make_record(repository)

    run_development_assessment(record, repository, None)

    assert record.status == AssessmentStatus.COMPLETE
    assert record.result is not None
    assert record.title_for_inference == "" and record.images[0].content == b""
