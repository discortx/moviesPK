"""P2-03 integration: the canary's database checks against MongoDB (CI: mongo:7 service)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from moviespk_scraper.core.config import load_config
from moviespk_scraper.db import repositories as repo
from moviespk_scraper.db.client import DB, DbSettings, connect
from moviespk_scraper.pipeline import canary
from moviespk_scraper.services.alerts import Alert

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 29, 4, 23, tzinfo=UTC)
CINEPAX = "cinepax-packages-mall"


@pytest.fixture
def db(mongo_uri: str, db_name: str) -> Iterator[DB]:
    client, database = connect(DbSettings(mongo_uri, db_name))
    yield database
    client.close()


def add_run(db: DB, *, hours_ago: float, showtimes: int, status: str = "ok", job: str = "full"):
    finished = NOW - timedelta(hours=hours_ago)
    db[repo.SCRAPE_RUNS].insert_one(
        {
            "job": job,
            "cinemaId": CINEPAX,
            "startedAt": finished - timedelta(minutes=1),
            "finishedAt": finished,
            "status": status,
            "counts": {"showtimes": showtimes},
        }
    )


class Collector:
    def __init__(self) -> None:
        self.found: dict[tuple[str, tuple[str, ...]], list[Alert]] = {}
        self.digests: list[tuple[str, str]] = []
        self.closed_before: datetime | None = None

    def emit(self, subject: str, types: tuple[str, ...], found: Sequence[Alert]) -> None:
        self.found[(subject, types)] = list(found)

    # alerter part (digests only)
    def raise_alert(self, alert: Alert, now: datetime) -> None: ...

    def resolve(self, cinema_id: str, now: datetime, types: tuple[str, ...] = ()) -> None: ...

    def post_digest(self, title: str, body: str) -> None:
        self.digests.append((title, body))

    def close_digests(self, created_before: datetime) -> None:
        self.closed_before = created_before


def run_checks(db: DB) -> tuple[Collector, canary.CanaryReport]:
    c = Collector()
    report = canary.CanaryReport()
    cinema = load_config().cinema(CINEPAX)
    canary._database_checks(db, [cinema], NOW, report, c.emit, c)
    return c, report


def types_for(c: Collector, subject: str, types: tuple[str, ...]) -> list[str]:
    return [a.type for a in c.found[(subject, types)]]


def test_fresh_and_steady_cinema_raises_nothing(db: DB) -> None:
    for i in range(8):
        add_run(db, hours_ago=1 + i, showtimes=20)
    c, report = run_checks(db)
    assert types_for(c, CINEPAX, canary.DB_CINEMA_TYPES) == []
    assert types_for(c, "atlas", ("storage",)) == []
    assert report.storage_bytes is not None and report.storage_bytes > 0


def test_low_latest_run_after_warm_up_and_staleness(db: DB) -> None:
    for i in range(7):
        add_run(db, hours_ago=20 + i, showtimes=20)
    add_run(db, hours_ago=19, showtimes=5)  # run 8: low, and 19 h ago (stale)
    add_run(db, hours_ago=1, showtimes=0, status="failed")  # failures count for neither
    c, _ = run_checks(db)
    assert types_for(c, CINEPAX, canary.DB_CINEMA_TYPES) == ["low-results", "stale"]


def test_seven_runs_are_still_warm_up(db: DB) -> None:
    for i in range(6):
        add_run(db, hours_ago=2 + i, showtimes=20)
    add_run(db, hours_ago=1, showtimes=5)
    c, _ = run_checks(db)
    assert types_for(c, CINEPAX, canary.DB_CINEMA_TYPES) == []


def test_last_success_reads_only_successful_runs_of_the_job(db: DB) -> None:
    add_run(db, hours_ago=1, showtimes=0, status="failed")
    add_run(db, hours_ago=3, showtimes=10, status="partial")
    add_run(db, hours_ago=2, showtimes=10, job="seats")
    assert repo.last_success_at(db, CINEPAX, "full") == NOW - timedelta(hours=3)
    assert repo.last_success_at(db, "nowhere", "full") is None


def test_digest_lists_new_unresolved_titles_only(db: DB) -> None:
    db[repo.MOVIES].insert_many(
        [
            {
                "title": "Belkis",
                "slug": "belkis-2026",
                "matchStatus": "unmatched",
                "createdAt": NOW - timedelta(hours=2),
            },
            {
                "title": "Hope",
                "slug": "hope-2026",
                "matchStatus": "provisional",
                "createdAt": NOW - timedelta(hours=5),
            },
            {
                "title": "Old",
                "slug": "old",
                "matchStatus": "unmatched",
                "createdAt": NOW - timedelta(days=3),
            },
            {
                "title": "Sanjog",
                "slug": "sanjog-2026",
                "matchStatus": "matched",
                "createdAt": NOW - timedelta(hours=1),
            },
        ]
    )
    add_run(db, hours_ago=1, showtimes=10)
    c, report = run_checks(db)
    assert report.digest_titles == 2
    [(title, body)] = c.digests
    assert title == "[digest] unmatched titles 2026-11-29"
    assert "Belkis" in body and "Hope" in body and "Old" not in body and "Sanjog" not in body
    assert c.closed_before == NOW - timedelta(days=7)
