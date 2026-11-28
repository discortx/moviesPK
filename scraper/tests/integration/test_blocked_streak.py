"""P2-07: a cinema blocked 3 full runs in a row gets an alert that says to drop it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from moviespk_scraper.core.config import load_config
from moviespk_scraper.core.logging import get_logger
from moviespk_scraper.db import repositories as repo
from moviespk_scraper.db.client import DB
from moviespk_scraper.runner import BLOCKED_DROP_AFTER, CinemaResult, Services, _report_health
from moviespk_scraper.services.alerts import Alert

pytestmark = pytest.mark.integration

CINEMA = "cinepax-packages-mall"
T0 = datetime(2026, 11, 28, 10, 7, tzinfo=UTC)


class Recorder:
    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def raise_alert(self, alert: Alert, now: datetime) -> None:
        self.alerts.append(alert)

    def resolve(self, cinema_id: str, now: datetime, types: tuple[str, ...] = ()) -> None:
        return None

    def post_digest(self, title: str, body: str) -> None:
        return None

    def close_digests(self, created_before: datetime) -> None:
        return None


def report(db: DB, alerter: Recorder, status: str, hour: int) -> None:
    result = CinemaResult(
        cinema_id=CINEMA,
        status=status,  # type: ignore[arg-type]
        error="robots.txt disallows /api/movies" if status == "blocked" else None,
        error_type="RobotsDisallowedError" if status == "blocked" else None,
    )
    now = T0 + timedelta(hours=hour)
    services = Services(db=db, alerter=alerter)
    _report_health(services, "full", load_config().cinema(CINEMA), result, now, now, get_logger())


def test_third_blocked_run_says_drop(db: DB) -> None:
    alerter = Recorder()
    report(db, alerter, "ok", 0)
    for hour in (1, 2, 3):
        report(db, alerter, "blocked", hour)
    states = [a.state for a in alerter.alerts]
    assert states == [
        "blocked:RobotsDisallowedError",
        "blocked:RobotsDisallowedError",
        "blocked:RobotsDisallowedError:drop",  # the state changes → one new comment
    ]
    last = alerter.alerts[-1].summary
    assert f"Blocked {BLOCKED_DROP_AFTER} runs in a row" in last and "Never a proxy" in last


def test_streak_restarts_after_a_good_run(db: DB) -> None:
    alerter = Recorder()
    for hour, status in enumerate(["blocked", "blocked", "ok", "blocked"]):
        report(db, alerter, status, hour)
    assert repo.status_streak(db, CINEMA, "full", "blocked") == 1
    assert not alerter.alerts[-1].state.endswith(":drop")
