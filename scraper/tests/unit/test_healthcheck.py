"""P2-08: scripts/healthcheck.py against a fake site, API and image Worker."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

from moviespk_scraper.services.alerts import Alert

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "healthcheck.py"
SITE, API, IMG = "https://site.test", "https://api.test", "https://img.test"
KEY = "movies/6b0ad79304040967adf0d459/poster-c5a0d7b2"
NOW = datetime(2026, 11, 28, 20, 17, tzinfo=UTC)  # 2026-11-29 01:17 PKT


@pytest.fixture(scope="module")
def hc() -> ModuleType:
    spec = importlib.util.spec_from_file_location("healthcheck", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["healthcheck"] = module
    spec.loader.exec_module(module)
    return module


Route = Callable[[httpx.Request], httpx.Response]


def healthy() -> dict[str, Route]:
    return {
        f"{SITE}/": lambda r: httpx.Response(200, headers={"content-type": "text/html"}),
        f"{API}/api/v1/health": lambda r: httpx.Response(
            200, json={"data": {"status": "ok", "db": "ok"}}
        ),
        f"{API}/api/v1/movies?city=lahore&date=2026-11-29": lambda r: httpx.Response(
            200,
            json={"data": [{"slug": "a", "poster": None}, {"slug": "b", "poster": {"key": KEY}}]},
        ),
        f"{IMG}/img/{KEY}-w342.webp": lambda r: httpx.Response(
            200, headers={"content-type": "image/webp"}, content=b"RIFF"
        ),
    }


class Recorder:
    def __init__(self) -> None:
        self.raised: list[Alert] = []
        self.resolved: list[tuple[str, tuple[str, ...]]] = []

    def raise_alert(self, alert: Alert, now: datetime) -> None:
        self.raised.append(alert)

    def resolve(self, cinema_id: str, now: datetime, types: tuple[str, ...] = ()) -> None:
        self.resolved.append((cinema_id, types))

    def post_digest(self, title: str, body: str) -> None: ...

    def close_digests(self, created_before: datetime) -> None: ...


def run(
    hc: ModuleType, routes: dict[str, Route], *, flaky: str | None = None
) -> tuple[list, Recorder, list[str]]:
    seen: list[str] = []
    calls: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        calls[url] = calls.get(url, 0) + 1
        if flaky and url == flaky and calls[url] == 1:
            return httpx.Response(503)
        route = routes.get(url)
        return route(request) if route else httpx.Response(404, text="Not Found")

    alerter = Recorder()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results = hc.run_checks(
            client, SITE, API, IMG, alerter=alerter, retry_after_s=120, sleep=lambda _s: None,
            now=lambda: NOW,
        )  # fmt: skip
    return results, alerter, seen


def test_healthy_closes_both_issues(hc: ModuleType) -> None:
    results, alerter, seen = run(hc, healthy())
    assert all(r.ok and not r.skipped for r in results)
    assert alerter.raised == []
    assert alerter.resolved == [("site", ("down",)), ("images", ("down",))]
    assert f"{API}/api/v1/movies?city=lahore&date=2026-11-29" in seen  # PKT date


def test_site_at_a_missing_path_opens_site_down(hc: ModuleType) -> None:
    routes = healthy()
    del routes[f"{SITE}/"]
    _, alerter, _ = run(hc, routes)
    [alert] = alerter.raised
    assert alert.title == "[alert] site: down" and "home page answered 404" in alert.summary
    assert ("images", ("down",)) in alerter.resolved


def test_image_base_at_a_missing_path_opens_images_down(hc: ModuleType) -> None:
    routes = healthy()
    del routes[f"{IMG}/img/{KEY}-w342.webp"]
    _, alerter, _ = run(hc, routes)
    [alert] = alerter.raised
    assert alert.title == "[alert] images: down" and "404" in alert.summary


def test_one_failure_then_success_is_not_an_alert(hc: ModuleType) -> None:
    results, alerter, seen = run(hc, healthy(), flaky=f"{API}/api/v1/health")
    assert alerter.raised == [] and all(r.ok for r in results)
    assert seen.count(f"{API}/api/v1/health") == 2


def test_workers_daily_limit_is_named(hc: ModuleType) -> None:
    routes = healthy()
    routes[f"{IMG}/img/{KEY}-w342.webp"] = lambda r: httpx.Response(
        429, text="error code: 1027", headers={"content-type": "text/plain"}
    )
    _, alerter, _ = run(hc, routes)
    assert "Workers Free daily limit reached" in alerter.raised[0].summary
    assert "resets 00:00 UTC" in alerter.raised[0].summary


def test_unhealthy_database_is_site_down(hc: ModuleType) -> None:
    routes = healthy()
    routes[f"{API}/api/v1/health"] = lambda r: httpx.Response(
        200, json={"data": {"status": "degraded", "db": "down"}}
    )
    _, alerter, _ = run(hc, routes)
    assert alerter.raised[0].title == "[alert] site: down"


def test_no_poster_today_is_skipped_not_failed(hc: ModuleType) -> None:
    routes: dict[str, Any] = healthy()
    routes[f"{API}/api/v1/movies?city=lahore&date=2026-11-29"] = lambda r: httpx.Response(
        200, json={"data": [{"slug": "a", "poster": None}]}
    )
    results, alerter, _ = run(hc, routes)
    images = next(r for r in results if r.name == "images")
    assert images.ok and images.skipped and alerter.raised == []
    assert ("images", ("down",)) not in alerter.resolved  # nothing concluded


def test_needs_urls(hc: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SITE_URL", raising=False)
    assert hc.main([]) == 2
