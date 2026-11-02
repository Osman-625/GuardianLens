# A rolling-minute rate limit on starting checks. One limiter counts per session, another per
# network address: a session costs nothing to create, so a limit on sessions alone stops nobody.
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import RLock

from api.errors import AppError

_WINDOW_SECONDS = 60.0


class RateLimiter:
    """Allows each key (a session id or a network address) a fixed number of requests a minute."""

    def __init__(self, requests_per_minute: int) -> None:
        """Sets the limit; each key's recent request times are kept in memory."""
        self._limit = requests_per_minute
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)
        self._last_sweep = time.monotonic()
        self._lock = RLock()

    def check(self, key: str) -> None:
        """Records a request for the key, or raises a 429 when it is over the limit."""
        now = time.monotonic()
        cutoff = now - _WINDOW_SECONDS
        with self._lock:
            if now - self._last_sweep >= _WINDOW_SECONDS:
                # Once a minute, forget every key that has been quiet for a whole window, so the
                # table does not grow with every session and address ever seen.
                self._last_sweep = now
                for name, seen in list(self._events.items()):
                    if not seen or seen[-1] < cutoff:
                        del self._events[name]
            events = self._events[key]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= self._limit:
                raise AppError(
                    429,
                    "rate_limit_exceeded",
                    "Too many checks were submitted. Try again shortly.",
                )
            events.append(now)
