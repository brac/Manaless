"""Per-host minimum-delay rate limiter.

EDHREC asks ~0.80s between requests, Scryfall ~0.12s (CLAUDE.md §4). Construct
one limiter per host with its required delay and call ``wait()`` immediately
before each request; it sleeps only for the time still owed since the last call.

``sleep`` and ``monotonic`` are injectable so the timing behaviour is testable
without real wall-clock delays.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import Lock


class RateLimiter:
    """Enforces at least ``min_delay_seconds`` between successive ``wait()`` calls."""

    def __init__(
        self,
        min_delay_seconds: float,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if min_delay_seconds < 0:
            raise ValueError("min_delay_seconds must be non-negative")
        self._min_delay = min_delay_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_call: float | None = None
        self._lock = Lock()

    def wait(self) -> None:
        """Block until at least ``min_delay_seconds`` have passed since the last call."""
        with self._lock:
            if self._last_call is not None:
                remaining = self._min_delay - (self._monotonic() - self._last_call)
                if remaining > 0:
                    self._sleep(remaining)
            self._last_call = self._monotonic()
