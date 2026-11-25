"""The scraper's only HTTP client (plan §10.2, P1-01).

Every request goes through :meth:`ScraperHttpClient.get`, which in order:

1. checks robots.txt for the URL (robots fetched once per host per run, through this
   client); a disallowed URL raises :class:`RobotsDisallowedError` before any request, and
   an unreachable robots.txt (5xx / network failure) raises :class:`RobotsUnavailableError`
   (run status ``blocked``);
2. waits for the host's slot (``min_delay_ms`` or a larger ``Crawl-delay``, plus jitter;
   one request in flight per host);
3. sends the GET with the descriptive User-Agent and per-run conditional headers;
4. retries timeouts, connection errors, 502/503/504 and short 429s (``core/retry.py``);
5. follows up to 5 redirects itself, re-checking robots.txt for every hop.

Identity rules: the User-Agent is the project's own (never a browser's); no cookies are
kept between runs; no login, CAPTCHA or paywall handling exists or may be added.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Literal, Self
from urllib.parse import urljoin, urlsplit

import httpx
from structlog.typing import FilteringBoundLogger

from .errors import (
    RateLimitedError,
    RetryableStatusError,
    RobotsUnavailableError,
    TooManyRedirectsError,
)
from .logging import get_logger, url_path
from .retry import RETRYABLE_STATUSES, parse_retry_after, retrying
from .robots import RobotsPolicy, robots_url
from .throttle import HostThrottle

DEFAULT_MIN_DELAY_MS = 1500
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 30.0
MAX_REDIRECTS = 5

RobotsPolicyName = Literal["respect", "permission_granted"]


def _host(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"absolute http(s) URL required: {url_path(url)}")
    return f"{parts.scheme}://{parts.netloc.lower()}"


class ScraperHttpClient:
    """One instance per run. Not shared between runs (robots and validators are per run)."""

    def __init__(
        self,
        user_agent: str,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        logger: FilteringBoundLogger | None = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("user agent must not be empty")
        self.user_agent = user_agent
        self._clock = clock
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 (jitter, not security)
        self._log = logger or get_logger()
        self._throttle = HostThrottle(clock=clock, sleep=sleep, rng=self._rng)
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
            follow_redirects=False,
            transport=transport,
        )
        self._robots: dict[str, RobotsPolicy] = {}
        self._robots_guard = threading.Lock()
        self._robots_locks: dict[str, threading.Lock] = {}
        # url -> (ETag, Last-Modified, response): conditional requests within this run only.
        self._validators: dict[str, tuple[str | None, str | None, httpx.Response]] = {}

    # --- lifecycle -------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # --- robots ----------------------------------------------------------------------

    def robots_for(self, url: str, *, min_delay_ms: int = DEFAULT_MIN_DELAY_MS) -> RobotsPolicy:
        """The robots policy for the host of ``url``, fetched at most once per run."""
        host = _host(url)
        with self._robots_guard:
            lock = self._robots_locks.setdefault(host, threading.Lock())
        with lock:
            policy = self._robots.get(host)
            if policy is None:
                policy = self._fetch_robots(host, min_delay_ms)
                self._robots[host] = policy
            return policy

    def _fetch_robots(self, host: str, min_delay_ms: int) -> RobotsPolicy:
        target = robots_url(host)
        status: int | None
        body = ""
        start = self._clock()
        with self._throttle.slot(host, min_delay_ms):
            try:
                resp = self._client.get(target, follow_redirects=True)
                status, body = resp.status_code, resp.text
            except httpx.HTTPError as exc:
                status = None
                self._log.warning("robots.error", url_path="/robots.txt", error=type(exc).__name__)
        policy = RobotsPolicy.from_response(self.user_agent, status, body)
        self._log.info(
            "robots.fetched",
            url_path="/robots.txt",
            status=status,
            mode=policy.mode,
            durationMs=round((self._clock() - start) * 1000),
        )
        return policy

    def _check_robots(
        self,
        url: str,
        min_delay_ms: int,
        robots_policy: RobotsPolicyName,
        permission_ref: str | None,
    ) -> int:
        """Raise if ``url`` may not be fetched; return the delay to use for its host."""
        if robots_policy == "permission_granted":
            if not permission_ref:
                raise ValueError("robots_policy 'permission_granted' requires permission_ref")
            return min_delay_ms
        if robots_policy != "respect":
            raise ValueError(f"unsupported robots_policy: {robots_policy!r}")
        policy = self.robots_for(url, min_delay_ms=min_delay_ms)
        if policy.blocked:
            raise RobotsUnavailableError(url, self.user_agent)
        policy.check(url)
        return policy.effective_delay_ms(min_delay_ms)

    # --- requests --------------------------------------------------------------------

    def get(
        self,
        url: str,
        *,
        min_delay_ms: int = DEFAULT_MIN_DELAY_MS,
        robots_policy: RobotsPolicyName = "respect",
        permission_ref: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """GET ``url`` under every §10.2 rule. Returns the final response (any status
        other than the retried ones); raises the typed errors of ``core/errors.py``."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            delay_ms = self._check_robots(current, min_delay_ms, robots_policy, permission_ref)
            resp = self._get_with_retries(current, delay_ms, headers)
            location = resp.headers.get("location")
            if resp.is_redirect and location:
                current = urljoin(current, location)
                continue
            return resp
        raise TooManyRedirectsError(f"more than {MAX_REDIRECTS} redirects", url_path=url_path(url))

    def _get_with_retries(
        self, url: str, delay_ms: int, headers: Mapping[str, str] | None
    ) -> httpx.Response:
        for attempt in retrying(sleep=self._sleep, rng=self._rng):
            with attempt:
                return self._send(url, delay_ms, headers, attempt.retry_state.attempt_number)
        raise AssertionError("unreachable: tenacity reraises the last error")  # pragma: no cover

    def _send(
        self, url: str, delay_ms: int, headers: Mapping[str, str] | None, attempt: int
    ) -> httpx.Response:
        path = url_path(url)
        request_headers = dict(headers or {})
        cached = self._validators.get(url)
        if cached is not None:
            etag, last_modified, _ = cached
            if etag:
                request_headers["If-None-Match"] = etag
            if last_modified:
                request_headers["If-Modified-Since"] = last_modified

        with self._throttle.slot(_host(url), delay_ms):
            start = self._clock()
            try:
                resp = self._client.get(url, headers=request_headers)
            except httpx.HTTPError as exc:
                self._log.warning(
                    "http.error",
                    url_path=path,
                    attempt=attempt,
                    error=type(exc).__name__,
                    durationMs=round((self._clock() - start) * 1000),
                )
                raise
            self._log.info(
                "http.request",
                url_path=path,
                status=resp.status_code,
                attempt=attempt,
                durationMs=round((self._clock() - start) * 1000),
            )

        if resp.status_code in RETRYABLE_STATUSES:
            raise RetryableStatusError(
                f"{resp.status_code} on {path}", url_path=path, status=resp.status_code
            )
        if resp.status_code == 429:
            raise RateLimitedError(
                url_path=path, retry_after_s=parse_retry_after(resp.headers.get("retry-after"))
            )
        if resp.status_code == 304 and cached is not None:
            return cached[2]
        if resp.status_code == 200:
            etag, last_modified = resp.headers.get("etag"), resp.headers.get("last-modified")
            if etag or last_modified:
                resp.read()
                self._validators[url] = (etag, last_modified, resp)
        return resp
