"""Upsert movies, showtimes and aliases for one cinema (plan §8.1, §8.4, §10.3 step 5).

Movies
* Identity: a ``matched`` movie by ``tmdbId``, anything else by ``localKey`` (slug of the
  normalized title + year). A local movie that later matches is upgraded in place (gains
  ``tmdbId``, keeps its ``_id``, ``slug`` and ``localKey``).
* ``_id``, ``slug``, ``localKey``, ``poster: null`` and ``createdAt`` are written on insert
  only, so URLs never change. Fields come from TMDB details when the match fetched them,
  otherwise from the cinema listing; a matched movie without fresh details keeps its
  TMDB-derived fields.

Showtimes
* ``_id`` = ``pipeline.ids.showtime_id`` (cinemaId | movieKey | startsAt | hall | format),
  where movieKey = tmdbId or localKey, so ids survive a movie being re-created.
* ``$set`` (never replace), so data from other jobs (seats) is kept; ``hall`` is removed
  when its canonical value is ``""``; ``status: active``, ``missCount: 0``, ``lastSeenAt``,
  ``expireAt = startsAt + 7 d``; denormalized ``cinema`` and ``movie`` blocks.
* ``bulk_write(ordered=False)``.

Aliases: ``auto``/``pending`` aliases from new TMDB matches; never over a manual alias,
and a ``pending`` alias may become ``auto``.
"""

from __future__ import annotations

import hashlib
import re
import threading
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId
from pymongo import UpdateOne

from ..core.config import CinemaConfig
from ..db import repositories as repo
from ..db.client import DB, Document
from .ids import movie_key, showtime_id
from .match import MatchResult
from .normalize import NormalizedMovie, NormalizedShowtime, map_genres
from .validate import SYNOPSIS_MAX, TITLE_MAX, cap, strip_html

EXPIRE_AFTER = timedelta(days=7)
#: Cinemas run in parallel threads and share movies; find-then-insert must not race
#: (the unique ``localKey``/``tmdbId`` indexes would reject the second insert).
_MOVIE_LOCK = threading.Lock()
_SLUG_JUNK = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, fallback_seed: str) -> str:
    """ASCII slug; a title with no Latin letters (Urdu) gets ``movie-<hash8>``."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = _SLUG_JUNK.sub("-", ascii_text.lower()).strip("-")[:70].strip("-")
    if slug:
        return slug
    return "movie-" + hashlib.sha256(fallback_seed.encode()).hexdigest()[:8]


def local_key_for(movie: NormalizedMovie) -> str:
    base = slugify(movie.title, fallback_seed=movie.title_key)
    return f"{base}-{movie.year}" if movie.year else base


@dataclass(frozen=True)
class StoredMovie:
    id: Any
    key: str  # movieKey for showtime ids
    slug: str
    title: str
    genres: list[str]
    runtime_min: int | None
    poster_key: str | None


@dataclass(frozen=True)
class UpsertCounts:
    movies: int
    showtimes: int
    aliases: int
    showtime_ids: frozenset[str] = frozenset()


def _cinema_fields(movie: NormalizedMovie) -> Document:
    fields: Document = {
        "title": movie.title,
        "genres": list(movie.genres),
        "languages": list(movie.languages),
        "rating": {"certification": movie.certification} if movie.certification else {},
    }
    for key, value in (
        ("originalTitle", movie.original_title),
        ("year", movie.year),
        ("synopsis", movie.synopsis),
        ("runtimeMin", movie.runtime_min),
        ("releaseDate", movie.release_date.isoformat() if movie.release_date else None),
    ):
        if value is not None:
            fields[key] = value
    return fields


def _tmdb_fields(match: MatchResult, movie: NormalizedMovie, now: datetime) -> Document:
    d = match.details
    assert d is not None
    fields: Document = {
        "title": cap(strip_html(d.title), TITLE_MAX) or movie.title,
        "genres": list(map_genres(d.genres)),
        "languages": list(movie.languages),
        "tmdbRefreshedAt": now,
    }
    for key, value in (
        ("originalTitle", cap(strip_html(d.original_title), TITLE_MAX) or None),
        ("year", d.release_date.year if d.release_date else movie.year),
        ("synopsis", cap(strip_html(d.overview), SYNOPSIS_MAX) or movie.synopsis),
        ("runtimeMin", d.runtime_min if d.runtime_min and 30 <= d.runtime_min <= 300 else None),
        ("releaseDate", d.release_date.isoformat() if d.release_date else None),
    ):
        if value is not None:
            fields[key] = value
    fields["rating"] = {"certification": movie.certification} if movie.certification else {}
    return fields


def _unique_slug(db: DB, base: str, existing_id: Any) -> str:
    slug, n = base, 2
    while repo.slug_taken(db, slug, except_id=existing_id):
        slug, n = f"{base}-{n}", n + 1
    return slug


def upsert_movie(db: DB, movie: NormalizedMovie, match: MatchResult, now: datetime) -> StoredMovie:
    with _MOVIE_LOCK:
        return _upsert_movie(db, movie, match, now)


def _upsert_movie(db: DB, movie: NormalizedMovie, match: MatchResult, now: datetime) -> StoredMovie:
    tmdb_id = match.tmdb_id if match.status == "matched" else None
    local_key = match.local_key if match.via_alias and match.local_key else local_key_for(movie)
    existing = repo.find_movie(db, tmdb_id=tmdb_id, local_key=local_key)

    if existing is not None:
        movie_id = existing["_id"]
        local_key = existing["localKey"]
        slug = existing["slug"]
    else:
        movie_id = ObjectId()
        local_key = _unique_slug(db, local_key, None)
        slug = local_key

    already_matched = existing is not None and existing.get("matchStatus") == "matched"
    status = match.status
    if match.details is not None:
        fields = _tmdb_fields(match, movie, now)
    elif already_matched:
        # Never downgrade: a matched movie keeps its TMDB fields and status when this run's
        # match is weaker (alias hit without details, TMDB down → provisional).
        fields, status = {}, "matched"
    else:
        fields = _cinema_fields(movie)
    fields.update({"matchStatus": status, "nowShowing": True, "updatedAt": now})
    if tmdb_id is not None:
        fields["tmdbId"] = tmdb_id

    on_insert: Document = {"slug": slug, "localKey": local_key, "poster": None, "createdAt": now}
    repo.upsert_movie(db, movie_id, fields, on_insert)
    stored = db[repo.MOVIES].find_one(
        {"_id": movie_id}, {"title": 1, "genres": 1, "runtimeMin": 1, "poster": 1, "tmdbId": 1}
    )
    assert stored is not None
    poster = stored.get("poster") or {}
    return StoredMovie(
        id=movie_id,
        key=movie_key(stored.get("tmdbId"), local_key),
        slug=slug,
        title=stored["title"],
        genres=list(stored.get("genres") or []),
        runtime_min=stored.get("runtimeMin"),
        poster_key=poster.get("key") if isinstance(poster, dict) else None,
    )


def showtime_update(
    cinema: CinemaConfig, movie: StoredMovie, show: NormalizedShowtime, now: datetime
) -> tuple[str, UpdateOne]:
    """The showtime's id and its upsert."""
    sid = showtime_id(cinema.id, movie.key, show.starts_at, show.hall, show.format)
    movie_block: Document = {
        "title": movie.title,
        "slug": movie.slug,
        "posterKey": movie.poster_key,
        "genres": movie.genres,
    }
    if movie.runtime_min:
        movie_block["runtimeMin"] = movie.runtime_min
    fields: Document = {
        "cinemaId": cinema.id,
        "movieId": movie.id,
        "startsAt": show.starts_at,
        "format": show.format,
        "language": show.language,
        "status": "active",
        "missCount": 0,
        "lastSeenAt": now,
        "cinema": {"name": cinema.name, "city": cinema.city},
        "movie": movie_block,
        "expireAt": show.starts_at + EXPIRE_AFTER,
        "updatedAt": now,
    }
    unset: dict[str, str] = {}
    optional: tuple[tuple[str, Any], ...] = (
        ("hall", show.hall or None),
        ("bookingUrl", show.booking_url),
        (
            "endsAt",
            show.starts_at + timedelta(minutes=movie.runtime_min) if movie.runtime_min else None,
        ),
    )
    for key, value in optional:
        if value is not None:
            fields[key] = value
        else:
            unset[key] = ""
    update: Document = {"$set": fields, "$setOnInsert": {"seats": {"status": "unknown"}}}
    if unset:
        update["$unset"] = unset
    return sid, UpdateOne({"_id": sid}, update, upsert=True)


def _alias_ops(db: DB, matches: dict[str, MatchResult], now: datetime) -> list[UpdateOne]:
    existing = {d["_id"]: d.get("source") for d in repo.load_aliases(db)}
    ops = []
    for key, match in matches.items():
        source = match.new_alias_source
        if source is None or match.tmdb_id is None:
            continue
        current = existing.get(repo.alias_id(key, None))
        if current == "manual" or current == source or (current == "auto" and source == "pending"):
            continue
        ops.append(
            repo.alias_op(
                key,
                movie_key=str(match.tmdb_id),
                source=source,
                confidence=match.score,
                cinema_id=None,
                now=now,
            )
        )
    return ops


def upsert_cinema(
    db: DB,
    cinema: CinemaConfig,
    movies: Sequence[NormalizedMovie],
    showtimes: Sequence[NormalizedShowtime],
    matches: dict[str, MatchResult],
    now: datetime,
) -> UpsertCounts:
    """Write one cinema's validated, matched rows. Idempotent for the same input and now."""
    by_key = {m.title_key: m for m in movies}
    stored: dict[str, StoredMovie] = {}
    for key, match in sorted(matches.items()):
        movie = by_key.get(key)
        if movie is None:
            show = next(s for s in showtimes if s.title_key == key)
            movie = NormalizedMovie(
                title=show.movie_title,
                title_key=key,
                local_key=show.movie_local_key,
                original_title=None,
                runtime_min=None,
                genres=(),
                languages=(show.language,),
                synopsis=None,
                release_date=None,
                year=None,
                certification=None,
            )
        stored[key] = upsert_movie(db, movie, match, now)

    built = [
        showtime_update(cinema, stored[s.title_key], s, now)
        for s in showtimes
        if s.title_key in stored
    ]
    ops = [op for _, op in built]
    repo.bulk_upsert(db, repo.SHOWTIMES, ops)

    latest: dict[Any, datetime] = {}
    for s in showtimes:
        if s.title_key in stored:
            mid = stored[s.title_key].id
            latest[mid] = max(latest.get(mid, s.starts_at), s.starts_at)
    repo.raise_last_showing(db, latest)

    alias_ops = _alias_ops(db, matches, now)
    repo.bulk_upsert(db, repo.ALIASES, alias_ops)
    return UpsertCounts(
        movies=len(stored),
        showtimes=len(ops),
        aliases=len(alias_ops),
        showtime_ids=frozenset(sid for sid, _ in built),
    )
