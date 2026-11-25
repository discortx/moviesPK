"""P1-11 integration: reconcile and guards through the real ``full`` job (plan §8.4).

Each run replays a (possibly edited) copy of the Packages Mall fixture through
``run_cinema`` with a database, so fetch → validate → guards → upsert → reconcile all run.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from moviespk_scraper.core.config import load_config
from moviespk_scraper.core.http import ScraperHttpClient
from moviespk_scraper.core.offline import FixtureTransport, captured_at
from moviespk_scraper.db.client import DB, DbSettings, connect
from moviespk_scraper.pipeline.match import Matcher
from moviespk_scraper.runner import CinemaResult, Services, run_cinema

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "scraper" / "tests" / "fixtures" / "cinepax-packages-mall" / "2026-11-25"
CINEMA = "cinepax-packages-mall"
Mutate = Callable[[list[dict[str, Any]]], Any]


@pytest.fixture
def db(mongo_uri: str, db_name: str) -> Iterator[DB]:
    client, database = connect(DbSettings(mongo_uri, db_name))
    yield database
    client.close()


@pytest.fixture
def run(db: DB, tmp_path: Path) -> Callable[..., CinemaResult]:
    counter = iter(range(1000))

    def _run(mutate: Mutate | None = None, alerter: Any = None) -> CinemaResult:
        fixture = tmp_path / f"run{next(counter)}"
        shutil.copytree(SOURCE, fixture)
        if mutate is not None:
            movies_file = next(fixture.glob("002-api-movies-*.json"))
            data = json.loads(movies_file.read_text(encoding="utf-8"))
            result = mutate(data)
            movies_file.write_text(json.dumps(data if result is None else result), encoding="utf-8")
        now = captured_at(fixture)
        assert now is not None
        with ScraperHttpClient(
            "t", transport=FixtureTransport(fixture), sleep=lambda _s: None
        ) as http:
            return run_cinema(
                http,
                "full",
                load_config().cinema(CINEMA),
                now=now,
                clock=time.monotonic,
                services=Services(matcher=Matcher(None), db=db, alerter=alerter),
            )

    return _run


def first_session(data: list[dict[str, Any]]) -> dict[str, Any]:
    return next(iter(data[0]["screens"].values()))["sessions"][0]


def drop_first_session(data: list[dict[str, Any]]) -> None:
    next(iter(data[0]["screens"].values()))["sessions"].pop(0)


def the_dropped_show(db: DB) -> dict[str, Any]:
    data = json.loads(next(SOURCE.glob("002-api-movies-*.json")).read_text(encoding="utf-8"))
    local = datetime.fromisoformat(first_session(data)["showtime"])
    starts_at = (local - timedelta(hours=5)).replace(tzinfo=UTC)
    doc = db.showtimes.find_one({"cinemaId": CINEMA, "startsAt": starts_at, "hall": "Screen 4"})
    assert doc is not None
    return doc


def showtimes(db: DB) -> list[dict[str, Any]]:
    return list(db.showtimes.find({}).sort("_id", 1))


# --- acceptance --------------------------------------------------------------------------


def test_one_miss_keeps_active_two_misses_cancel_and_a_return_reactivates(
    db: DB, run: Callable[..., CinemaResult]
) -> None:
    assert run().status == "ok"
    assert the_dropped_show(db)["status"] == "active"

    assert run(drop_first_session).status == "ok"
    show = the_dropped_show(db)
    assert (show["status"], show["missCount"]) == ("active", 1)

    result = run(drop_first_session)
    show = the_dropped_show(db)
    assert (show["status"], show["missCount"]) == ("cancelled", 2)
    assert result.cancelled == 1

    run()  # listed again
    show = the_dropped_show(db)
    assert (show["status"], show["missCount"]) == ("active", 0)


def test_failed_run_changes_no_showtime(db: DB, run: Callable[..., CinemaResult]) -> None:
    run()
    before = showtimes(db)

    def mostly_invalid(data: list[dict[str, Any]]) -> None:
        # 09:00 PKT on the capture day: inside the adapter's window, but more than 2 h
        # before the capture (23:10 PKT), so validation rejects every show.
        for film in data:
            for screen in film["screens"].values():
                for s in screen["sessions"]:
                    s["calendarDate"] = "2026-11-25"
                    s["showtime"] = "2026-11-25T09:00:00"

    result = run(mostly_invalid)
    assert result.status == "failed" and "invalid" in (result.error or "")
    assert showtimes(db) == before


def test_zero_result_run_changes_no_showtime(db: DB, run: Callable[..., CinemaResult]) -> None:
    run()
    before = showtimes(db)
    result = run(lambda data: [])
    assert result.status == "failed" and "zero result" in (result.error or "")
    assert showtimes(db) == before


def test_median_guard_after_warm_up(db: DB, run: Callable[..., CinemaResult]) -> None:
    run()
    before = showtimes(db)
    started = datetime(2026, 11, 20, tzinfo=UTC)
    db.scrape_runs.insert_many(
        [
            {
                "cinemaId": CINEMA,
                "job": "full",
                "status": "ok",
                "startedAt": started + timedelta(hours=i),
                "counts": {"showtimes": 19},
            }
            for i in range(3)
        ]
    )

    def keep_one_film(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return data[:1]  # 6 shows < 50% of 19

    result = run(keep_one_film)
    assert result.status == "failed" and "median" in (result.error or "")
    assert showtimes(db) == before


def test_past_shows_are_left_to_the_ttl(db: DB, run: Callable[..., CinemaResult]) -> None:
    run()
    now = captured_at(SOURCE)
    assert now is not None
    past = {
        "_id": "f" * 40,
        "cinemaId": CINEMA,
        "startsAt": now - timedelta(hours=1),
        "status": "active",
        "missCount": 0,
        "expireAt": now + timedelta(days=6),
    }
    db.showtimes.insert_one(past)
    run()
    run()
    assert db.showtimes.find_one({"_id": past["_id"]}) == past


def test_shows_after_the_latest_seen_start_are_not_judged(
    db: DB, run: Callable[..., CinemaResult]
) -> None:
    run()
    latest = max(d["startsAt"] for d in db.showtimes.find({"cinemaId": CINEMA}))
    beyond = {
        "_id": "e" * 40,
        "cinemaId": CINEMA,
        "startsAt": latest + timedelta(days=2),
        "status": "active",
        "missCount": 0,
    }
    db.showtimes.insert_one(beyond)
    run()
    run()
    assert db.showtimes.find_one({"_id": beyond["_id"]}) == beyond


def test_other_cinemas_are_untouched(db: DB, run: Callable[..., CinemaResult]) -> None:
    now = captured_at(SOURCE)
    assert now is not None
    other = {
        "_id": "d" * 40,
        "cinemaId": "cinepax-ocean-mall",
        "startsAt": now + timedelta(hours=3),
        "status": "active",
        "missCount": 0,
    }
    db.showtimes.insert_one(other)
    run()
    run()
    assert db.showtimes.find_one({"_id": other["_id"]}) == other


# --- P1-12: run health and alerts through the real job ------------------------------------


class RecordingAlerter:
    def __init__(self) -> None:
        self.raised: list[Any] = []
        self.resolved: list[str] = []

    def raise_alert(self, alert: Any, now: datetime) -> None:
        self.raised.append(alert)

    def resolve(self, cinema_id: str, now: datetime) -> None:
        self.resolved.append(cinema_id)


def test_runs_are_recorded_and_alerts_follow_the_status(
    db: DB, run: Callable[..., CinemaResult]
) -> None:
    from moviespk_scraper.pipeline.sync_cinemas import sync_cinemas

    sync_cinemas(db, load_config().cinemas, datetime.now(UTC))
    alerts = RecordingAlerter()

    assert run(alerter=alerts).status == "ok"
    ok_run = db.scrape_runs.find_one({"status": "ok"})
    assert ok_run is not None and ok_run["counts"]["showtimes"] == 19
    health = db.cinemas.find_one({"_id": CINEMA})
    assert health is not None and health["health"]["status"] == "ok"
    assert health["lastScrapedAt"] == health["health"]["lastSuccessAt"]
    assert alerts.resolved == [CINEMA] and alerts.raised == []

    assert run(lambda data: [], alerter=alerts).status == "failed"
    failed_run = db.scrape_runs.find_one({"status": "failed"})
    assert failed_run is not None and failed_run["errors"][0]["type"] == "ZeroResult"
    assert len(alerts.raised) == 1
    raised = alerts.raised[0]
    assert (raised.title, raised.state) == (f"[alert] {CINEMA}: failed", "failed:ZeroResult")
    assert raised.last_success is not None
    health = db.cinemas.find_one({"_id": CINEMA})
    assert health is not None and health["health"]["status"] == "failed"
    assert health["health"]["lastSuccessAt"] == ok_run["finishedAt"]


def test_median_guard_uses_recorded_runs(db: DB, run: Callable[..., CinemaResult]) -> None:
    for _ in range(3):  # warm-up: three ok runs of 19 shows
        assert run().status == "ok"
    result = run(lambda data: data[:1])
    assert result.status == "failed" and result.error_type == "MedianGuard"
