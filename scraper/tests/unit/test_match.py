# ruff: noqa: RUF001  (Turkish dotless i in a real TMDB title is deliberate)
"""P1-09: TMDB client and matcher against a mocked TMDB (plan §10.4)."""

from __future__ import annotations

import dataclasses
import itertools
import random
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from moviespk_scraper.core.config import AliasConfig
from moviespk_scraper.pipeline.match import (
    Alias,
    AliasTable,
    Matcher,
    needs_refresh,
    score_candidate,
)
from moviespk_scraper.pipeline.normalize import NormalizedMovie
from moviespk_scraper.services.tmdb import (
    DEFAULT_IMAGE_BASE,
    RateLimiter,
    TmdbCandidate,
    TmdbClient,
    TmdbConfiguration,
    TmdbError,
)

API = "https://api.themoviedb.org/3"


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def tmdb(clock: FakeClock) -> Iterator[TmdbClient]:
    limiter = RateLimiter(clock=clock, sleep=clock.sleep)
    with TmdbClient("v3key", limiter=limiter, sleep=clock.sleep, rng=random.Random(1)) as client:
        yield client


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=False) as r:
        yield r


def movie(title: str, **changes: Any) -> NormalizedMovie:
    from moviespk_scraper.pipeline.normalize import title_key

    base = NormalizedMovie(
        title=title,
        title_key=title_key(title),
        local_key="F1",
        original_title=None,
        runtime_min=None,
        genres=(),
        languages=(),
        synopsis=None,
        release_date=None,
        year=None,
        certification=None,
    )
    return dataclasses.replace(base, **changes)


def search(*results: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200, json={"page": 1, "results": list(results), "total_results": len(results)}
    )


def details(
    tmdb_id: int, title: str, runtime: int = 120, poster: str | None = "/p.jpg"
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": tmdb_id,
            "title": title,
            "original_title": title,
            "overview": "An overview.",
            "runtime": runtime,
            "genres": [{"id": 28, "name": "Action"}],
            "release_date": "2026-11-20",
            "poster_path": poster,
        },
    )


# --- acceptance ------------------------------------------------------------------------


def test_score_90_or_more_matches_with_poster_path(
    tmdb: TmdbClient, router: respx.MockRouter
) -> None:
    router.get("/search/movie").mock(
        return_value=search({"id": 7, "title": "Resident Evil", "release_date": "2026-11-20"})
    )
    router.get("/movie/7").mock(return_value=details(7, "Resident Evil", poster="/re.jpg"))
    result = Matcher(tmdb).match(movie("Resident Evil", year=2026))
    assert result.status == "matched" and result.tmdb_id == 7
    assert result.score is not None and result.score >= 90
    assert result.poster_path == "/re.jpg"
    assert result.new_alias_source == "auto"


def test_score_around_75_is_provisional_with_pending_alias(
    tmdb: TmdbClient, router: respx.MockRouter
) -> None:
    router.get("/search/movie").mock(
        return_value=search(
            {"id": 8, "title": "Avengers Doomsday Part One", "release_date": "2026-05-01"}
        )
    )
    router.get("/movie/8").mock(return_value=details(8, "Avengers Doomsday Part One"))
    m = movie("Avengers Dooms")
    score = score_candidate(m, TmdbCandidate(8, "Avengers Doomsday Part One", None, None))
    assert 70 <= score < 90
    result = Matcher(tmdb).match(m)
    assert result.status == "provisional" and result.new_alias_source == "pending"
    assert result.tmdb_id == 8


def test_no_results_is_unmatched(tmdb: TmdbClient, router: respx.MockRouter) -> None:
    router.get("/search/movie").mock(return_value=search())
    result = Matcher(tmdb).match(movie("Chakkven"))
    assert result.status == "unmatched" and result.local_key == "F1"
    assert result.new_alias_source is None


def test_low_score_is_unmatched_without_details_call(
    tmdb: TmdbClient, router: respx.MockRouter
) -> None:
    router.get("/search/movie").mock(
        return_value=search({"id": 9, "title": "Something Else Entirely"})
    )
    details_route = router.get("/movie/9").mock(return_value=details(9, "x"))
    assert Matcher(tmdb).match(movie("Chakkven")).status == "unmatched"
    assert details_route.call_count == 0


def test_alias_hit_makes_zero_tmdb_calls(tmdb: TmdbClient, router: respx.MockRouter) -> None:
    route = router.get("/search/movie").mock(return_value=search())
    aliases = AliasTable(
        manual=[Alias.from_config(AliasConfig(alias="belkis", tmdb_id=123, note="dubbed title"))]
    )
    result = Matcher(tmdb, aliases).match(movie("Belkis"))
    assert result.status == "matched" and result.tmdb_id == 123 and result.via_alias == "manual"
    assert route.call_count == 0 and tmdb.calls == 0


def test_tmdb_503_is_provisional_without_crash(tmdb: TmdbClient, router: respx.MockRouter) -> None:
    route = router.get("/search/movie").mock(return_value=httpx.Response(503))
    matcher = Matcher(tmdb)
    result = matcher.match(movie("Resident Evil"))
    assert result.status == "provisional" and result.tmdb_failed
    assert route.call_count == 3  # retried, then gave up
    matcher.match(movie("Resident Evil"))  # not cached: retried (next run, or here)
    assert route.call_count == 6


def test_one_search_per_unique_title_per_run(tmdb: TmdbClient, router: respx.MockRouter) -> None:
    route = router.get("/search/movie").mock(return_value=search())
    matcher = Matcher(tmdb)
    for cinema in ("a", "b", "c"):
        matcher.match(movie("Chakkven (Punjabi)".replace(" (Punjabi)", "")), cinema)
        matcher.match(movie("CHAKKVEN"), cinema)
    assert route.call_count == 1


def test_request_spacing_at_least_200ms(
    tmdb: TmdbClient, router: respx.MockRouter, clock: FakeClock
) -> None:
    starts: list[float] = []

    def record(request: httpx.Request) -> httpx.Response:
        starts.append(clock.now)
        return search()

    router.get("/search/movie").mock(side_effect=record)
    matcher = Matcher(tmdb)
    for title in ("One", "Two", "Three", "Four", "Five", "Six"):
        matcher.match(movie(title))
    gaps = [b - a for a, b in itertools.pairwise(starts)]
    assert len(gaps) == 5 and all(g >= 0.2 - 1e-9 for g in gaps)


# --- scoring ------------------------------------------------------------------------------


def test_year_bonus_and_runtime_penalty(tmdb: TmdbClient, router: respx.MockRouter) -> None:
    m = movie("Ghost Soldier", year=2026, runtime_min=90)
    with_year = score_candidate(m, TmdbCandidate(1, "Ghost Soldiers", None, date(2026, 1, 1)))
    without = score_candidate(m, TmdbCandidate(1, "Ghost Soldiers", None, date(2019, 1, 1)))
    assert with_year == min(without + 5, 100)

    router.get("/search/movie").mock(
        return_value=search({"id": 3, "title": "Ghost Soldier", "release_date": "2026-01-01"})
    )
    router.get("/movie/3").mock(return_value=details(3, "Ghost Soldier", runtime=140))  # 50 min off
    result = Matcher(tmdb).match(m)
    assert result.score == 90 and result.status == "matched"  # 100 (capped) - 10


def test_original_title_counts(tmdb: TmdbClient) -> None:
    m = movie("Kible Bitlisli Belkis")
    c = TmdbCandidate(5, "Belkis: The Qibla Series", "Kıble: Bitlisli Belkıs", None)
    assert score_candidate(m, c) >= 90


# --- aliases ------------------------------------------------------------------------------


def test_manual_beats_stored_and_cinema_specific_beats_global() -> None:
    table = AliasTable(
        manual=[
            Alias("belkis", "manual", tmdb_id=1),
            Alias("belkis", "manual", tmdb_id=2, cinema_id="cinepax-ocean-mall"),
        ],
        stored=[Alias("belkis", "auto", tmdb_id=3), Alias("hope", "pending", tmdb_id=4)],
    )
    assert table.find("belkis", None).tmdb_id == 1  # type: ignore[union-attr]
    assert table.find("belkis", "cinepax-ocean-mall").tmdb_id == 2  # type: ignore[union-attr]
    assert table.find("belkis", "cinepax-packages-mall").tmdb_id == 1  # type: ignore[union-attr]
    assert table.find("hope", None).source == "pending"  # type: ignore[union-attr]
    assert table.find("nothing", None) is None


def test_stored_aliases_map_to_statuses(tmdb: TmdbClient) -> None:
    table = AliasTable(
        stored=[Alias("hope", "pending", tmdb_id=4), Alias("ebenezer", "auto", tmdb_id=5)]
    )
    matcher = Matcher(tmdb, table)
    assert matcher.match(movie("Hope")).status == "provisional"
    assert matcher.match(movie("Ebenezer")).status == "matched"
    assert tmdb.calls == 0


def test_local_key_alias_is_a_local_movie(tmdb: TmdbClient) -> None:
    alias = Alias.from_config(
        AliasConfig(alias="jawani phir nahi ani 3", local_key="jpna3", note="not on TMDB")
    )
    result = Matcher(tmdb, AliasTable(manual=[alias])).match(movie("Jawani Phir Nahi Ani 3"))
    assert (result.status, result.local_key, tmdb.calls) == ("unmatched", "jpna3", 0)


def test_without_tmdb_everything_is_unmatched_locally() -> None:
    assert Matcher(None).match(movie("Resident Evil")).status == "unmatched"


# --- client details -----------------------------------------------------------------------


def test_v3_key_is_a_query_param_and_v4_token_a_header(router: respx.MockRouter) -> None:
    route = router.get("/search/movie").mock(return_value=search())
    with TmdbClient("v3key", sleep=lambda _s: None) as v3:
        v3.search_movie("x")
    assert route.calls.last.request.url.params["api_key"] == "v3key"
    with TmdbClient("eyJhbGciOi.token", sleep=lambda _s: None) as v4:
        v4.search_movie("x")
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer eyJhbGciOi.token"
    assert "api_key" not in request.url.params


def test_search_sends_year_and_region(tmdb: TmdbClient, router: respx.MockRouter) -> None:
    route = router.get("/search/movie").mock(return_value=search())
    tmdb.search_movie("Dune", year=2026)
    params = route.calls.last.request.url.params
    assert (params["query"], params["year"], params["region"]) == ("Dune", "2026", "PK")


def test_429_honours_retry_after(
    tmdb: TmdbClient, router: respx.MockRouter, clock: FakeClock
) -> None:
    router.get("/search/movie").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "2"}), search()]
    )
    assert tmdb.search_movie("x") == []
    assert 2.0 in clock.sleeps


def test_404_is_an_error_without_retry(tmdb: TmdbClient, router: respx.MockRouter) -> None:
    route = router.get("/movie/1").mock(return_value=httpx.Response(404))
    with pytest.raises(TmdbError):
        tmdb.movie_details(1)
    assert route.call_count == 1


def test_configuration_cached_weekly_with_fallback(
    tmdb: TmdbClient, router: respx.MockRouter
) -> None:
    now = datetime(2026, 11, 25, tzinfo=UTC)
    fresh = TmdbConfiguration("https://cached.example/t/p/", now - timedelta(days=6))
    assert tmdb.configuration(cached=fresh, now=now) is fresh
    route = router.get("/configuration").mock(
        return_value=httpx.Response(
            200, json={"images": {"secure_base_url": "https://image.tmdb.org/t/p/"}}
        )
    )
    stale = TmdbConfiguration("https://old.example/", now - timedelta(days=8))
    assert tmdb.configuration(cached=stale, now=now).image_base_url == "https://image.tmdb.org/t/p/"
    tmdb.configuration(now=now)
    assert route.call_count == 1  # once per run


def test_configuration_falls_back_on_error(tmdb: TmdbClient, router: respx.MockRouter) -> None:
    router.get("/configuration").mock(return_value=httpx.Response(500))
    assert tmdb.configuration().image_base_url == DEFAULT_IMAGE_BASE


def test_needs_refresh_every_7_days() -> None:
    now = datetime(2026, 11, 25, tzinfo=UTC)
    assert needs_refresh(None, now)
    assert not needs_refresh(now - timedelta(days=6), now)
    assert needs_refresh(now - timedelta(days=7), now)


def test_empty_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        TmdbClient("  ")
