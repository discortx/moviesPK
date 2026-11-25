"""Per-host circuit breaker and per-cinema time budget (plan §10.2, P1-02).

Circuit breaker:
* a **failure** is the final outcome of one ``get`` (after retries) that is a network
  error, a 403, a 429 or a 5xx;
* a **success** (any status below 400) resets the host's count;
* other 4xx (404, 410...) are neutral: they say nothing about the host's health;
* 5 consecutive failures open the circuit for the rest of the run; further calls raise
  :class:`CircuitOpenError` without any network I/O;
* the open circuit means ``blocked`` when at least 3 of the 5 failures were 403/429 (the
  site is refusing us), otherwise ``failed``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from .errors import BudgetExceededError, CircuitOpenError

FAILURE_THRESHOLD = 5
BLOCKING_STATUSES = frozenset({403, 429})
CINEMA_BUDGET_S = 600.0


def is_failure_status(status: int) -> bool:
    return status in BLOCKING_STATUSES or status >= 500


@dataclass
class _HostState:
    streak: list[int | None] = field(default_factory=list)  # statuses; None = network error
    open_as: Literal["failed", "blocked"] | None = None


class CircuitBreaker:
    def __init__(self, threshold: int = FAILURE_THRESHOLD) -> None:
        self._threshold = threshold
        self._hosts: dict[str, _HostState] = {}
        self._lock = threading.Lock()

    def _state(self, host: str) -> _HostState:
        return self._hosts.setdefault(host, _HostState())

    def before_request(self, host: str) -> None:
        """Raise :class:`CircuitOpenError` if ``host``'s circuit is open."""
        with self._lock:
            state = self._state(host)
            if state.open_as is not None:
                raise CircuitOpenError(host, state.open_as)

    def record_success(self, host: str) -> None:
        with self._lock:
            state = self._state(host)
            if state.open_as is None:
                state.streak.clear()

    def record_failure(self, host: str, status: int | None) -> None:
        with self._lock:
            state = self._state(host)
            if state.open_as is not None:
                return
            state.streak.append(status)
            if len(state.streak) >= self._threshold:
                blocking = sum(1 for s in state.streak if s in BLOCKING_STATUSES)
                state.open_as = "blocked" if blocking * 2 > len(state.streak) else "failed"

    def record_status(self, host: str, status: int) -> None:
        """Record a response that was returned to the caller."""
        if status < 400:
            self.record_success(host)
        elif is_failure_status(status):
            self.record_failure(host, status)

    def is_open(self, host: str) -> bool:
        with self._lock:
            return self._state(host).open_as is not None


class CinemaBudget:
    """Wall-clock budget for one cinema's work in one run (10 minutes, then ``failed``)."""

    def __init__(
        self,
        cinema_id: str,
        limit_s: float = CINEMA_BUDGET_S,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cinema_id = cinema_id
        self.limit_s = limit_s
        self._clock = clock
        self._start = clock()

    @property
    def elapsed_s(self) -> float:
        return self._clock() - self._start

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.limit_s - self.elapsed_s)

    def check(self) -> None:
        if self.elapsed_s >= self.limit_s:
            raise BudgetExceededError(
                f"{self.cinema_id}: {self.limit_s:.0f} s budget used up "
                f"({self.elapsed_s:.0f} s elapsed)"
            )
