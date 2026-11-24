"""Canonical showtime ID (plan §8.1).

``_id = sha1(cinemaId|movieKey|startsAtUtcISO|hall|format)``:

* always exactly five components joined by ``|``, UTF-8 encoded, lowercase hex digest;
* ``movieKey`` is the TMDB id as a decimal string, else the movie's ``localKey``;
* ``startsAtUtcISO`` is ``YYYY-MM-DDTHH:MM:SSZ`` (UTC, seconds precision);
* ``hall`` is the normalized hall text; missing, ``None``, empty and whitespace-only
  halls all become ``""`` (the slot is kept, e.g. ``...T18:30:00Z||2D``).

This is the only implementation. Every caller (pipeline, ``scripts/seed_dev.py``,
tests) must use it.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from moviespk_scraper.models.vocab import Format
from moviespk_scraper.pipeline.text import normalize_text


def canonical_hall(hall: str | None) -> str:
    """Normalized hall; ``""`` means "no hall" (the stored field is then omitted)."""
    return normalize_text(hall)


def movie_key(tmdb_id: int | None, local_key: str | None) -> str:
    """``tmdbId`` as a decimal string, else ``localKey``."""
    if tmdb_id is not None:
        if isinstance(tmdb_id, bool) or tmdb_id <= 0:
            raise ValueError("tmdb_id must be a positive integer")
        return str(tmdb_id)
    if not local_key:
        raise ValueError("either tmdb_id or local_key is required")
    return local_key


def utc_iso_seconds(starts_at: datetime) -> str:
    """``YYYY-MM-DDTHH:MM:SSZ``; rejects naive datetimes."""
    if starts_at.tzinfo is None or starts_at.utcoffset() is None:
        raise ValueError("starts_at must be timezone-aware")
    return starts_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def showtime_id(
    cinema_id: str,
    movie_key_value: str,
    starts_at: datetime,
    hall: str | None,
    fmt: Format,
) -> str:
    """Deterministic showtime ``_id`` (40 lowercase hex chars)."""
    if not cinema_id or not movie_key_value:
        raise ValueError("cinema_id and movie key are required")
    parts = (cinema_id, movie_key_value, utc_iso_seconds(starts_at), canonical_hall(hall), fmt)
    return hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()
