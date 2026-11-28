"""P2-04 acceptance: an alias added to aliases.yml re-links a movie's showtimes on the next
run, with no duplicate showtimes (plan §8.4, §10.4)."""

from __future__ import annotations

import pytest

from moviespk_scraper.adapters.base import RunContext
from moviespk_scraper.adapters.registry import get_adapter
from moviespk_scraper.core.circuit_breaker import CinemaBudget
from moviespk_scraper.core.config import load_config
from moviespk_scraper.core.http import ScraperHttpClient
from moviespk_scraper.core.logging import get_logger
from moviespk_scraper.core.offline import FixtureTransport, captured_at
from moviespk_scraper.db.client import DB
from moviespk_scraper.pipeline.ids import showtime_id
from moviespk_scraper.pipeline.match import Alias, AliasTable, Matcher
from moviespk_scraper.pipeline.normalize import normalize_movie, normalize_showtime
from moviespk_scraper.pipeline.sync_cinemas import sync_cinemas
from moviespk_scraper.pipeline.upsert import UpsertCounts, upsert_cinema
from moviespk_scraper.pipeline.validate import validate

from .test_upsert import CAPTURES, FIXTURES

pytestmark = pytest.mark.integration

CINEPAX = "cinepax-packages-mall"
UNIVERSAL = "universal-emporium-mall-lahore"
BELKIS_TMDB = 990001  # a made-up id: offline runs never call TMDB


def run(db: DB, cinema_id: str, aliases: list[Alias]) -> UpsertCounts:
    """One offline full run of ``cinema_id`` with the given manual aliases (aliases.yml)."""
    config = load_config()
    cinema = config.cinema(cinema_id)
    fixture = FIXTURES / cinema_id / CAPTURES[cinema.adapter]
    now = captured_at(fixture)
    assert now is not None
    with ScraperHttpClient("t", transport=FixtureTransport(fixture), sleep=lambda _s: None) as h:
        ctx = RunContext(http=h, job="full", now=now, log=get_logger(), budget=CinemaBudget("t"))
        adapter = get_adapter(cinema.adapter)
        movies = adapter.list_movies(ctx, cinema)
        shows = adapter.list_showtimes(ctx, cinema)
    checked = validate(
        [normalize_movie(m) for m in movies], [normalize_showtime(s) for s in shows], now=now
    )
    matcher = Matcher(None, AliasTable(manual=aliases))
    matches = {m.title_key: matcher.match(m, cinema_id) for m in checked.movies}
    sync_cinemas(db, config.cinemas, now)
    return upsert_cinema(db, cinema, checked.movies, checked.showtimes, matches, now)


def showtimes_of(db: DB, movie_id: object, cinema_id: str) -> list[dict]:
    return list(db.showtimes.find({"movieId": movie_id, "cinemaId": cinema_id}))


def test_tmdb_alias_relinks_a_local_movie_without_duplicates(db: DB) -> None:
    first = run(db, CINEPAX, [])
    belkis = db.movies.find_one({"title": "Belkis"})
    assert belkis is not None and "tmdbId" not in belkis
    before = sorted(
        (d["startsAt"], d.get("hall")) for d in showtimes_of(db, belkis["_id"], CINEPAX)
    )
    total = db.showtimes.count_documents({})
    assert before and total == first.showtimes

    alias = Alias("belkis", "manual", tmdb_id=BELKIS_TMDB)
    second = run(db, CINEPAX, [alias])

    movie = db.movies.find_one({"_id": belkis["_id"]})
    assert movie is not None and movie["tmdbId"] == BELKIS_TMDB  # upgraded in place
    assert movie["slug"] == belkis["slug"]  # URLs never change
    after = showtimes_of(db, belkis["_id"], CINEPAX)
    assert sorted((d["startsAt"], d.get("hall")) for d in after) == before
    assert db.showtimes.count_documents({}) == total  # no duplicates
    assert second.relinked == len(before)
    for d in after:  # every id is now built from the tmdbId
        assert d["_id"] == showtime_id(
            CINEPAX, str(BELKIS_TMDB), d["startsAt"], d.get("hall"), d["format"]
        )
        assert d["status"] == "active" and d["missCount"] == 0

    third = run(db, CINEPAX, [alias])  # steady state: nothing moves, nothing added
    assert third.relinked == 0 and db.showtimes.count_documents({}) == total


def test_local_key_alias_merges_one_cinemas_showtimes_into_the_other_movie(db: DB) -> None:
    """The Belkis case of 2026-11-28: Universal's "Belkis" (no year) and Cinepax's
    "18+Belkis" (2026) were two movies until an alias joined them."""
    run(db, CINEPAX, [])
    run(db, UNIVERSAL, [])
    cinepax_belkis = db.movies.find_one({"localKey": "belkis-2026"})
    universal_belkis = db.movies.find_one({"localKey": "belkis"})
    assert cinepax_belkis is not None and universal_belkis is not None
    moving = len(showtimes_of(db, universal_belkis["_id"], UNIVERSAL))
    total = db.showtimes.count_documents({})
    assert moving > 0

    alias = Alias("belkis", "manual", local_key="belkis-2026", cinema_id=UNIVERSAL)
    counts = run(db, UNIVERSAL, [alias])

    assert counts.relinked == moving
    assert showtimes_of(db, universal_belkis["_id"], UNIVERSAL) == []
    assert len(showtimes_of(db, cinepax_belkis["_id"], UNIVERSAL)) == moving
    assert db.showtimes.count_documents({}) == total  # no duplicates
    assert db.showtimes.count_documents({"cinemaId": UNIVERSAL}) == 97
    merged = showtimes_of(db, cinepax_belkis["_id"], UNIVERSAL)
    assert {d["movie"]["slug"] for d in merged} == {"belkis-2026"}


def test_matched_movie_is_never_merged_away(db: DB) -> None:
    run(db, CINEPAX, [Alias("belkis", "manual", tmdb_id=BELKIS_TMDB)])
    matched = db.movies.find_one({"tmdbId": BELKIS_TMDB})
    assert matched is not None
    own = len(showtimes_of(db, matched["_id"], CINEPAX))
    # A bad alias pointing the title elsewhere must not move a matched movie's showtimes.
    db.movies.insert_one({"_id": "elsewhere", "localKey": "other", "slug": "other"})
    run(db, CINEPAX, [Alias("belkis", "manual", local_key="other")])
    assert len(showtimes_of(db, matched["_id"], CINEPAX)) == own
