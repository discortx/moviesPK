"""Typed errors raised by the HTTP layer (plan §10.2).

P1-02 adds the pipeline errors (``SchemaDriftError``, ``BlockedError``, ``ParseError``,
``BudgetExceededError``) and the circuit breaker on top of these.
"""

from __future__ import annotations

from .robots import RobotsDisallowedError

__all__ = [
    "HttpError",
    "RateLimitedError",
    "RetryableStatusError",
    "RobotsDisallowedError",
    "RobotsUnavailableError",
    "TooManyRedirectsError",
]


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
