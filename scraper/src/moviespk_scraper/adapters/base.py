"""Adapter contract (plan §10.1).

Adapters only **parse**. Every fetch goes through :meth:`RunContext.fetch`, which applies
the cinema's robots policy, delay and time budget through the shared HTTP client (robots
checks, throttling, retries, circuit breaker, logging). Chains share one adapter,
parameterized by ``cinema.branch``.
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

import httpx
from structlog.typing import FilteringBoundLogger

from ..core.circuit_breaker import CinemaBudget
from ..core.http import ScraperHttpClient
from ..core.redact import clean_body
from ..models.vocab import Job

if TYPE_CHECKING:
    from ..core.config import CinemaConfig

FetchMode = Literal["json", "html", "browser"]

#: Plan §10.3 step 1: at most 2 MB of debug payload per cinema.
DEBUG_MAX_BYTES = 2 * 1024 * 1024
BOOKING_PLACEHOLDERS = frozenset({"branch", "sessionId", "filmId"})


def build_booking_url(template: str | None, **values: str | None) -> str | None:
    """Fill ``cinema.booking_url_template`` (placeholders ``{branch}``, ``{sessionId}``,
    ``{filmId}``). Returns ``None`` without a template or when a used value is missing."""
    if not template:
        return None
    used = {name for _, name, _, _ in string.Formatter().parse(template) if name}
    unknown = used - BOOKING_PLACEHOLDERS
    if unknown:
        raise ValueError(f"unknown booking_url_template placeholders: {sorted(unknown)}")
    if any(not values.get(name) for name in used):
        return None
    return template.format(**{name: values[name] for name in used})


@dataclass(frozen=True)
class RawMovie:
    """A movie as the cinema lists it, before normalization and TMDB matching."""

    title: str
    local_key: str | None = None  # the cinema's own film id, if any
    original_title: str | None = None
    runtime_min: int | None = None
    genres: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    synopsis: str | None = None
    release_date: date | None = None
    rating: str | None = None  # e.g. "PG-13" as published


@dataclass(frozen=True)
class RawShowtime:
    """One show as the cinema lists it. ``starts_at`` may be naive (cinema-local, PKT) or
    aware; the normalizer converts it to UTC (plan §10.3 step 2)."""

    movie_title: str
    starts_at: datetime
    movie_local_key: str | None = None
    hall: str | None = None
    format_text: str | None = None  # "2D", "3D", "IMAX"... as published
    language_text: str | None = None
    booking_url: str | None = None
    external_id: str | None = None  # the cinema's session id
    seats_available: int | None = None  # only when published with the listing
    seats_total: int | None = None


@dataclass(frozen=True)
class ShowRef:
    """What ``fetch_seat_status`` needs to find one show again."""

    showtime_id: str
    external_id: str | None = None
    booking_url: str | None = None


@dataclass(frozen=True)
class RawSeats:
    available: int | None = None
    total: int | None = None
    category: str | None = None  # a cinema-published label such as "Filling fast"


@dataclass
class RunContext:
    """Per-cinema context for one run."""

    http: ScraperHttpClient
    job: Job
    now: datetime  # aware UTC; the run's reference time
    log: FilteringBoundLogger
    budget: CinemaBudget
    #: Where raw payloads go when parsing fails (an Actions artifact); ``None`` = off.
    debug_dir: Path | None = None
    extra: dict[str, object] = field(default_factory=dict)
    _debug_bytes: int = 0

    def fetch(self, cinema: CinemaConfig, url: str) -> httpx.Response:
        """GET ``url`` for ``cinema`` under its robots policy, delay and budget."""
        return self.http.get(
            url,
            min_delay_ms=cinema.min_delay_ms,
            robots_policy=cinema.robots_policy,
            permission_ref=cinema.permission_ref,
            budget=self.budget,
        )

    def save_debug(self, cinema: CinemaConfig, name: str, resp: httpx.Response) -> Path | None:
        """Keep a fetched payload for diagnosis after a parse failure (plan §10.3 step 1):
        cookies and tokens stripped, at most 2 MB per cinema. Only responses that were
        fetched (so robots-allowed) can be passed in."""
        if self.debug_dir is None:
            return None
        body, ext = clean_body(resp.headers.get("content-type", ""), resp.content)
        if self._debug_bytes + len(body) > DEBUG_MAX_BYTES:
            self.log.warning("debug.skipped", reason="2 MB cap", bytes=len(body))
            return None
        out = self.debug_dir / cinema.id
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{name}{ext}"
        path.write_bytes(body)
        self._debug_bytes += len(body)
        self.log.info("debug.saved", file=str(path), bytes=len(body))
        return path


@runtime_checkable
class CinemaAdapter(Protocol):
    adapter_id: str
    fetch_mode: FetchMode

    def list_showtimes(
        self, ctx: RunContext, cinema: CinemaConfig, days: int = 7
    ) -> list[RawShowtime]: ...

    def list_movies(self, ctx: RunContext, cinema: CinemaConfig) -> list[RawMovie]:
        """May return ``[]`` when movie info comes with the showtimes."""
        ...

    def fetch_seat_status(
        self, ctx: RunContext, cinema: CinemaConfig, show: ShowRef
    ) -> RawSeats | None:
        """Called only when ``cinema.seats_allowed``."""
        ...
