from __future__ import annotations

from threading import RLock
from uuid import UUID, uuid4

from api.models.domain import AssessmentRecord, FeedbackRecord


class InMemoryAssessmentRepository:
    """Development and test repository. It never writes research data."""

    def __init__(self) -> None:
        self._sessions: set[UUID] = set()
        self._assessments: dict[UUID, AssessmentRecord] = {}
        self._feedback: dict[UUID, FeedbackRecord] = {}
        self._lock = RLock()

    def create_session(self) -> UUID:
        session_id = uuid4()
        with self._lock:
            self._sessions.add(session_id)
        return session_id

    def session_exists(self, session_id: UUID) -> bool:
        with self._lock:
            return session_id in self._sessions

    def save_assessment(self, assessment: AssessmentRecord) -> None:
        with self._lock:
            self._assessments[assessment.id] = assessment

    def get_assessment(self, assessment_id: UUID) -> AssessmentRecord | None:
        with self._lock:
            return self._assessments.get(assessment_id)

    def list_session_assessments(self, session_id: UUID) -> list[AssessmentRecord]:
        with self._lock:
            records = [item for item in self._assessments.values() if item.session_id == session_id]
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def save_feedback(self, feedback: FeedbackRecord) -> None:
        with self._lock:
            self._feedback[feedback.assessment_id] = feedback

    def list_all_assessments(self) -> list[AssessmentRecord]:
        with self._lock:
            return sorted(self._assessments.values(), key=lambda item: item.created_at, reverse=True)
