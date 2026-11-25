"""Validator and sanitizer (plan §10.3 step 3, P1-08).

Sanitize first, then validate:

* **Sanitize** (never rejects): HTML is stripped from every text field (tags removed,
  entities decoded, whitespace collapsed); titles are capped at 200 characters and
  synopses at 2,000 (cut at a word boundary, ending in "…"); halls at 60. A runtime
  outside 30-300 minutes is dropped from the movie (a listing typo should not drop the
  movie and all its shows), and so is a negative seat count.
* **Validate** each showtime with Pydantic: a title, ``startsAt`` aware and within
  ``now - 2 h .. now + 14 d``, ``endsAt > startsAt`` when present, known format and language,
  an http(s) booking URL. Failing rows are dropped and counted by reason.
* **Threshold:** when more than ``max_invalid_rate`` (default 20%) of the showtimes are
  invalid, the cinema run is ``failed`` (nothing of it is written).
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)
from selectolax.lexbor import LexborHTMLParser
from structlog.typing import FilteringBoundLogger

from ..models.vocab import Format, Language
from .normalize import NormalizedMovie, NormalizedShowtime
from .text import normalize_text

MAX_INVALID_RATE = 0.20
PAST_WINDOW = timedelta(hours=2)
FUTURE_WINDOW = timedelta(days=14)
TITLE_MAX = 200
SYNOPSIS_MAX = 2000
HALL_MAX = 60
RUNTIME_RANGE = (30, 300)
ELLIPSIS = "…"


# --- sanitizing ------------------------------------------------------------------------


def strip_html(value: str | None) -> str:
    """Plain text of ``value``: tags removed, entities decoded, whitespace collapsed."""
    if not value:
        return ""
    if "<" not in value and "&" not in value:
        return normalize_text(value)
    tree = LexborHTMLParser(f"<body>{value}</body>")
    for node in tree.css("script, style, template, noscript"):
        node.decompose()
    body = tree.body
    return normalize_text(body.text(separator=" ") if body is not None else "")


def cap(value: str, limit: int) -> str:
    """At most ``limit`` characters, cut at a word boundary, ending in an ellipsis."""
    if len(value) <= limit:
        return value
    cut = value[: limit - 1]
    if " " in cut[limit // 2 :]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:-") + ELLIPSIS


def _clean(value: str | None, limit: int) -> str | None:
    text = strip_html(value)
    return cap(text, limit) if text else None


def sanitize_movie(movie: NormalizedMovie) -> tuple[NormalizedMovie, list[str]]:
    fixes: list[str] = []
    runtime = movie.runtime_min
    if runtime is not None and not RUNTIME_RANGE[0] <= runtime <= RUNTIME_RANGE[1]:
        fixes.append("runtime out of range")
        runtime = None
    title = _clean(movie.title, TITLE_MAX) or movie.title_key
    return (
        dataclasses.replace(
            movie,
            title=title,
            original_title=_clean(movie.original_title, TITLE_MAX),
            synopsis=_clean(movie.synopsis, SYNOPSIS_MAX),
            runtime_min=runtime,
        ),
        fixes,
    )


def sanitize_showtime(show: NormalizedShowtime) -> NormalizedShowtime:
    seats = show.seats_available
    total = show.seats_total
    return dataclasses.replace(
        show,
        movie_title=_clean(show.movie_title, TITLE_MAX) or "",
        hall=cap(strip_html(show.hall), HALL_MAX),
        seats_available=seats if seats is None or seats >= 0 else None,
        seats_total=total if total is None or total > 0 else None,
    )


# --- validation ----------------------------------------------------------------------


def _http_url(value: str | None) -> str | None:
    if value is not None and not value.startswith(("https://", "http://")):
        raise ValueError("booking URL must be http(s)")
    return value


class ShowtimeRow(BaseModel):
    """What a showtime must satisfy to be written."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    movie_title: Annotated[str, StringConstraints(min_length=1, max_length=TITLE_MAX)]
    title_key: Annotated[str, StringConstraints(min_length=1)]
    starts_at: AwareDatetime
    ends_at: AwareDatetime | None = None
    hall: Annotated[str, StringConstraints(max_length=HALL_MAX)]
    format: Format
    language: Language
    booking_url: Annotated[str | None, AfterValidator(_http_url)] = Field(
        default=None, max_length=2048
    )
    seats_available: Annotated[int, Field(ge=0)] | None = None
    seats_total: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _times(self) -> ShowtimeRow:
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("endsAt must be after startsAt")
        return self


@dataclass
class ValidationResult:
    movies: list[NormalizedMovie]
    showtimes: list[NormalizedShowtime]
    total: int
    invalid: int
    reasons: Counter[str] = field(default_factory=Counter)
    fixes: Counter[str] = field(default_factory=Counter)
    max_invalid_rate: float = MAX_INVALID_RATE

    @property
    def invalid_rate(self) -> float:
        return self.invalid / self.total if self.total else 0.0

    @property
    def failed(self) -> bool:
        """More than ``max_invalid_rate`` of the rows are invalid (plan: above 20%)."""
        return self.invalid_rate > self.max_invalid_rate


def _reason(exc: ValidationError) -> str:
    first = exc.errors()[0]
    loc = ".".join(str(p) for p in first["loc"]) or "row"
    return f"{loc}: {first['type']}"


def validate(
    movies: Sequence[NormalizedMovie],
    showtimes: Sequence[NormalizedShowtime],
    *,
    now: datetime,
    max_invalid_rate: float = MAX_INVALID_RATE,
    log: FilteringBoundLogger | None = None,
) -> ValidationResult:
    """Sanitize every row, keep the valid showtimes and count the rest."""
    if now.tzinfo is None:
        raise ValueError("now must be aware")
    earliest, latest = now - PAST_WINDOW, now + FUTURE_WINDOW
    fixes: Counter[str] = Counter()
    clean_movies = []
    for movie in movies:
        cleaned, movie_fixes = sanitize_movie(movie)
        fixes.update(movie_fixes)
        clean_movies.append(cleaned)

    valid: list[NormalizedShowtime] = []
    reasons: Counter[str] = Counter()
    for show in showtimes:
        cleaned_show = sanitize_showtime(show)
        try:
            row = ShowtimeRow.model_validate(dataclasses.asdict(cleaned_show))
        except ValidationError as exc:
            reasons[_reason(exc)] += 1
            continue
        if not earliest <= row.starts_at <= latest:
            reasons["starts_at: outside now-2h..now+14d"] += 1
            continue
        valid.append(cleaned_show)

    result = ValidationResult(
        movies=clean_movies,
        showtimes=valid,
        total=len(showtimes),
        invalid=len(showtimes) - len(valid),
        reasons=reasons,
        fixes=fixes,
        max_invalid_rate=max_invalid_rate,
    )
    if log is not None and (result.invalid or fixes):
        log.info(
            "validate.summary",
            phase="validate",
            total=result.total,
            invalid=result.invalid,
            invalidRate=round(result.invalid_rate, 3),
            reasons=dict(reasons),
            fixes=dict(fixes),
        )
    return result
