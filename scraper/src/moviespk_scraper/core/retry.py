"""Retry policy (plan §10.2).

* 3 attempts in total on timeouts, connection errors and 502/503/504;
* exponential backoff 2 s, 4 s, (8 s) plus 0-1 s of jitter;
* a 429 waits for ``Retry-After`` (seconds or HTTP date) when it is at most 120 s; a longer
  or missing ``Retry-After`` falls back to the backoff, and a ``Retry-After`` above 120 s
  counts as a failure at once;
* no retry on any other 4xx.
"""

from __future__ import annotations

import email.utils
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
)

from .errors import RateLimitedError, RetryableStatusError

ATTEMPTS = 3
BACKOFF_BASE_S = 2.0
JITTER_MAX_S = 1.0
RETRY_AFTER_MAX_S = 120.0
RETRYABLE_STATUSES = frozenset({502, 503, 504})


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Seconds to wait from a ``Retry-After`` header, or ``None`` if absent or invalid."""
    if value is None:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, RateLimitedError):
        return exc.retry_after_s is None or exc.retry_after_s <= RETRY_AFTER_MAX_S
    return isinstance(exc, RetryableStatusError | httpx.TimeoutException | httpx.TransportError)


def make_wait(rng: random.Random) -> Callable[[RetryCallState], float]:
    def wait(state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        if isinstance(exc, RateLimitedError) and exc.retry_after_s is not None:
            return exc.retry_after_s
        backoff = BACKOFF_BASE_S * float(2 ** (state.attempt_number - 1))
        return backoff + rng.uniform(0, JITTER_MAX_S)

    return wait


def retrying(
    *, sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None
) -> Retrying:
    return Retrying(
        stop=stop_after_attempt(ATTEMPTS),
        wait=make_wait(rng or random.Random()),  # noqa: S311 (jitter, not security)
        retry=retry_if_exception(is_retryable),
        sleep=sleep,
        reraise=True,
    )
