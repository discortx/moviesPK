"""P1-10 integration: cinema sync and upsert against MongoDB (CI: mongo:7 service).

The fixture pipeline: Cinepax fixtures → adapter → normalize → validate → match (offline,
one manual alias to a TMDB id) → upsert. Real indexes come from scripts/create_indexes.js.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from moviespk_scraper.adapters.base import RunContext
from moviespk_scraper.adapters.cinepax import CinepaxAdapter
from moviespk_scraper.core.circuit_breaker import CinemaBudget
from moviespk_scraper.core.config import CinemaConfig, load_config
from moviespk_scraper.core.http import ScraperHttpClient
from moviespk_scraper.core.logging import get_logger
from moviespk_scraper.core.offline import FixtureTransport, captured_at
from moviespk_scraper.db.client import DB, DbSettings, connect
from moviespk_scraper.pipeline.ids import showtime_id
from moviespk_scraper.pipeline.match import Alias, AliasTable, Matcher, MatchResult
from moviespk_scraper.pipeline.normalize import (
    NormalizedMovie,
    NormalizedShowtime,
    normalize_movie,
    normalize_showtime,
)
from moviespk_scraper.pipeline.sync_cinemas import sync_cinemas
from moviespk_scraper.pipeline.upsert import upsert_cinema
from moviespk_scraper.pipeline.validate import validate

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "scraper" / "tests" / "fixtures"
CAPTURE = "2026-11-25"
#: One film matched through a manual alias, so tmdbId-based ids are exercised.
ALIASES = AliasTable(manual=[Alias("resident evil", "manual", tmdb_id=1196970)])

Rows = tuple[CinemaConfig, list[NormalizedMovie], list[NormalizedShowtime], dict[str, MatchResult]]


@pytest.fixture
def db(mongo_uri: str, db_name: str) -> Iterator[DB]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed (needed for scripts/create_indexes.js)")
    env = os.environ | {"MONGODB_URI_SCRAPER": mongo_uri, "MONGODB_DB": db_name}
    proc = subprocess.run(
        [node, "scripts/create_indexes.js"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    client, database = connect(DbSettings(mongo_uri, db_name))
    yield database
    client.close()


def rows(cinema_id: str) -> tuple[Rows, datetime]:
    cinema = load_config().cinema(cinema_id)
    fixture = FIXTURES / cinema_id / CAPTURE
    now = captured_at(fixture)
    assert now is not None
    with ScraperHttpClient("t", transport=FixtureTransport(fixture), sleep=lambda _s: None) as http:
        ctx = RunContext(
            http=http, job="full", now=now, log=get_logger(), budget=CinemaBudget(cinema_id)
        )
        adapter = CinepaxAdapter()
        movies = adapter.list_movies(ctx, cinema)
        shows = adapter.list_showtimes(ctx, cinema)
    checked = validate(
        [normalize_movie(m) for m in movies], [normalize_showtime(s) for s in shows], now=now
    )
    matcher = Matcher(None, ALIASES)
    matches = {m.title_key: matcher.match(m, cinema_id) for m in checked.movies}
    return (cinema, checked.movies, checked.showtimes, matches), now


def run_pipeline(db: DB, cinema_ids: list[str]) -> None:
    config = load_config()
    for cinema_id in cinema_ids:
        (cinema, movies, shows, matches), now = rows(cinema_id)
        sync_cinemas(db, config.cinemas, now)
        upsert_cinema(db, cinema, movies, shows, matches, now)


def snapshot(db: DB) -> str:
    out: dict[str, Any] = {}
    for name in ("cinemas", "movies", "showtimes", "movie_aliases"):
        docs = [
            {k: v for k, v in d.items() if k != "updatedAt"}
            for d in db[name].find({}).sort("_id", 1)
        ]
        out[name] = docs
    return hashlib.sha256(json.dumps(out, default=str, sort_keys=True).encode()).hexdigest()


CINEPAX = ["cinepax-packages-mall", "cinepax-world-trade-center", "cinepax-ocean-mall"]


# --- acceptance -------------------------------------------------------------------------


def test_running_the_fixture_pipeline_twice_is_identical(db: DB) -> None:
    run_pipeline(db, CINEPAX)
    first = snapshot(db)
    run_pipeline(db, CINEPAX)
    assert snapshot(db) == first
    assert db.showtimes.count_documents({}) == 19 + 12 + 33
    assert db.cinemas.count_documents({}) == 5


def test_recreated_movie_with_same_tmdb_id_keeps_showtime_ids(db: DB) -> None:
    run_pipeline(db, ["cinepax-ocean-mall"])
    movie = db.movies.find_one({"tmdbId": 1196970})
    assert movie is not None and movie["matchStatus"] == "matched"
    ids_before = sorted(d["_id"] for d in db.showtimes.find({"movieId": movie["_id"]}))
    assert ids_before

    db.movies.delete_one({"_id": movie["_id"]})  # the movie is re-created next run
    run_pipeline(db, ["cinepax-ocean-mall"])
    recreated = db.movies.find_one({"tmdbId": 1196970})
    assert recreated is not None and recreated["_id"] != movie["_id"]
    ids_after = sorted(d["_id"] for d in db.showtimes.find({"movieId": recreated["_id"]}))
    assert ids_after == ids_before


def test_hall_missing_and_blank_are_stored_once_without_hall(db: DB) -> None:
    (cinema, movies, shows, matches), now = rows("cinepax-packages-mall")
    show = shows[0]
    for hall in ("", "  "):
        blank = dataclasses.replace(show, hall=hall.strip())
        upsert_cinema(db, cinema, movies, [blank], matches, now)
    docs = list(db.showtimes.find({"startsAt": show.starts_at, "cinemaId": cinema.id}))
    assert len(docs) == 1
    assert "hall" not in docs[0]


# --- documents --------------------------------------------------------------------------


def test_documents_have_the_planned_shape(db: DB) -> None:
    run_pipeline(db, ["cinepax-ocean-mall"])
    cinema = db.cinemas.find_one({"_id": "cinepax-ocean-mall"})
    assert cinema is not None
    assert cinema["location"] == {
        "type": "Point",
        "coordinates": [67.03598697114558, 24.82401989059472],
    }
    # YAML wins: the stored flag follows cinemas.yml, whatever it currently says.
    assert cinema["enabled"] is load_config().cinema("cinepax-ocean-mall").enabled
    assert cinema["health"] == {"status": "unknown"}
    assert "phone" not in cinema

    show = db.showtimes.find_one({"cinemaId": "cinepax-ocean-mall", "hall": "GOLD-1"})
    assert show is not None
    movie = db.movies.find_one({"_id": show["movieId"]})
    assert movie is not None
    key = str(movie["tmdbId"]) if "tmdbId" in movie else movie["localKey"]
    assert show["_id"] == showtime_id(
        "cinepax-ocean-mall", key, show["startsAt"], show.get("hall"), show["format"]
    )
    assert show["status"] == "active" and show["missCount"] == 0
    assert show["expireAt"] - show["startsAt"] == datetime(2026, 1, 8) - datetime(2026, 1, 1)
    assert show["cinema"] == {"name": "Cinepax Ocean Mall", "city": "karachi"}
    assert show["movie"]["slug"] == movie["slug"] and show["seats"] == {"status": "unknown"}
    assert show["bookingUrl"].startswith("https://web.cinepax.com/pages/booking.html?")
    assert movie["poster"] is None and movie["nowShowing"] is True
    assert movie["lastShowingAt"] >= show["startsAt"]


def test_late_night_show_is_stored_on_its_utc_instant(db: DB) -> None:
    run_pipeline(db, ["cinepax-ocean-mall"])
    show = db.showtimes.find_one(
        {"cinemaId": "cinepax-ocean-mall", "movie.title": "Resident Evil", "hall": "GOLD-1"}
    )
    late = [
        d["startsAt"]
        for d in db.showtimes.find({"cinemaId": "cinepax-ocean-mall", "movieId": show["movieId"]})  # type: ignore[index]
    ]
    assert datetime(2026, 11, 27, 19, 15, tzinfo=UTC) in late  # 2026-11-28 00:15 PKT


def test_same_film_at_three_cinemas_is_one_movie(db: DB) -> None:
    run_pipeline(db, CINEPAX)
    belkis = list(db.movies.find({"title": "Belkis"}))
    assert len(belkis) == 1
    cinemas = db.showtimes.distinct("cinemaId", {"movieId": belkis[0]["_id"]})
    assert sorted(cinemas) == sorted(CINEPAX)


def test_disabled_or_removed_cinema_is_kept_disabled(db: DB) -> None:
    now = datetime(2026, 11, 25, tzinfo=UTC)
    db.cinemas.insert_one({"_id": "old-cinema", "name": "Old", "enabled": True})
    sync_cinemas(db, load_config().cinemas, now)
    old = db.cinemas.find_one({"_id": "old-cinema"})
    assert old is not None and old["enabled"] is False
    assert db.cinemas.count_documents({}) == 6


def test_matched_movie_is_never_downgraded(db: DB) -> None:
    run_pipeline(db, ["cinepax-ocean-mall"])
    (cinema, movies, shows, matches), now = rows("cinepax-ocean-mall")
    re_key = next(k for k in matches if k == "resident evil")
    matches[re_key] = MatchResult("provisional", re_key, local_key="F000003117", tmdb_failed=True)
    upsert_cinema(db, cinema, movies, shows, matches, now)
    movie = db.movies.find_one({"tmdbId": 1196970})
    assert movie is not None and movie["matchStatus"] == "matched"
