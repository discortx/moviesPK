"""Movie matching against TMDB (plan §10.4, P1-09).

1. Key = :func:`title_key` of the normalized title.
2. Aliases first, with no TMDB call: manual entries from ``aliases.yml`` (a cinema-specific
   entry beats a global one), then aliases from the database (``auto``/``pending``).
3. Otherwise one ``search/movie`` per unique key per run (``year`` if known, ``region=PK``).
   Candidates are scored with ``rapidfuzz.fuzz.token_set_ratio`` against the title and the
   original title, +5 when the year matches. The best candidate's details are fetched when
   it could match (≥ 70); minus 10 when its runtime differs from the cinema's by more than 15 min.
4. ≥ 90 → ``matched`` (alias ``auto``; details and poster path for the image step).
5. 70-89 → ``provisional`` (alias ``pending``; listed in the digest).
6. < 70 or no result → ``unmatched`` (local movie; listed in the digest).
7. TMDB failure → ``provisional``, nothing cached, retried next run; never a crash.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from rapidfuzz import fuzz
from structlog.typing import FilteringBoundLogger

from ..core.config import AliasConfig
from ..core.logging import get_logger
from ..models.vocab import AliasSource, MatchStatus
from ..services.tmdb import TmdbCandidate, TmdbClient, TmdbError, TmdbMovie
from .normalize import NormalizedMovie, title_key

MATCHED_MIN = 90
PROVISIONAL_MIN = 70
YEAR_BONUS = 5
RUNTIME_PENALTY = 10
RUNTIME_TOLERANCE_MIN = 15
REFRESH_EVERY = timedelta(days=7)


@dataclass(frozen=True)
class Alias:
    """One alias: a normalized title that points at a movie key."""

    key: str  # title_key of the alias
    source: AliasSource
    tmdb_id: int | None = None
    local_key: str | None = None
    cinema_id: str | None = None

    @classmethod
    def from_config(cls, entry: AliasConfig) -> Alias:
        return cls(
            key=title_key(entry.alias),
            source="manual",
            tmdb_id=entry.tmdb_id,
            local_key=entry.local_key,
            cinema_id=entry.cinema_id,
        )


@dataclass(frozen=True)
class MatchResult:
    status: MatchStatus
    key: str
    tmdb_id: int | None = None
    local_key: str | None = None
    score: float | None = None
    details: TmdbMovie | None = None
    #: The alias the upsert step should record (``None`` = leave aliases as they are).
    new_alias_source: AliasSource | None = None
    via_alias: AliasSource | None = None
    tmdb_failed: bool = False

    @property
    def poster_path(self) -> str | None:
        """For the image step only (P1-23); never stored."""
        return self.details.poster_path if self.details else None


class AliasTable:
    """Manual (YAML) aliases first, then database aliases; cinema-specific before global."""

    def __init__(self, manual: Iterable[Alias] = (), stored: Iterable[Alias] = ()) -> None:
        self._entries: dict[tuple[str, str | None], Alias] = {}
        for alias in stored:  # inserted first so manual entries overwrite them
            self._entries[(alias.key, alias.cinema_id)] = alias
        for alias in manual:
            self._entries[(alias.key, alias.cinema_id)] = alias

    def find(self, key: str, cinema_id: str | None) -> Alias | None:
        hits = [self._entries.get((key, cinema_id)), self._entries.get((key, None))]
        manual = [a for a in hits if a is not None and a.source == "manual"]
        if manual:
            return manual[0]
        return next((a for a in hits if a is not None), None)


def score_candidate(movie: NormalizedMovie, candidate: TmdbCandidate) -> float:
    titles = [candidate.title] + ([candidate.original_title] if candidate.original_title else [])
    base = max(fuzz.token_set_ratio(movie.title_key, title_key(t)) for t in titles)
    if movie.year and candidate.year == movie.year:
        base += YEAR_BONUS
    return min(base, 100.0)


def needs_refresh(refreshed_at: datetime | None, now: datetime) -> bool:
    """Matched, now-showing movies are refreshed from TMDB at least every 7 days."""
    return refreshed_at is None or now - refreshed_at >= REFRESH_EVERY


@dataclass
class Matcher:
    """One per run. Thread-safe; at most one TMDB search per unique title key per run."""

    tmdb: TmdbClient | None
    aliases: AliasTable = field(default_factory=AliasTable)
    log: FilteringBoundLogger = field(default_factory=get_logger)
    _cache: dict[str, MatchResult] = field(default_factory=dict)
    _locks: dict[str, threading.Lock] = field(default_factory=dict)
    _guard: threading.Lock = field(default_factory=threading.Lock)

    def match(self, movie: NormalizedMovie, cinema_id: str | None = None) -> MatchResult:
        key = movie.title_key
        alias = self.aliases.find(key, cinema_id)
        if alias is not None:
            return self._from_alias(key, alias, movie)
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            result = self._search(movie)
            if not result.tmdb_failed:  # failures are retried next run, not cached
                self._cache[key] = result
            return result

    def _from_alias(self, key: str, alias: Alias, movie: NormalizedMovie) -> MatchResult:
        if alias.tmdb_id is not None:
            status: MatchStatus = "provisional" if alias.source == "pending" else "matched"
            return MatchResult(status, key, tmdb_id=alias.tmdb_id, via_alias=alias.source)
        return MatchResult(
            "unmatched", key, local_key=alias.local_key or movie.local_key, via_alias=alias.source
        )

    def _search(self, movie: NormalizedMovie) -> MatchResult:
        key = movie.title_key
        if self.tmdb is None:
            return MatchResult("unmatched", key, local_key=movie.local_key)
        try:
            candidates = self.tmdb.search_movie(movie.title, year=movie.year)
            if not candidates:
                return MatchResult("unmatched", key, local_key=movie.local_key, score=0.0)
            best = max(candidates, key=lambda c: score_candidate(movie, c))
            score = score_candidate(movie, best)
            details = None
            if score >= PROVISIONAL_MIN:
                details = self.tmdb.movie_details(best.tmdb_id)
                if (
                    movie.runtime_min
                    and details.runtime_min
                    and abs(movie.runtime_min - details.runtime_min) > RUNTIME_TOLERANCE_MIN
                ):
                    score -= RUNTIME_PENALTY
        except TmdbError as exc:
            self.log.warning("match.tmdb_failed", title=movie.title, error=str(exc))
            return MatchResult("provisional", key, local_key=movie.local_key, tmdb_failed=True)

        if score >= MATCHED_MIN:
            return MatchResult(
                "matched",
                key,
                tmdb_id=best.tmdb_id,
                score=score,
                details=details,
                new_alias_source="auto",
            )
        if score >= PROVISIONAL_MIN:
            return MatchResult(
                "provisional",
                key,
                tmdb_id=best.tmdb_id,
                local_key=movie.local_key,
                score=score,
                details=details,
                new_alias_source="pending",
            )
        return MatchResult("unmatched", key, local_key=movie.local_key, score=score)
