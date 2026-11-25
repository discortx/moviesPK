"""P1-06: the Cinepax adapter against the captured fixtures (plan §10.1, §10.3).

Snapshots live in ``tests/snapshots/cinepax/``. After an intended parser change, regenerate
them with ``UPDATE_SNAPSHOTS=1 pytest tests/unit/test_adapter_cinepax.py`` and review the diff.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from moviespk_scraper.adapters import registry
from moviespk_scraper.adapters.base import RunContext, build_booking_url
from moviespk_scraper.adapters.cinepax import CinepaxAdapter
from moviespk_scraper.cli import main
from moviespk_scraper.core.circuit_breaker import CinemaBudget
from moviespk_scraper.core.config import CinemaConfig, load_config
from moviespk_scraper.core.errors import SchemaDriftError
from moviespk_scraper.core.http import ScraperHttpClient
from moviespk_scraper.core.logging import get_logger
from moviespk_scraper.core.offline import FixtureTransport

TESTS = Path(__file__).resolve().parents[1]
FIXTURES = TESTS / "fixtures"
SNAPSHOTS = TESTS / "snapshots" / "cinepax"
CAPTURED = "2026-11-25"
#: The capture time (2026-11-25 23:10 PKT): the reference "now" for the 7-day window.
NOW = datetime(2026, 11, 25, 18, 10, tzinfo=UTC)
CINEMAS = ["cinepax-packages-mall", "cinepax-world-trade-center", "cinepax-ocean-mall"]

Run = Callable[..., tuple[CinepaxAdapter, RunContext, FixtureTransport]]


def cinema_config(cinema_id: str, **changes: Any) -> CinemaConfig:
    base = load_config().cinema(cinema_id)
    return base.model_copy(update=changes) if changes else base


@pytest.fixture
def make_ctx(tmp_path: Path) -> Iterator[Run]:
    clients: list[ScraperHttpClient] = []

    def make(
        fixture_dir: Path, *, now: datetime = NOW
    ) -> tuple[CinepaxAdapter, RunContext, FixtureTransport]:
        transport = FixtureTransport(fixture_dir)
        http = ScraperHttpClient(
            "MoviesPKBot/1.0 (+test)", transport=transport, sleep=lambda _s: None
        )
        clients.append(http)
        ctx = RunContext(
            http=http,
            job="full",
            now=now,
            log=get_logger(),
            budget=CinemaBudget("test"),
            debug_dir=tmp_path / "debug",
        )
        return CinepaxAdapter(), ctx, transport

    yield make
    for http in clients:
        http.close()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, tuple | list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _snapshot(adapter: CinepaxAdapter, ctx: RunContext, cinema: CinemaConfig) -> dict[str, Any]:
    return {
        "movies": [_jsonable(dataclasses.asdict(m)) for m in adapter.list_movies(ctx, cinema)],
        "showtimes": [
            _jsonable(dataclasses.asdict(s)) for s in adapter.list_showtimes(ctx, cinema)
        ],
    }


# --- acceptance: fixture output equals the snapshot -------------------------------------


@pytest.mark.parametrize("cinema_id", CINEMAS)
def test_fixture_output_equals_snapshot(make_ctx: Run, cinema_id: str) -> None:
    adapter, ctx, _ = make_ctx(FIXTURES / cinema_id / CAPTURED)
    actual = _snapshot(adapter, ctx, cinema_config(cinema_id))
    path = SNAPSHOTS / f"{cinema_id}.json"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(actual, indent=2, ensure_ascii=False) + "\n").encode())
    assert actual == json.loads(path.read_text(encoding="utf-8"))


def test_first_cinema_has_movies_and_showtimes(make_ctx: Run) -> None:
    adapter, ctx, _ = make_ctx(FIXTURES / "cinepax-packages-mall" / CAPTURED)
    cinema = cinema_config("cinepax-packages-mall")
    movies = adapter.list_movies(ctx, cinema)
    shows = adapter.list_showtimes(ctx, cinema)
    assert len(movies) == 8 and len(shows) == 19
    first = shows[0]
    assert first.external_id and first.hall and first.format_text == "2D"
    assert first.starts_at.tzinfo is None  # naive PKT; the normalizer converts to UTC
    assert {s.movie_local_key for s in shows} <= {m.local_key for m in movies}


# --- acceptance: after-midnight show keeps its real calendar date ---------------------


def test_late_night_show_maps_to_next_calendar_date(make_ctx: Run) -> None:
    """Ocean Mall lists Resident Evil at 00:15 under businessDate 2026-11-27
    (lateNight: true); it must start on 2026-11-28 00:15 PKT."""
    adapter, ctx, _ = make_ctx(FIXTURES / "cinepax-ocean-mall" / CAPTURED)
    shows = adapter.list_showtimes(ctx, cinema_config("cinepax-ocean-mall"))
    late = [s for s in shows if s.starts_at.hour == 0]
    assert len(late) == 1
    assert late[0].movie_title == "18+Resident Evil (English)"
    assert late[0].starts_at == datetime(2026, 11, 28, 0, 15)


# --- acceptance: a drift fixture raises SchemaDriftError ------------------------------


def _drift_fixture(tmp_path: Path, mutate: Callable[[Any], Any]) -> Path:
    src = FIXTURES / "cinepax-packages-mall" / CAPTURED
    dst = tmp_path / "drift"
    shutil.copytree(src, dst)
    movies = next(dst.glob("002-api-movies-*.json"))
    data = json.loads(movies.read_text(encoding="utf-8"))
    movies.write_text(json.dumps(mutate(data)), encoding="utf-8")
    return dst


def _drop(key: str) -> Callable[[Any], Any]:
    def mutate(data: Any) -> Any:
        del data[0][key]
        return data

    return mutate


def _drop_session_key(key: str) -> Callable[[Any], Any]:
    def mutate(data: Any) -> Any:
        del next(iter(data[0]["screens"].values()))["sessions"][0][key]
        return data

    return mutate


def _skew_calendar_date(data: Any) -> Any:
    next(iter(data[0]["screens"].values()))["sessions"][0]["calendarDate"] = "2026-12-31"
    return data


@pytest.mark.parametrize(
    "mutate",
    [
        _drop("screens"),
        _drop("title"),
        _drop_session_key("sessionId"),
        _drop_session_key("showtime"),
        _drop_session_key("calendarDate"),
        _skew_calendar_date,
        lambda data: {"films": data},
    ],
    ids=["screens", "title", "sessionId", "showtime", "calendarDate", "skewed-date", "not-a-list"],
)
def test_drift_fixture_raises_schema_drift(make_ctx: Run, tmp_path: Path, mutate: Any) -> None:
    adapter, ctx, _ = make_ctx(_drift_fixture(tmp_path, mutate))
    cinema = cinema_config("cinepax-packages-mall")
    with pytest.raises(SchemaDriftError):
        adapter.list_movies(ctx, cinema)
        adapter.list_showtimes(ctx, cinema)


def test_drift_saves_a_cleaned_debug_payload(make_ctx: Run, tmp_path: Path) -> None:
    adapter, ctx, _ = make_ctx(_drift_fixture(tmp_path, _drop("screens")))
    with pytest.raises(SchemaDriftError):
        adapter.list_movies(ctx, cinema_config("cinepax-packages-mall"))
    saved = list((tmp_path / "debug" / "cinepax-packages-mall").iterdir())
    assert [p.name for p in saved] == ["api-movies.json"]


def test_wrong_branch_in_payload_is_drift(make_ctx: Run, tmp_path: Path) -> None:
    def other_branch(data: Any) -> Any:
        data[0]["cinemaId"] = "0000000099"
        return data

    adapter, ctx, _ = make_ctx(_drift_fixture(tmp_path, other_branch))
    with pytest.raises(SchemaDriftError, match="belongs to branch"):
        adapter.list_movies(ctx, cinema_config("cinepax-packages-mall"))


# --- behaviour --------------------------------------------------------------------------


def test_payload_is_fetched_once_per_run(make_ctx: Run) -> None:
    adapter, ctx, transport = make_ctx(FIXTURES / "cinepax-packages-mall" / CAPTURED)
    cinema = cinema_config("cinepax-packages-mall")
    adapter.list_movies(ctx, cinema)
    adapter.list_showtimes(ctx, cinema)
    assert sum("/api/movies" in u for u in transport.requested) == 1


def test_days_window(make_ctx: Run) -> None:
    adapter, ctx, _ = make_ctx(FIXTURES / "cinepax-packages-mall" / CAPTURED)
    shows = adapter.list_showtimes(ctx, cinema_config("cinepax-packages-mall"), days=1)
    assert shows and all(s.starts_at.date() <= date(2026, 11, 26) for s in shows)


def test_booking_url_from_template(make_ctx: Run) -> None:
    adapter, ctx, _ = make_ctx(FIXTURES / "cinepax-packages-mall" / CAPTURED)
    cinema = cinema_config(
        "cinepax-packages-mall",
        booking_url_template="https://web.cinepax.com/booking/{branch}/{sessionId}",
    )
    show = adapter.list_showtimes(ctx, cinema)[0]
    assert show.booking_url == f"https://web.cinepax.com/booking/0000000014/{show.external_id}"


def test_booking_url_values_are_url_encoded() -> None:
    url = build_booking_url(
        "https://x/b?movie={movieTitle}&cinema={cinemaName}",
        movieTitle="18+Belkis (Turkish Urdu Dubbed)",
        cinemaName="CINEPAX PACKAGES MALL",
    )
    assert (
        url
        == "https://x/b?movie=18%2BBelkis+%28Turkish+Urdu+Dubbed%29&cinema=CINEPAX+PACKAGES+MALL"
    )


def test_build_booking_url_rules() -> None:
    assert build_booking_url(None, branch="1") is None
    assert build_booking_url("https://x/{sessionId}", sessionId=None) is None
    with pytest.raises(ValueError, match="placeholders"):
        build_booking_url("https://x/{seat}", branch="1")


def test_registry_builds_the_cinepax_adapter() -> None:
    assert registry.spec("cinepax").implemented
    assert isinstance(registry.get_adapter("cinepax"), CinepaxAdapter)


# --- P1-04 acceptance on a real cinema ----------------------------------------------------


def test_cli_offline_dry_run_on_the_first_cinema(capsys: pytest.CaptureFixture[str]) -> None:
    fixture = FIXTURES / "cinepax-packages-mall" / CAPTURED
    code = main(
        [
            "run",
            "--job",
            "full",
            "--cinema",
            "cinepax-packages-mall",
            "--dry-run",
            "--offline",
            str(fixture),
        ]
    )
    assert code == 0
    assert "[ok] cinepax-packages-mall: 8 movies" in capsys.readouterr().out
