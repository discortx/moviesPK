"""P1-04: the CLI and the job runner, end to end against offline fixtures."""

from __future__ import annotations

import copy
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from moviespk_scraper.adapters import registry
from moviespk_scraper.adapters.base import (
    RawMovie,
    RawSeats,
    RawShowtime,
    RunContext,
    ShowRef,
)
from moviespk_scraper.cli import main
from moviespk_scraper.core.config import CinemaConfig
from moviespk_scraper.core.errors import SchemaDriftError
from moviespk_scraper.core.http import ScraperHttpClient
from moviespk_scraper.runner import MAX_PARALLEL_CINEMAS, run_job

BASE = "https://fake.example"
CITY = {"slug": "lahore", "name": "Lahore", "center": [74.3587, 31.5204], "default_radius_km": 25}
CINEMA: dict[str, Any] = {
    "id": "fake-mall",
    "chain": "fake",
    "adapter": "fake",
    "branch": "7",
    "fetch_mode": "json",
    "base_url": BASE,
    "name": "Fake Mall",
    "address": "Main Boulevard, Lahore",
    "city": "lahore",
    "location": [74.35, 31.47],
    "enabled": False,
    "robots_policy": "respect",
    "evidence": {
        "checked_at": "2026-11-25",
        "robots_sha256": None,
        "terms_url": None,
        "terms_sha256": None,
        "endpoints": [{"path": "/api/shows", "allowed": True}],
    },
}
#: Offline runs use the capture time as "now" (2026-11-26 10:00 PKT).
CAPTURED_AT = "2026-11-26T05:00:00Z"
SHOWS = [
    {"title": "Movie A", "start": "2026-11-26T15:30:00", "hall": "Screen 1"},
    {"title": "Movie B", "start": "2026-11-26T18:00:00", "hall": "Screen 2"},
    {"title": "Movie A", "start": "2026-11-26T21:00:00", "hall": "Screen 1"},
]


class FakeAdapter:
    adapter_id = "fake"
    fetch_mode = "json"

    def list_showtimes(
        self, ctx: RunContext, cinema: CinemaConfig, days: int = 7
    ) -> list[RawShowtime]:
        resp = ctx.fetch(cinema, f"{cinema.base_url}/api/shows?branch={cinema.branch}")
        data = resp.json()
        if not isinstance(data, list):
            raise SchemaDriftError("expected a list of shows")
        return [
            RawShowtime(
                movie_title=s["title"], starts_at=datetime.fromisoformat(s["start"]), hall=s["hall"]
            )
            for s in data
        ]

    def list_movies(self, ctx: RunContext, cinema: CinemaConfig) -> list[RawMovie]:
        return []

    def fetch_seat_status(
        self, ctx: RunContext, cinema: CinemaConfig, show: ShowRef
    ) -> RawSeats | None:
        return None


@pytest.fixture(autouse=True)
def fake_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        registry._ADAPTERS, "fake", registry.AdapterSpec("fake", "json", FakeAdapter)
    )


@pytest.fixture(autouse=True)
def no_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCRAPER_USER_AGENT", raising=False)


def config_dir(tmp_path: Path, *cinemas: dict[str, Any]) -> Path:
    d = tmp_path / "config"
    d.mkdir(exist_ok=True)
    (d / "cities.yml").write_text(yaml.safe_dump([CITY]), encoding="utf-8")
    (d / "cinemas.yml").write_text(yaml.safe_dump(list(cinemas or [CINEMA])), encoding="utf-8")
    return d


def fixtures(tmp_path: Path, shows: Any = SHOWS, robots: str | None = None) -> Path:
    d = tmp_path / "fixtures" / "fake-mall" / "2026-11-26"
    d.mkdir(parents=True)
    (d / "001-shows.json").write_text(json.dumps(shows), encoding="utf-8")
    responses = [
        {
            "url": f"{BASE}/api/shows?branch=7",
            "status": 200,
            "headers": {"content-type": "application/json"},
            "body": "001-shows.json",
        }
    ]
    if robots is not None:
        (d / "000-robots.txt").write_text(robots, encoding="utf-8")
        responses.append(
            {"url": f"{BASE}/robots.txt", "status": 200, "headers": {}, "body": "000-robots.txt"}
        )
    manifest = {"captured_at": CAPTURED_AT, "responses": responses}
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


def run(tmp_path: Path, fixture_dir: Path, *extra: str, cinema: str = "fake-mall") -> int:
    return main(
        [
            "run",
            "--job",
            "full",
            "--cinema",
            cinema,
            "--dry-run",
            "--offline",
            str(fixture_dir),
            "--config-dir",
            str(config_dir(tmp_path)),
            *extra,
        ]
    )


# --- acceptance: run --job full --cinema <id> --dry-run --offline <fixtures> exits 0 ---


def test_offline_dry_run_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(tmp_path, fixtures(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "full dry run" in out
    assert "[ok] fake-mall: 0 movies, 3 valid showtimes, 0 invalid" in out
    assert "2026-11-26 15:30 PKT  Movie A · Screen 1 · 2D · other" in out
    assert "1 ok, 0 not ok" in out


def test_samples_are_capped_at_five(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shows = [
        {"title": f"M{i}", "start": f"2026-11-26T{10 + i:02d}:00:00", "hall": "1"} for i in range(8)
    ]
    assert run(tmp_path, fixtures(tmp_path, shows=shows)) == 0
    out = capsys.readouterr().out
    assert "8 valid showtimes" in out and "M4" in out and "M5" not in out


def test_21_percent_invalid_fixture_fails_the_cinema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Plan P1-08: 21 of 100 shows already started long before the capture → failed."""
    shows = [
        {
            "title": f"M{i}",
            "start": "2026-11-25T09:00:00" if i < 21 else "2026-11-26T20:00:00",
            "hall": str(i),
        }
        for i in range(100)
    ]
    assert run(tmp_path, fixtures(tmp_path, shows=shows)) == 1
    out = capsys.readouterr().out
    assert "[failed] fake-mall: 0 movies, 79 valid showtimes, 21 invalid" in out
    assert "21 of 100 showtimes invalid (21% > 20%)" in out


def test_drift_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(tmp_path, fixtures(tmp_path, shows={"unexpected": True})) == 1
    out = capsys.readouterr().out
    assert "[drift] fake-mall" in out and "SchemaDriftError" in out


def test_robots_disallow_in_fixtures_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, fixtures(tmp_path, robots="User-agent: *\nDisallow: /api/\n")) == 1
    assert "[blocked] fake-mall" in capsys.readouterr().out


def test_missing_fixture_fails_without_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = fixtures(tmp_path)
    (d / "manifest.json").write_text(json.dumps({"responses": []}), encoding="utf-8")
    assert run(tmp_path, d) == 1
    assert "FixtureMissingError" in capsys.readouterr().out


# --- exit code 2 -----------------------------------------------------------------------


def test_config_error_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = copy.deepcopy(CINEMA)
    bad["robots_policy"] = "ignore"
    cfg = config_dir(tmp_path, bad)
    code = main(["run", "--job", "full", "--dry-run", "--config-dir", str(cfg)])
    assert code == 2 and "ADR-0001" in capsys.readouterr().err


def test_unknown_cinema_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(tmp_path, fixtures(tmp_path), cinema="nowhere") == 2
    assert "unknown cinema" in capsys.readouterr().err


@pytest.mark.parametrize("job", ["seats", "canary", "export"])
def test_unimplemented_jobs_exit_2(job: str) -> None:
    assert main(["run", "--job", job, "--dry-run"]) == 2


def test_a_writing_run_needs_database_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("MONGODB_URI_SCRAPER", raising=False)
    monkeypatch.delenv("MONGODB_DB", raising=False)
    monkeypatch.setenv("SCRAPER_USER_AGENT", "MoviesPKBot/1.0 (+test)")
    cfg = config_dir(tmp_path, {**CINEMA, "enabled": True})
    assert main(["run", "--job", "full", "--cinema", "fake-mall", "--config-dir", str(cfg)]) == 2
    assert "MONGODB_URI_SCRAPER" in capsys.readouterr().err


def test_offline_runs_never_write(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "run",
            "--job",
            "full",
            "--cinema",
            "fake-mall",
            "--offline",
            str(fixtures(tmp_path)),
            "--config-dir",
            str(config_dir(tmp_path, {**CINEMA, "enabled": True})),
        ]
    )
    assert code == 2 and "always --dry-run" in capsys.readouterr().err


def test_online_run_needs_user_agent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = config_dir(tmp_path)
    code = main(
        ["run", "--job", "full", "--cinema", "fake-mall", "--dry-run", "--config-dir", str(cfg)]
    )
    assert code == 2 and "SCRAPER_USER_AGENT" in capsys.readouterr().err


def test_bad_fixture_dir_exits_2(tmp_path: Path) -> None:
    assert run(tmp_path, tmp_path / "missing") == 2


def test_no_enabled_cinemas_is_a_no_op(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = config_dir(tmp_path)
    assert main(["run", "--job", "full", "--dry-run", "--config-dir", str(cfg)]) == 0
    assert "no enabled cinemas" in capsys.readouterr().out


# --- runner --------------------------------------------------------------------------------


class SlowAdapter(FakeAdapter):
    def __init__(self) -> None:
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()

    def list_showtimes(
        self, ctx: RunContext, cinema: CinemaConfig, days: int = 7
    ) -> list[RawShowtime]:
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.05)
        with self.lock:
            self.active -= 1
        if cinema.id == "c-2":
            raise RuntimeError("boom")
        return []


def test_at_most_three_cinemas_in_parallel_and_failures_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slow = SlowAdapter()
    monkeypatch.setitem(
        registry._ADAPTERS, "fake", registry.AdapterSpec("fake", "json", lambda: slow)
    )
    cinemas = [CinemaConfig.model_validate({**CINEMA, "id": f"c-{i}"}) for i in range(7)]
    with ScraperHttpClient("MoviesPKBot/1.0 (+test)") as http:
        report = run_job(http, "full", cinemas, dry_run=True, clock=time.monotonic)
    assert slow.peak == MAX_PARALLEL_CINEMAS
    statuses = {r.cinema_id: r.status for r in report.results}
    assert statuses["c-2"] == "failed"
    assert sum(1 for s in statuses.values() if s == "ok") == 6
    assert report.exit_code == 1
