from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import UUID

from api.errors import AppError


class SessionRateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self._limit = requests_per_minute
        self._events: dict[UUID, deque[datetime]] = defaultdict(deque)
        self._lock = RLock()

    def check(self, session_id: UUID) -> None:
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=1)
        with self._lock:
            events = self._events[session_id]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= self._limit:
                raise AppError(
                    429,
                    "rate_limit_exceeded",
                    "Too many checks were submitted. Try again shortly.",
                )
            events.append(now)
