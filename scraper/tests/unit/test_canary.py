"""P2-03: canary rules (plan §10.5, §18.1).

Acceptance: a test per rule, including the warm-up (runs 1-7 no count alert, run 8 alerts);
a mocked robots change fires once and is deduplicated; a mocked terms change fires once.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from moviespk_scraper.cli import main
from moviespk_scraper.core.config import CinemaConfig, load_config
from moviespk_scraper.core.evidence import terms_sha256
from moviespk_scraper.core.http import ScraperHttpClient
from moviespk_scraper.core.logging import get_logger
from moviespk_scraper.pipeline import canary
from moviespk_scraper.pipeline.canary import (
    ATLAS_LIMIT_BYTES,
    count_alert,
    evidence_alerts,
    probe,
    run_canary,
    stale_alert,
    storage_alert,
)
from moviespk_scraper.services.alerts import Alert, GitHubAlerter

from .test_alerts import REPO, FakeGitHub

NOW = datetime(2026, 11, 29, 4, 23, tzinfo=UTC)
CINEPAX = "cinepax-packages-mall"
TERMS_URL = "https://web.cinepax.com/api/cms/pages/terms"
TERMS = "<html><body><h1>Terms</h1><p>Tickets are non-refundable.</p></body></html>"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def cinema(cinema_id: str = CINEPAX, **evidence: Any) -> CinemaConfig:
    base = load_config().cinema(cinema_id)
    ev = base.evidence.model_copy(update={"terms_sha256": terms_sha256(TERMS), **evidence})
    return base.model_copy(update={"evidence": ev})


Site = dict[str, tuple[int, str]]


@pytest.fixture
def site() -> Site:
    """path → (status, body) for web.cinepax.com; robots.txt missing by default."""
    return {
        "/robots.txt": (404, ""),
        "/api/cms/pages/terms": (200, TERMS),
        "/api/movies": (200, "[]"),
    }


@pytest.fixture
def make_http(site: Site) -> Iterator[Callable[[], ScraperHttpClient]]:
    clients: list[ScraperHttpClient] = []
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        status, body = site.get(request.url.path, (404, ""))
        return httpx.Response(status, text=body)

    def make() -> ScraperHttpClient:
        http = ScraperHttpClient(
            "MoviesPKBot/1.0 (+test)",
            transport=httpx.MockTransport(handler),
            sleep=lambda _s: None,
        )
        clients.append(http)
        return http

    make.requested = requested  # type: ignore[attr-defined]
    yield make
    for http in clients:
        http.close()


class RecordingAlerter:
    def __init__(self) -> None:
        self.raised: list[Alert] = []
        self.resolved: list[tuple[str, tuple[str, ...]]] = []
        self.digests: list[str] = []

    def raise_alert(self, alert: Alert, now: datetime) -> None:
        self.raised.append(alert)

    def resolve(self, cinema_id: str, now: datetime, types: tuple[str, ...] = ()) -> None:
        self.resolved.append((cinema_id, types))

    def post_digest(self, title: str, body: str) -> None:
        self.digests.append(title)

    def close_digests(self, created_before: datetime) -> None:
        return None


def check(make_http: Callable[[], ScraperHttpClient], c: CinemaConfig) -> list[Alert]:
    with make_http() as http:
        alerts, _notes = evidence_alerts(http, c, get_logger(), {})
    return alerts


# --- 1. robots and terms ---------------------------------------------------------------


def test_unchanged_evidence_raises_nothing(make_http: Any) -> None:
    assert check(make_http, cinema()) == []


def test_newly_disallowed_path_alerts_robots(make_http: Any, site: Site) -> None:
    site["/robots.txt"] = (200, "User-agent: *\nDisallow: /api/movies\n")
    [alert] = check(make_http, cinema())
    assert alert.type == "robots" and alert.cinema_id == CINEPAX
    assert "/api/movies" in alert.summary and alert.state == "robots:/api/movies"
    assert alert.repeat_after is None


def test_robots_hash_change_without_verdict_change_is_logged_only(
    make_http: Any, site: Site
) -> None:
    site["/robots.txt"] = (200, "User-agent: *\nDisallow: /admin\n")
    with make_http() as http:
        alerts, notes = evidence_alerts(http, cinema(), get_logger(), {})
    assert alerts == [] and any("verdicts unchanged" in n for n in notes)


def test_unreachable_robots_is_a_note_not_an_alert(make_http: Any, site: Site) -> None:
    site["/robots.txt"] = (503, "")
    with make_http() as http:
        alerts, notes = evidence_alerts(http, cinema(), get_logger(), {})
    assert alerts == [] and any("unreachable" in n for n in notes)


def test_changed_terms_alert(make_http: Any, site: Site) -> None:
    site["/api/cms/pages/terms"] = (200, TERMS.replace("non-refundable", "refundable"))
    [alert] = check(make_http, cinema())
    assert alert.type == "terms-changed" and alert.repeat_after is None


def test_terms_markup_change_is_not_a_terms_change(make_http: Any, site: Site) -> None:
    site["/api/cms/pages/terms"] = (200, TERMS.replace("<p>", "<p class='x'>  "))
    assert check(make_http, cinema()) == []


def test_terms_page_fetched_once_for_cinemas_sharing_it(make_http: Any) -> None:
    cache: dict[str, str | None] = {}
    with make_http() as http:
        for cid in ("cinepax-packages-mall", "cinepax-ocean-mall"):
            evidence_alerts(http, cinema(cid), get_logger(), cache)
    assert make_http.requested.count("/api/cms/pages/terms") == 1


@pytest.fixture
def github() -> Iterator[FakeGitHub]:
    fake = FakeGitHub()
    with respx.mock(assert_all_called=False) as router:
        fake.install(router)
        yield fake


@pytest.mark.parametrize(
    "change",
    [
        ("/robots.txt", (200, "User-agent: *\nDisallow: /api/\n")),
        ("/api/cms/pages/terms", (200, "<p>New terms</p>")),
    ],
    ids=["robots", "terms"],
)
def test_mocked_change_fires_once_and_is_deduplicated(
    make_http: Any, site: Site, github: FakeGitHub, change: tuple[str, tuple[int, str]]
) -> None:
    site[change[0]] = change[1]
    for day in range(3):  # three daily canaries
        alerter = GitHubAlerter("token", REPO)
        with make_http() as http:
            run_canary(
                http,
                [cinema()],
                db=None,
                alerter=alerter,
                now=NOW + timedelta(days=day),
                log=get_logger(),
            )
        alerter.close()
    titles = [i["title"] for i in github.issues.values()]
    kind = "robots" if change[0] == "/robots.txt" else "terms-changed"
    assert titles == [f"[alert] {CINEPAX}: {kind}"]
    assert github.comments[1] == []


def test_cleared_evidence_closes_the_issue(make_http: Any, site: Site) -> None:
    alerter = RecordingAlerter()
    with make_http() as http:
        run_canary(http, [cinema()], db=None, alerter=alerter, now=NOW, log=get_logger())
    assert (CINEPAX, ("robots", "terms-changed")) in alerter.resolved


# --- 2. structural probe -----------------------------------------------------------------


def test_probe_parses_the_fixture_page() -> None:
    from moviespk_scraper.core.offline import FixtureTransport, captured_at

    fixture = FIXTURES / "universal-emporium-mall-lahore" / "2026-11-28"
    c = load_config().cinema("universal-emporium-mall-lahore")
    with ScraperHttpClient("t", transport=FixtureTransport(fixture), sleep=lambda _s: None) as h:
        result = probe(h, "vista", c, captured_at(fixture), get_logger(), None)  # type: ignore[arg-type]
    assert result.ran and result.alert is None and "97 showtimes" in result.note


def test_probe_drift_alerts_and_network_error_concludes_nothing(make_http: Any, site: Site) -> None:
    site["/api/movies"] = (200, '{"films": []}')  # not a list: drift
    with make_http() as http:
        drift = probe(http, "cinepax", cinema(), NOW, get_logger(), None)
    assert drift.alert is not None and drift.alert.cinema_id == "adapter-cinepax"
    assert drift.alert.type == "probe"

    site["/api/movies"] = (503, "")
    with make_http() as http:
        down = probe(http, "cinepax", cinema(), NOW, get_logger(), None)
    assert down.alert is None and not down.ran


def test_probe_targets_first_enabled_cinema_per_adapter() -> None:
    targets = canary.probe_targets(load_config().enabled_cinemas)
    assert {k: v.id for k, v in targets.items()} == {
        "cinepax": "cinepax-packages-mall",
        "vista": "universal-emporium-mall-lahore",
    }


# --- 3. count rule with warm-up ----------------------------------------------------------


def test_count_rule_warm_up_then_alert() -> None:
    history = [100] * 7
    low = 40
    for runs in range(1, 8):  # runs 1-7: the low run is the newest, history too short
        assert count_alert(CINEPAX, [low, *history][:runs]) is None
    alert = count_alert(CINEPAX, [low, *history])  # run 8
    assert alert is not None and alert.type == "low-results" and "median (100)" in alert.summary


def test_count_rule_at_half_the_median_is_fine() -> None:
    assert count_alert(CINEPAX, [50, *[100] * 7]) is None
    assert count_alert(CINEPAX, [49, *[100] * 7]) is not None


# --- 4. staleness -------------------------------------------------------------------------


def test_staleness_thresholds() -> None:
    full = timedelta(hours=18)
    assert stale_alert(CINEPAX, "stale", NOW - timedelta(hours=17), NOW, full) is None
    assert stale_alert(CINEPAX, "stale", NOW - timedelta(hours=18), NOW, full) is None
    late = stale_alert(CINEPAX, "stale", NOW - timedelta(hours=19), NOW, full)
    assert late is not None and "18 h" in late.summary
    never = stale_alert(CINEPAX, "stale", None, NOW, full)
    assert never is not None and "never" in never.summary
    seats = stale_alert(CINEPAX, "stale-seats", NOW - timedelta(hours=7), NOW, timedelta(hours=6))
    assert seats is not None and "seats run" in seats.summary


# --- 5. storage ---------------------------------------------------------------------------


def test_storage_threshold() -> None:
    assert storage_alert(int(ATLAS_LIMIT_BYTES * 0.7)) is None
    alert = storage_alert(int(ATLAS_LIMIT_BYTES * 0.71))
    assert alert is not None and alert.cinema_id == "atlas" and alert.type == "storage"


# --- 7. maintenance hooks and the job -----------------------------------------------------


def test_maintenance_hooks_run_and_failures_fail_the_job(
    make_http: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def ok_hook(ctx: canary.CanaryContext) -> None:
        seen.append("ok")

    def bad_hook(ctx: canary.CanaryContext) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(canary, "MAINTENANCE_HOOKS", [ok_hook, bad_hook])
    with make_http() as http:
        report = run_canary(http, [cinema()], db=None, alerter=None, now=NOW, log=get_logger())
    assert seen == ["ok"]
    assert report.exit_code == 1 and "bad_hook" in report.errors[0]


def test_cli_offline_canary_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    fixture = FIXTURES / "cinestar-township-lahore" / "2026-11-28"
    code = main(
        [
            "run",
            "--job",
            "canary",
            "--cinema",
            "cinestar-township-lahore",
            "--dry-run",
            "--offline",
            str(fixture),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "probe vista (cinestar-township-lahore): 9 movies, 20 showtimes" in out
    assert "canary: 0 alerts, 0 check errors" in out


def test_cli_offline_canary_must_be_a_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    fixture = FIXTURES / "cinestar-township-lahore" / "2026-11-28"
    code = main(["run", "--job", "canary", "--offline", str(fixture)])
    assert code == 2


def test_canary_run_record_matches_the_contract() -> None:
    from moviespk_scraper.cli import _canary_run_document

    report = canary.CanaryReport(
        alerts=[storage_alert(ATLAS_LIMIT_BYTES)],  # type: ignore[list-item]
        errors=["database checks failed: ServerSelectionTimeoutError"],
        storage_bytes=ATLAS_LIMIT_BYTES,
    )
    doc = _canary_run_document(report, NOW, NOW + timedelta(minutes=2))  # validated inside
    assert doc["job"] == "canary" and doc["cinemaId"] == "canary"
    assert doc["status"] == "partial" and doc["storageBytes"] == ATLAS_LIMIT_BYTES
    assert [e["type"] for e in doc["errors"]] == ["storage", "check"]
    clean = _canary_run_document(canary.CanaryReport(), NOW, NOW)
    assert clean["status"] == "ok" and clean["errors"] == []
