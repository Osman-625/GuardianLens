from __future__ import annotations

from typing import Never
from uuid import UUID

from api.models.domain import AssessmentRecord, FeedbackRecord


class SupabaseAssessmentRepository:
    """Production adapter boundary.

    The SQL schema is complete in db/migrations. This adapter intentionally refuses
    to run until proposal P-2 and the final Supabase project are confirmed. Keeping
    the boundary explicit prevents the first draft from silently falling back to a
    fake database in a production-like environment.
    """

    def _pending(self) -> Never:
        raise RuntimeError(
            "Supabase adapter is not wired in this first draft. Apply the supplied migrations, "
            "confirm topology P-2, then implement this adapter before disabling stub mode."
        )

    def create_session(self) -> UUID:
        return self._pending()

    def session_exists(self, session_id: UUID) -> bool:
        return self._pending()

    def save_assessment(self, assessment: AssessmentRecord) -> None:
        self._pending()

    def get_assessment(self, assessment_id: UUID) -> AssessmentRecord | None:
        return self._pending()

    def list_session_assessments(self, session_id: UUID) -> list[AssessmentRecord]:
        return self._pending()

    def save_feedback(self, feedback: FeedbackRecord) -> None:
        self._pending()

    def list_all_assessments(self) -> list[AssessmentRecord]:
        return self._pending()
