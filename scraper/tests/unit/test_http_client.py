"""P1-01 acceptance tests for the HTTP client (plan §10.2). No real sleeping: a fake clock
advances when the client sleeps."""

from __future__ import annotations

import itertools
import random
from collections.abc import Iterator

import httpx
import pytest
import respx

from moviespk_scraper.core.errors import (
    RateLimitedError,
    RetryableStatusError,
    RobotsDisallowedError,
    RobotsUnavailableError,
    TooManyRedirectsError,
)
from moviespk_scraper.core.http import ScraperHttpClient
from moviespk_scraper.core.retry import parse_retry_after

UA = "MoviesPKBot/1.0 (+https://github.com/example/moviespk; contact@example.com)"
BASE = "https://cinema.example"
ROBOTS = "User-agent: *\nDisallow: /private/\n"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
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
def client(clock: FakeClock) -> Iterator[ScraperHttpClient]:
    with ScraperHttpClient(UA, clock=clock, sleep=clock.sleep, rng=random.Random(1)) as c:
        yield c


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as r:
        yield r


def _robots(router: respx.MockRouter, status: int = 200, body: str = ROBOTS) -> respx.Route:
    return router.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(status, text=body))


# --- retries -------------------------------------------------------------------------


def test_503_twice_then_200_succeeds_after_backoff(
    client: ScraperHttpClient, router: respx.MockRouter, clock: FakeClock
) -> None:
    _robots(router)
    route = router.get(f"{BASE}/api/movies").mock(
        side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(200, text="ok")]
    )
    assert client.get(f"{BASE}/api/movies").text == "ok"
    assert route.call_count == 3
    backoffs = [s for s in clock.sleeps if s >= 2.0]
    assert 2.0 <= backoffs[0] <= 3.0 and 4.0 <= backoffs[1] <= 5.0


def test_retryable_status_gives_up_after_three_attempts(
    client: ScraperHttpClient, router: respx.MockRouter
) -> None:
    _robots(router)
    route = router.get(f"{BASE}/x").mock(return_value=httpx.Response(502))
    with pytest.raises(RetryableStatusError) as info:
        client.get(f"{BASE}/x")
    assert route.call_count == 3 and info.value.status == 502


def test_timeouts_and_connection_errors_are_retried(
    client: ScraperHttpClient, router: respx.MockRouter
) -> None:
    _robots(router)
    route = router.get(f"{BASE}/x").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.ConnectError("down"), httpx.Response(200)]
    )
    assert client.get(f"{BASE}/x").status_code == 200
    assert route.call_count == 3


@pytest.mark.parametrize("status", [400, 403, 404, 500])
def test_no_retry_on_other_statuses(
    client: ScraperHttpClient, router: respx.MockRouter, status: int
) -> None:
    _robots(router)
    route = router.get(f"{BASE}/x").mock(return_value=httpx.Response(status))
    assert client.get(f"{BASE}/x").status_code == status
    assert route.call_count == 1


def test_429_honours_retry_after(
    client: ScraperHttpClient, router: respx.MockRouter, clock: FakeClock
) -> None:
    _robots(router)
    router.get(f"{BASE}/x").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200)]
    )
    before = clock.now
    assert client.get(f"{BASE}/x").status_code == 200
    assert 3.0 in clock.sleeps
    assert clock.now - before >= 3.0


def test_429_with_long_retry_after_fails_at_once(
    client: ScraperHttpClient, router: respx.MockRouter
) -> None:
    _robots(router)
    route = router.get(f"{BASE}/x").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "121"})
    )
    with pytest.raises(RateLimitedError) as info:
        client.get(f"{BASE}/x")
    assert route.call_count == 1 and info.value.retry_after_s == 121.0


def test_parse_retry_after() -> None:
    from datetime import UTC, datetime

    now = datetime(2026, 11, 25, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("7") == 7.0
    assert parse_retry_after("Wed, 25 Nov 2026 12:00:30 GMT", now=now) == 30.0
    assert parse_retry_after("Wed, 25 Nov 2026 11:00:00 GMT", now=now) == 0.0
    assert parse_retry_after("soon") is None
    assert parse_retry_after(None) is None


# --- throttle ------------------------------------------------------------------------


def test_requests_to_one_host_are_spaced(
    client: ScraperHttpClient, router: respx.MockRouter, clock: FakeClock
) -> None:
    _robots(router)
    times: list[float] = []

    def record(request: httpx.Request) -> httpx.Response:
        times.append(clock.now)
        return httpx.Response(200)

    router.get(url__regex=rf"{BASE}/page/\d").mock(side_effect=record)
    for i in range(4):
        client.get(f"{BASE}/page/{i}", min_delay_ms=1500)
    gaps = [b - a for a, b in itertools.pairwise(times)]
    assert gaps and all(1.5 <= g <= 2.0 for g in gaps)


def test_crawl_delay_larger_than_min_delay_is_honoured(
    client: ScraperHttpClient, router: respx.MockRouter, clock: FakeClock
) -> None:
    _robots(router, body="User-agent: *\nCrawl-delay: 5\n")
    times: list[float] = []

    def record(request: httpx.Request) -> httpx.Response:
        times.append(clock.now)
        return httpx.Response(200)

    router.get(url__regex=rf"{BASE}/p\d").mock(side_effect=record)
    client.get(f"{BASE}/p1")
    client.get(f"{BASE}/p2")
    assert times[1] - times[0] >= 5.0


def test_other_hosts_are_not_delayed(
    client: ScraperHttpClient, router: respx.MockRouter, clock: FakeClock
) -> None:
    for host in ("https://a.example", "https://b.example"):
        router.get(f"{host}/robots.txt").mock(return_value=httpx.Response(404))
        router.get(f"{host}/x").mock(return_value=httpx.Response(200))
    client.get("https://a.example/x")
    sleeps_before = list(clock.sleeps)
    client.get("https://b.example/x")
    # b's robots + first request wait for nothing; only b's own second request would wait
    assert len(clock.sleeps) - len(sleeps_before) == 1


# --- robots --------------------------------------------------------------------------


def test_disallowed_path_raises_with_zero_requests(
    client: ScraperHttpClient, router: respx.MockRouter
) -> None:
    _robots(router)
    private = router.get(f"{BASE}/private/data").mock(return_value=httpx.Response(200))
    with pytest.raises(RobotsDisallowedError):
        client.get(f"{BASE}/private/data")
    assert private.call_count == 0


def test_robots_fetched_once_per_host_per_run(
    client: ScraperHttpClient, router: respx.MockRouter
) -> None:
    robots = _robots(router)
    router.get(url__regex=rf"{BASE}/a/\d").mock(return_value=httpx.Response(200))
    for i in range(3):
        client.get(f"{BASE}/a/{i}")
    assert robots.call_count == 1


def test_robots_404_allows(client: ScraperHttpClient, router: respx.MockRouter) -> None:
    _robots(router, status=404, body="")
    router.get(f"{BASE}/private/data").mock(return_value=httpx.Response(200))
    assert client.get(f"{BASE}/private/data").status_code == 200


@pytest.mark.parametrize("failure", ["503", "network"])
def test_robots_unreachable_blocks(
    client: ScraperHttpClient, router: respx.MockRouter, failure: str
) -> None:
    route = router.get(f"{BASE}/robots.txt")
    if failure == "503":
        route.mock(return_value=httpx.Response(503))
    else:
        route.mock(side_effect=httpx.ConnectError("down"))
    page = router.get(f"{BASE}/x").mock(return_value=httpx.Response(200))
    with pytest.raises(RobotsUnavailableError):
        client.get(f"{BASE}/x")
    assert page.call_count == 0
    assert client.robots_for(f"{BASE}/x").blocked


def test_permission_granted_skips_robots_only_with_ref(
    client: ScraperHttpClient, router: respx.MockRouter
) -> None:
    robots = _robots(router)
    router.get(f"{BASE}/private/data").mock(return_value=httpx.Response(200))
    with pytest.raises(ValueError, match="permission_ref"):
        client.get(f"{BASE}/private/data", robots_policy="permission_granted")
    resp = client.get(
        f"{BASE}/private/data", robots_policy="permission_granted", permission_ref="email-2026-12"
    )
    assert resp.status_code == 200 and robots.call_count == 0


def test_unknown_robots_policy_is_rejected(client: ScraperHttpClient) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        client.get(f"{BASE}/x", robots_policy="ignore")  # type: ignore[arg-type]


# --- redirects, identity, conditional requests ---------------------------------------


def test_redirect_target_is_robots_checked(
    client: ScraperHttpClient, router: respx.MockRouter
) -> None:
    _robots(router)
    router.get(f"{BASE}/go").mock(
        return_value=httpx.Response(302, headers={"Location": "/private/secret"})
    )
    private = router.get(f"{BASE}/private/secret").mock(return_value=httpx.Response(200))
    with pytest.raises(RobotsDisallowedError):
        client.get(f"{BASE}/go")
    assert private.call_count == 0


def test_redirects_are_followed_and_capped(
    client: ScraperHttpClient, router: respx.MockRouter
) -> None:
    _robots(router)
    router.get(f"{BASE}/old").mock(return_value=httpx.Response(301, headers={"Location": "/new"}))
    router.get(f"{BASE}/new").mock(return_value=httpx.Response(200, text="new"))
    assert client.get(f"{BASE}/old").text == "new"
    router.get(f"{BASE}/loop").mock(return_value=httpx.Response(302, headers={"Location": "/loop"}))
    with pytest.raises(TooManyRedirectsError):
        client.get(f"{BASE}/loop")


def test_sends_the_project_user_agent(client: ScraperHttpClient, router: respx.MockRouter) -> None:
    robots = _robots(router)
    page = router.get(f"{BASE}/x").mock(return_value=httpx.Response(200))
    client.get(f"{BASE}/x")
    assert robots.calls.last.request.headers["user-agent"] == UA
    assert page.calls.last.request.headers["user-agent"] == UA


def test_conditional_request_within_a_run(
    client: ScraperHttpClient, router: respx.MockRouter
) -> None:
    _robots(router)
    route = router.get(f"{BASE}/x").mock(
        side_effect=[
            httpx.Response(200, text="body", headers={"ETag": '"v1"'}),
            httpx.Response(304),
        ]
    )
    assert client.get(f"{BASE}/x").text == "body"
    second = client.get(f"{BASE}/x")
    assert route.calls.last.request.headers["if-none-match"] == '"v1"'
    assert second.status_code == 200 and second.text == "body"


def test_a_new_client_starts_without_validators(clock: FakeClock, router: respx.MockRouter) -> None:
    _robots(router)
    route = router.get(f"{BASE}/x").mock(
        return_value=httpx.Response(200, text="b", headers={"ETag": '"v1"'})
    )
    for _ in range(2):
        with ScraperHttpClient(UA, clock=clock, sleep=clock.sleep) as c:
            c.get(f"{BASE}/x")
    assert all("if-none-match" not in call.request.headers for call in route.calls)


def test_empty_user_agent_is_rejected() -> None:
    with pytest.raises(ValueError):
        ScraperHttpClient("  ")
