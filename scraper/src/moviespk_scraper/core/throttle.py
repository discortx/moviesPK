"""Per-host politeness (plan §10.2).

* at least ``min_delay_ms`` plus 0-500 ms of jitter between requests to the same host;
* at most one request in flight per host (``max_concurrency: 1``).

Thread-safe: the scraper runs at most 3 cinemas in parallel (threads), and two cinemas of
the same chain share a host, so they must share its slot.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

JITTER_MAX_MS = 500


class HostThrottle:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 (jitter, not security)
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}

    def _lock_for(self, host: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(host, threading.Lock())

    @contextmanager
    def slot(self, host: str, delay_ms: int) -> Iterator[None]:
        """Hold the host's single slot; wait until ``delay_ms`` + jitter has passed since
        the previous request to that host finished being sent."""
        with self._lock_for(host):
            last = self._last.get(host)
            if last is not None:
                gap_s = (delay_ms + self._rng.uniform(0, JITTER_MAX_MS)) / 1000
                remaining = last + gap_s - self._clock()
                if remaining > 0:
                    self._sleep(remaining)
            try:
                yield
            finally:
                self._last[host] = self._clock()
