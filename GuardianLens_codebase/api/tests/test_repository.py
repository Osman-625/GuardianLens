# Repository tests: the SQLite store keeps what the app needs after scoring, nothing the buyer typed
# or uploaded, survives a restart, and never lets a late result undo a cancel.
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from api.models.domain import AssessmentRecord, FeedbackRecord, ImageInput, SellerInput
from api.repositories.assessments import AssessmentRepository
from api.schemas import AssessmentStatus, FeedbackVerdict, PipelineStage
from api.services.orchestrator import run_development_assessment


def new_record(repository: AssessmentRepository) -> AssessmentRecord:
    """A still-processing assessment, with raw wording and a photo, saved in the repository."""
    record = AssessmentRecord(
        session_id=repository.create_session(),
        platform="carousell",
        title_scrubbed="Used laptop",
        title_for_inference="Used laptop my number is 0123",
        description_for_inference="Good condition.",
        category="Laptops",
        price=1250.5,
        language_detected="en",
        seller=SellerInput(account_age_days=400, rating=4.8, review_count=21),
        images=[ImageInput("a.jpg", "image/jpeg", b"photo-bytes", "0" * 64, 640, 480)],
        source="extension",
        capture_meta={"adapter_version": "1"},
    )
    repository.save_assessment(record)
    return record


def test_a_stored_assessment_comes_back_without_the_raw_wording_or_photos() -> None:
    """What the app reads again is kept; the buyer's own wording and the photo bytes are not."""
    repository = AssessmentRepository(":memory:")
    record = new_record(repository)

    found = repository.get_assessment(record.id)

    assert found is not None
    assert (found.session_id, found.title_scrubbed) == (record.session_id, "Used laptop")
    assert (found.category, found.price) == ("Laptops", 1250.5)
    assert found.seller == SellerInput(account_age_days=400, rating=4.8, review_count=21)
    assert (found.source, found.capture_meta) == ("extension", {"adapter_version": "1"})
    assert found.title_for_inference == found.description_for_inference == ""
    assert found.images == []


def test_a_finished_result_round_trips_and_history_is_newest_first_per_session() -> None:
    """A completed check keeps its result, and a session lists only its own checks."""
    repository = AssessmentRepository(":memory:")
    first = new_record(repository)
    run_development_assessment(first, repository, None)
    later = replace(first, id=uuid4(), created_at=first.created_at.replace(year=2099))
    repository.save_assessment(later)
    other = new_record(repository)

    listed = repository.list_session_assessments(first.session_id)

    assert [item.id for item in listed] == [later.id, first.id]
    assert listed[1].result is not None and listed[1].result == first.result
    assert other.id not in {item.id for item in listed}


def test_data_survives_a_restart_and_an_unfinished_check_is_closed_as_failed(
    tmp_path: Path,
) -> None:
    """A check running when the server stopped cannot resume (its inputs were never stored)."""
    path = tmp_path / "data" / "guardianlens.sqlite3"
    repository = AssessmentRepository(path)
    running = new_record(repository)
    done = new_record(repository)
    run_development_assessment(done, repository, None)
    repository.close()

    reopened = AssessmentRepository(path)

    assert reopened.session_exists(running.session_id)
    interrupted = reopened.get_assessment(running.id)
    assert interrupted is not None
    assert interrupted.status == AssessmentStatus.FAILED
    assert interrupted.error_code == "interrupted"
    kept = reopened.get_assessment(done.id)
    assert kept is not None and kept.status == AssessmentStatus.COMPLETE and kept.result is not None


def test_a_late_result_cannot_undo_a_cancel() -> None:
    """Once a check is abandoned, nothing the scoring task saves afterwards changes it."""
    repository = AssessmentRepository(":memory:")
    record = new_record(repository)
    cancelled = repository.get_assessment(record.id)
    assert cancelled is not None
    cancelled.status, cancelled.stage = AssessmentStatus.ABANDONED, None
    repository.save_assessment(cancelled)

    record.status, record.stage = AssessmentStatus.PROCESSING, PipelineStage.FUSION
    repository.save_assessment(record)

    stored = repository.get_assessment(record.id)
    assert stored is not None and stored.status == AssessmentStatus.ABANDONED


def test_unknown_sessions_do_not_exist_and_later_feedback_replaces_earlier_feedback() -> None:
    """Feedback is kept once per assessment, the latest verdict winning."""
    repository = AssessmentRepository(":memory:")
    record = new_record(repository)
    assert repository.session_exists(record.session_id)
    assert not repository.session_exists(record.id)

    repository.save_feedback(FeedbackRecord(record.id, FeedbackVerdict.HELPFUL, None))
    repository.save_feedback(FeedbackRecord(record.id, FeedbackVerdict.UNCLEAR, "too vague"))

    rows = repository._db.execute("SELECT verdict, comment_scrubbed FROM feedback").fetchall()
    assert [(row["verdict"], row["comment_scrubbed"]) for row in rows] == [("unclear", "too vague")]
