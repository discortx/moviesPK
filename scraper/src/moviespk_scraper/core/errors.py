"""Typed errors (plan §10.2, P1-01/P1-02).

Every error maps to the run status it causes through :func:`run_status_for`:

==========================  ===========  =============================================
Error                       Run status   Meaning
==========================  ===========  =============================================
RobotsDisallowedError       ``blocked``  robots.txt forbids a needed path
RobotsUnavailableError      ``blocked``  robots.txt 5xx / unreachable (RFC 9309)
BlockedError                ``blocked``  the site refuses us (403/429 pattern)
CircuitOpenError            either       5 consecutive failures for a host
SchemaDriftError            ``drift``    the page/JSON no longer has the expected shape
ParseError                  ``failed``   one value could not be parsed
BudgetExceededError         ``failed``   the 10-minute per-cinema budget ran out
HttpError and subclasses    ``failed``   network / server failure after retries
anything else               ``failed``
==========================  ===========  =============================================
"""

from __future__ import annotations

from typing import Literal

from .robots import RobotsDisallowedError

__all__ = [
    "BlockedError",
    "BudgetExceededError",
    "CircuitOpenError",
    "FailureRunStatus",
    "HttpError",
    "ParseError",
    "RateLimitedError",
    "RetryableStatusError",
    "RobotsDisallowedError",
    "RobotsUnavailableError",
    "SchemaDriftError",
    "TooManyRedirectsError",
    "run_status_for",
]

#: Run statuses an error can cause (the ``ok``/``partial`` statuses never come from errors).
FailureRunStatus = Literal["failed", "blocked", "drift"]


# --- HTTP layer ------------------------------------------------------------------------


class HttpError(Exception):
    """Base class for request failures after the client's own handling."""

    def __init__(self, message: str, *, url_path: str, status: int | None = None) -> None:
        super().__init__(message)
        self.url_path = url_path
        self.status = status


class RetryableStatusError(HttpError):
    """502/503/504: retried; raised when the attempts are used up."""


class RateLimitedError(HttpError):
    """429. ``retry_after_s`` is the server's ``Retry-After`` in seconds, if any."""

    def __init__(self, *, url_path: str, retry_after_s: float | None) -> None:
        super().__init__(f"429 rate limited on {url_path}", url_path=url_path, status=429)
        self.retry_after_s = retry_after_s


class TooManyRedirectsError(HttpError):
    """More than the allowed number of redirects."""


class RobotsUnavailableError(RobotsDisallowedError):
    """robots.txt answered 5xx or could not be fetched: everything is disallowed for this
    run and the run status is ``blocked`` (RFC 9309, plan §10.2)."""


class BlockedError(Exception):
    """The site is refusing us (for example repeated 403/429). Never routed around: no
    proxy, VPS, IP rotation or browser spoofing (plan §10.2, R3/D17)."""


class CircuitOpenError(Exception):
    """The host's circuit is open for the rest of the run; no request was made.

    ``run_status`` is ``blocked`` when the failures that opened it were mostly 403/429,
    otherwise ``failed``.
    """

    def __init__(self, host: str, run_status: Literal["failed", "blocked"]) -> None:
        super().__init__(f"circuit open for {host} ({run_status})")
        self.host = host
        self.run_status: Literal["failed", "blocked"] = run_status


# --- pipeline ------------------------------------------------------------------------


class SchemaDriftError(Exception):
    """The source no longer has the expected structure. Run ``drift``: no reconcile, an
    issue is opened, the last good data stays (plan §2.3)."""


class ParseError(Exception):
    """A single value (date, time, title...) could not be parsed."""


class BudgetExceededError(Exception):
    """The per-cinema time budget (10 minutes) ran out. Run ``failed``."""


def run_status_for(exc: BaseException) -> FailureRunStatus:
    """The run status a failed cinema gets for ``exc``."""
    if isinstance(exc, CircuitOpenError):
        return exc.run_status
    if isinstance(exc, RobotsDisallowedError | BlockedError):
        return "blocked"
    if isinstance(exc, SchemaDriftError):
        return "drift"
    return "failed"
