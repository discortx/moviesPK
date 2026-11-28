"""P1-02: circuit breaker, per-cinema budget and the error → run status mapping."""

from __future__ import annotations

import random
from collections.abc import Iterator

import httpx
import pytest
import respx

from moviespk_scraper.core.circuit_breaker import CinemaBudget, CircuitBreaker
from moviespk_scraper.core.errors import (
    BlockedError,
    BudgetExceededError,
    CircuitOpenError,
    ParseError,
    RateLimitedError,
    RetryableStatusError,
    RobotsDisallowedError,
    RobotsUnavailableError,
    SchemaDriftError,
    run_status_for,
)
from moviespk_scraper.core.http import ScraperHttpClient

UA = "MoviesPKBot/1.0 (+https://github.com/example/moviespk)"
BASE = "https://cinema.example"
HOST = BASE


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(clock: FakeClock) -> Iterator[ScraperHttpClient]:
    with ScraperHttpClient(UA, clock=clock, sleep=clock.sleep, rng=random.Random(2)) as c:
        yield c


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as r:
        r.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
        yield r


# --- breaker unit --------------------------------------------------------------------


def test_opens_after_five_consecutive_failures() -> None:
    breaker = CircuitBreaker()
    for _ in range(4):
        breaker.record_failure(HOST, 500)
    breaker.before_request(HOST)  # still closed
    breaker.record_failure(HOST, 500)
    with pytest.raises(CircuitOpenError) as info:
        breaker.before_request(HOST)
    assert info.value.run_status == "failed"


def test_success_resets_the_streak() -> None:
    breaker = CircuitBreaker()
    for _ in range(4):
        breaker.record_failure(HOST, None)
    breaker.record_status(HOST, 200)
    for _ in range(4):
        breaker.record_failure(HOST, None)
    assert not breaker.is_open(HOST)


def test_neutral_4xx_neither_counts_nor_resets() -> None:
    breaker = CircuitBreaker()
    for _ in range(4):
        breaker.record_failure(HOST, 503)
    breaker.record_status(HOST, 404)
    assert not breaker.is_open(HOST)
    breaker.record_status(HOST, 503)
    assert breaker.is_open(HOST)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([403] * 5, "blocked"),
        ([429] * 5, "blocked"),
        ([403, 429, 403, 500, None], "blocked"),  # 3 of 5 refusals
        ([403, 429, 500, 502, None], "failed"),  # only 2 of 5
        ([None] * 5, "failed"),
    ],
)
def test_403_429_pattern_maps_to_blocked(statuses: list[int | None], expected: str) -> None:
    breaker = CircuitBreaker()
    for status in statuses:
        breaker.record_failure(HOST, status)
    with pytest.raises(CircuitOpenError) as info:
        breaker.before_request(HOST)
    assert info.value.run_status == expected
    assert run_status_for(info.value) == expected


def test_hosts_are_independent() -> None:
    breaker = CircuitBreaker()
    for _ in range(5):
        breaker.record_failure("https://a.example", 500)
    assert breaker.is_open("https://a.example")
    breaker.before_request("https://b.example")


def test_open_circuit_stays_open_for_the_run() -> None:
    breaker = CircuitBreaker()
    for _ in range(5):
        breaker.record_failure(HOST, 403)
    breaker.record_status(HOST, 200)
    assert breaker.is_open(HOST)


# --- breaker through the client -------------------------------------------------------


def test_after_five_failures_next_call_has_no_network_io(
    client: ScraperHttpClient, router: respx.MockRouter
) -> None:
    route = router.get(url__regex=rf"{BASE}/x/\d+").mock(return_value=httpx.Response(403))
    for i in range(5):
        assert client.get(f"{BASE}/x/{i}").status_code == 403
    calls = route.call_count
    with pytest.raises(CircuitOpenError) as info:
        client.get(f"{BASE}/x/99")
    assert route.call_count == calls == 5
    assert info.value.run_status == "blocked"


def test_rate_limited_failures_open_as_blocked(
    client: ScraperHttpClient, router: respx.MockRouter
) -> None:
    router.get(url__regex=rf"{BASE}/y/\d+").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "600"})
    )
    for i in range(5):
        with pytest.raises(RateLimitedError):
            client.get(f"{BASE}/y/{i}")
    with pytest.raises(CircuitOpenError) as info:
        client.get(f"{BASE}/y/9")
    assert info.value.run_status == "blocked"


def test_server_errors_open_as_failed(client: ScraperHttpClient, router: respx.MockRouter) -> None:
    router.get(url__regex=rf"{BASE}/z/\d+").mock(return_value=httpx.Response(503))
    for i in range(5):
        with pytest.raises(RetryableStatusError):
            client.get(f"{BASE}/z/{i}")
    with pytest.raises(CircuitOpenError) as info:
        client.get(f"{BASE}/z/9")
    assert info.value.run_status == "failed"


def test_network_errors_count(client: ScraperHttpClient, router: respx.MockRouter) -> None:
    router.get(url__regex=rf"{BASE}/n/\d+").mock(side_effect=httpx.ConnectError("down"))
    for i in range(5):
        with pytest.raises(httpx.ConnectError):
            client.get(f"{BASE}/n/{i}")
    assert client.breaker.is_open(HOST)


# --- budget --------------------------------------------------------------------------


def test_budget_raises_after_ten_minutes(clock: FakeClock) -> None:
    budget = CinemaBudget("c", clock=clock)
    clock.now += 599
    budget.check()
    assert budget.remaining_s == pytest.approx(1)
    clock.now += 1
    with pytest.raises(BudgetExceededError, match="600 s budget"):
        budget.check()


def test_exhausted_budget_stops_requests(
    client: ScraperHttpClient, router: respx.MockRouter, clock: FakeClock
) -> None:
    route = router.get(f"{BASE}/b").mock(return_value=httpx.Response(200))
    budget = CinemaBudget("c", clock=clock)
    clock.now += 600
    with pytest.raises(BudgetExceededError):
        client.get(f"{BASE}/b", budget=budget)
    assert route.call_count == 0


def test_budget_is_checked_between_retries(
    client: ScraperHttpClient, router: respx.MockRouter, clock: FakeClock
) -> None:
    route = router.get(f"{BASE}/slow").mock(return_value=httpx.Response(503))
    budget = CinemaBudget("c", limit_s=3, clock=clock)  # the 2 s backoff + jitter + delay
    with pytest.raises(BudgetExceededError):
        client.get(f"{BASE}/slow", budget=budget)
    assert route.call_count < 3


# --- error → run status --------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (RobotsDisallowedError("https://e/x", UA), "blocked"),
        (RobotsUnavailableError("https://e/x", UA), "blocked"),
        (BlockedError("refused"), "blocked"),
        (SchemaDriftError("no sessions key"), "drift"),
        (ParseError("bad time"), "failed"),
        (BudgetExceededError("10 min"), "failed"),
        (RetryableStatusError("503", url_path="/x", status=503), "failed"),
        (httpx.ConnectError("down"), "failed"),
        (ValueError("anything else"), "failed"),
    ],
)
def test_run_status_for(exc: BaseException, status: str) -> None:
    assert run_status_for(exc) == status


def test_unreachable_robots_message_does_not_claim_a_disallow() -> None:
    message = str(RobotsUnavailableError("https://e.example/api/movies?cinemaId=14", UA))
    assert "could not be fetched" in message and "/api/movies" in message
    assert "disallows" not in message and "cinemaId" not in message
    assert run_status_for(RobotsUnavailableError("https://e.example/x", UA)) == "blocked"
