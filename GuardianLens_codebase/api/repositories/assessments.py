# Where sessions, assessments, and feedback are kept: one SQLite file (":memory:" in tests). It is
# the standard library's sqlite3, so there is no server, no account, and no credential to manage,
# and the file can be read with any SQLite tool for the research analysis.
#
# Only what the app needs after scoring is stored. The buyer's own wording, the description and the
# photo bytes are never written: they live in the running check and are cleared when it ends, so a
# stored record comes back with empty raw fields.
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from api.models.domain import AssessmentRecord, FeedbackRecord, SellerInput
from api.schemas import AssessmentResultResponse, AssessmentStatus, PipelineStage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assessments (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (id),
    platform TEXT NOT NULL,
    title_scrubbed TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL NOT NULL,
    language_detected TEXT NOT NULL,
    seller TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    result TEXT,
    error_code TEXT,
    error_message TEXT,
    source TEXT NOT NULL,
    capture_meta TEXT
);
CREATE INDEX IF NOT EXISTS assessments_by_session ON assessments (session_id, created_at);
CREATE TABLE IF NOT EXISTS feedback (
    assessment_id TEXT PRIMARY KEY REFERENCES assessments (id),
    verdict TEXT NOT NULL,
    comment_scrubbed TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
"""

# A check cannot resume after a restart (its photos and wording were never stored), so one that was
# still running when the server stopped is closed as failed instead of staying "processing" forever.
# shortcut: this assumes one server process (like the in-process rate limiter). With several
# workers, one starting would fail the others' running checks; track the owner process then.
_INTERRUPTED = (
    "UPDATE assessments SET status = 'failed', stage = NULL, error_code = 'interrupted', "
    "error_message = 'This check was interrupted when the server restarted. Try again.' "
    "WHERE status = 'processing'"
)

# Progress fields are the only ones that change after a check starts. A cancelled (abandoned) check
# is never overwritten, so a result that finishes just after the buyer pressed Cancel cannot undo
# it.
_SAVE_ASSESSMENT = """
INSERT INTO assessments (
    id, session_id, platform, title_scrubbed, category, price,
    language_detected, seller, status, stage, created_at, completed_at, result, error_code,
    error_message, source, capture_meta
) VALUES (
    :id, :session_id, :platform, :title_scrubbed, :category, :price,
    :language_detected, :seller, :status, :stage, :created_at, :completed_at, :result, :error_code,
    :error_message, :source, :capture_meta
)
ON CONFLICT (id) DO UPDATE SET
    status = excluded.status, stage = excluded.stage, completed_at = excluded.completed_at,
    result = excluded.result, error_code = excluded.error_code,
    error_message = excluded.error_message
WHERE assessments.status != 'abandoned'
"""


def _iso(value: datetime | None) -> str | None:
    """A time as text for the database, or None."""
    return value.isoformat() if value else None


def _record(row: sqlite3.Row) -> AssessmentRecord:
    """Builds an assessment from its row; the raw wording and photos were never stored, so empty."""
    return AssessmentRecord(
        id=UUID(row["id"]),
        session_id=UUID(row["session_id"]),
        platform=row["platform"],
        title_scrubbed=row["title_scrubbed"],
        title_for_inference="",
        description_for_inference="",
        category=row["category"],
        price=row["price"],
        language_detected=row["language_detected"],
        seller=SellerInput(**json.loads(row["seller"])),
        images=[],
        status=AssessmentStatus(row["status"]),
        stage=PipelineStage(row["stage"]) if row["stage"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        result=AssessmentResultResponse.model_validate_json(row["result"])
        if row["result"]
        else None,
        error_code=row["error_code"],
        error_message=row["error_message"],
        source=row["source"],
        capture_meta=json.loads(row["capture_meta"]) if row["capture_meta"] else None,
    )


class AssessmentRepository:
    """The app's one store. One connection is shared by the request threads and by the background
    task that scores an assessment, so a lock serialises its use."""

    def __init__(self, path: Path | str) -> None:
        """Opens (and creates, if needed) the database, then closes any check left running."""
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.executescript(_SCHEMA)
            self._db.execute(_INTERRUPTED)

    def close(self) -> None:
        """Closes the database."""
        with self._lock:
            self._db.close()

    def create_session(self) -> UUID:
        """Creates an anonymous session and returns its id."""
        session_id = uuid4()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                (str(session_id), datetime.now(UTC).isoformat()),
            )
        return session_id

    def session_exists(self, session_id: UUID) -> bool:
        """Tells whether a session id was issued by this repository."""
        with self._lock:
            found = self._db.execute("SELECT 1 FROM sessions WHERE id = ?", (str(session_id),))
            return found.fetchone() is not None

    def save_assessment(self, assessment: AssessmentRecord) -> None:
        """Stores a new assessment, or updates the progress of the stored one with the same id."""
        row = {
            "id": str(assessment.id),
            "session_id": str(assessment.session_id),
            "platform": assessment.platform,
            "title_scrubbed": assessment.title_scrubbed,
            "category": assessment.category,
            "price": assessment.price,
            "language_detected": assessment.language_detected,
            "seller": json.dumps(asdict(assessment.seller)),
            "status": assessment.status.value,
            "stage": assessment.stage.value if assessment.stage else None,
            "created_at": assessment.created_at.isoformat(),
            "completed_at": _iso(assessment.completed_at),
            "result": assessment.result.model_dump_json() if assessment.result else None,
            "error_code": assessment.error_code,
            "error_message": assessment.error_message,
            "source": assessment.source,
            "capture_meta": json.dumps(assessment.capture_meta)
            if assessment.capture_meta
            else None,
        }
        with self._lock, self._db:
            self._db.execute(_SAVE_ASSESSMENT, row)

    def get_assessment(self, assessment_id: UUID) -> AssessmentRecord | None:
        """Returns one assessment by id, or None when there is none."""
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM assessments WHERE id = ?", (str(assessment_id),)
            ).fetchone()
        return _record(row) if row else None

    def list_session_assessments(self, session_id: UUID) -> list[AssessmentRecord]:
        """Returns one session's assessments, newest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM assessments WHERE session_id = ? ORDER BY created_at DESC",
                (str(session_id),),
            ).fetchall()
        return [_record(row) for row in rows]

    def save_feedback(self, feedback: FeedbackRecord) -> None:
        """Stores feedback for an assessment, replacing any earlier feedback for it."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO feedback "
                "(assessment_id, verdict, comment_scrubbed, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(feedback.assessment_id),
                    feedback.verdict.value,
                    feedback.comment_scrubbed,
                    feedback.created_at.isoformat(),
                    _iso(feedback.updated_at),
                ),
            )
