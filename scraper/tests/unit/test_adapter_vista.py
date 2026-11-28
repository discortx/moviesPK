"""P2-01: the Vista adapter (Universal, CineStar) against the captured fixtures (plan §10.1).

Snapshots live in ``tests/snapshots/vista/``. After an intended parser change, regenerate
them with ``UPDATE_SNAPSHOTS=1 pytest tests/unit/test_adapter_vista.py`` and review the diff.
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
from moviespk_scraper.adapters.base import RunContext
from moviespk_scraper.adapters.vista import VistaAdapter, _classify
from moviespk_scraper.cli import main
from moviespk_scraper.core.circuit_breaker import CinemaBudget
from moviespk_scraper.core.config import CinemaConfig, load_config
from moviespk_scraper.core.errors import SchemaDriftError
from moviespk_scraper.core.http import ScraperHttpClient
from moviespk_scraper.core.logging import get_logger
from moviespk_scraper.core.offline import FixtureTransport

TESTS = Path(__file__).resolve().parents[1]
FIXTURES = TESTS / "fixtures"
SNAPSHOTS = TESTS / "snapshots" / "vista"
CAPTURED = "2026-11-28"
#: The capture time (2026-11-28 18:08 PKT): the reference "now" for the 7-day window.
NOW = datetime(2026, 11, 28, 13, 8, 28, tzinfo=UTC)
UNIVERSAL = "universal-emporium-mall-lahore"
CINESTAR = "cinestar-township-lahore"
CINEMAS = [UNIVERSAL, CINESTAR]

Run = Callable[..., tuple[VistaAdapter, RunContext, FixtureTransport]]


def cinema_config(cinema_id: str, **changes: Any) -> CinemaConfig:
    base = load_config().cinema(cinema_id)
    return base.model_copy(update=changes) if changes else base


@pytest.fixture
def make_ctx(tmp_path: Path) -> Iterator[Run]:
    clients: list[ScraperHttpClient] = []

    def make(
        fixture_dir: Path, *, now: datetime = NOW
    ) -> tuple[VistaAdapter, RunContext, FixtureTransport]:
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
        return VistaAdapter(), ctx, transport

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


def _snapshot(adapter: VistaAdapter, ctx: RunContext, cinema: CinemaConfig) -> dict[str, Any]:
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


@pytest.mark.parametrize(("cinema_id", "movies", "shows"), [(UNIVERSAL, 23, 97), (CINESTAR, 9, 20)])
def test_counts_and_shape(make_ctx: Run, cinema_id: str, movies: int, shows: int) -> None:
    adapter, ctx, _ = make_ctx(FIXTURES / cinema_id / CAPTURED)
    cinema = cinema_config(cinema_id)
    listed = adapter.list_movies(ctx, cinema)
    showtimes = adapter.list_showtimes(ctx, cinema)
    assert len(listed) == movies and len(showtimes) == shows
    assert all(s.hall and s.external_id and s.booking_url for s in showtimes)
    assert all(s.starts_at.tzinfo is None for s in showtimes)  # naive PKT
    assert {s.movie_local_key for s in showtimes} == {m.local_key for m in listed}
    assert all(m.rating for m in listed)


def test_films_without_sessions_are_skipped(make_ctx: Run) -> None:
    """The page lists 42 films (19 coming soon); only the 23 with sessions count."""
    adapter, ctx, _ = make_ctx(FIXTURES / UNIVERSAL / CAPTURED)
    assert len(adapter.list_movies(ctx, cinema_config(UNIVERSAL))) == 23


# --- after-midnight shows keep their real calendar date ----------------------------------


def test_after_midnight_show_uses_the_datetime_not_the_heading(make_ctx: Run) -> None:
    """Sanjog at 00:00 is listed under "Saturday, 28 November 2026"; it starts on
    2026-11-29 00:00 PKT."""
    adapter, ctx, _ = make_ctx(FIXTURES / UNIVERSAL / CAPTURED)
    shows = adapter.list_showtimes(ctx, cinema_config(UNIVERSAL))
    sanjog = [s.starts_at for s in shows if s.movie_title == "Sanjog" and s.starts_at.hour == 0]
    assert datetime(2026, 11, 29, 0, 0) in sanjog


# --- icon alts -------------------------------------------------------------------------


def test_icon_alts_split_into_hall_format_and_language() -> None:
    assert _classify(["Screen-9"]) == ("Screen-9", None, None)
    assert _classify(["Gold", "3DX"]) == ("Gold", "3D", None)
    assert _classify(["Diamond10", "Japanese"]) == ("Diamond10", None, "Japanese")
    assert _classify(["Urdu", "SUPER ULTRA"]) == ("SUPER ULTRA", None, "Urdu")
    assert _classify([]) == (None, None, None)


def test_universal_attributes_reach_the_showtimes(make_ctx: Run) -> None:
    adapter, ctx, _ = make_ctx(FIXTURES / UNIVERSAL / CAPTURED)
    shows = adapter.list_showtimes(ctx, cinema_config(UNIVERSAL))
    assert sum(s.format_text == "3D" for s in shows) == 1
    assert sum(s.language_text == "Urdu" for s in shows) == 5
    assert sum(s.language_text == "Japanese" for s in shows) == 11


# --- acceptance: a drift fixture raises SchemaDriftError ------------------------------


def _drift_fixture(tmp_path: Path, cinema_id: str, old: str, new: str) -> Path:
    src = FIXTURES / cinema_id / CAPTURED
    dst = tmp_path / "drift"
    shutil.copytree(src, dst)
    page = next(dst.glob("003-browsing-cinemas-details-*.html"))
    html = page.read_text(encoding="utf-8")
    assert old in html, old
    page.write_text(html.replace(old, new), encoding="utf-8")
    return dst


DRIFTS = {
    "no-film-list": ('class="film-list"', 'class="films"'),
    "no-film-item": ('class="film-item', 'class="film-card'),
    "no-title": ('class="film-title"', 'class="film-name"'),
    "no-session-id": ("txtSessionId=", "sessionRef="),
    "no-datetime": ("<time datetime=", "<time data-at="),
    "bad-heading": ("Sunday, 29 November 2026", "29/11/2026"),
    "skewed-date": ('datetime="2026-11-29T', 'datetime="2026-12-03T'),
    "other-cinema": ("cinemacode=8888", "cinemacode=9999"),
    "tz-datetime": ('datetime="2026-11-29T12:00:00"', 'datetime="2026-11-29T12:00:00+05:00"'),
}


@pytest.mark.parametrize("name", list(DRIFTS))
def test_drift_fixture_raises_schema_drift(make_ctx: Run, tmp_path: Path, name: str) -> None:
    old, new = DRIFTS[name]
    adapter, ctx, _ = make_ctx(_drift_fixture(tmp_path, UNIVERSAL, old, new))
    with pytest.raises(SchemaDriftError):
        adapter.list_movies(ctx, cinema_config(UNIVERSAL))


def test_drift_saves_a_cleaned_debug_payload(make_ctx: Run, tmp_path: Path) -> None:
    adapter, ctx, _ = make_ctx(_drift_fixture(tmp_path, UNIVERSAL, *DRIFTS["no-film-list"]))
    with pytest.raises(SchemaDriftError):
        adapter.list_movies(ctx, cinema_config(UNIVERSAL))
    saved = list((tmp_path / "debug" / UNIVERSAL).iterdir())
    assert [p.name for p in saved] == ["cinema-details.html"]


# --- behaviour --------------------------------------------------------------------------


def test_page_is_fetched_once_per_run(make_ctx: Run) -> None:
    adapter, ctx, transport = make_ctx(FIXTURES / CINESTAR / CAPTURED)
    cinema = cinema_config(CINESTAR)
    adapter.list_movies(ctx, cinema)
    adapter.list_showtimes(ctx, cinema)
    assert sum("/Cinemas/Details/" in u for u in transport.requested) == 1


def test_days_window(make_ctx: Run) -> None:
    adapter, ctx, _ = make_ctx(FIXTURES / UNIVERSAL / CAPTURED)
    shows = adapter.list_showtimes(ctx, cinema_config(UNIVERSAL), days=0)
    assert shows and all(s.starts_at.date() == date(2026, 11, 28) for s in shows)


def test_booking_url_comes_from_the_template(make_ctx: Run) -> None:
    adapter, ctx, _ = make_ctx(FIXTURES / CINESTAR / CAPTURED)
    show = adapter.list_showtimes(ctx, cinema_config(CINESTAR))[0]
    assert show.booking_url == (
        "https://cinestar.pk/Ticketing/visSelectTickets.aspx"
        f"?cinemacode=0005&txtSessionId={show.external_id}"
    )


def test_no_template_means_no_booking_url(make_ctx: Run) -> None:
    adapter, ctx, _ = make_ctx(FIXTURES / CINESTAR / CAPTURED)
    shows = adapter.list_showtimes(ctx, cinema_config(CINESTAR, booking_url_template=None))
    assert shows and all(s.booking_url is None for s in shows)


def test_registry_builds_the_vista_adapter() -> None:
    assert registry.spec("vista").implemented
    assert isinstance(registry.get_adapter("vista"), VistaAdapter)


@pytest.mark.parametrize(("cinema_id", "movies"), [(UNIVERSAL, 23), (CINESTAR, 9)])
def test_cli_offline_dry_run(
    capsys: pytest.CaptureFixture[str], cinema_id: str, movies: int
) -> None:
    fixture = FIXTURES / cinema_id / CAPTURED
    code = main(
        ["run", "--job", "full", "--cinema", cinema_id, "--dry-run", "--offline", str(fixture)]
    )
    assert code == 0
    assert f"[ok] {cinema_id}: {movies} movies" in capsys.readouterr().out
