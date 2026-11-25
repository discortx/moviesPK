"""TMDB client (plan §10.4 step 7, P1-09).

* One client per run, shared by API calls and (P1-23) poster downloads.
* **At most 5 requests per second** across all threads (≥ 200 ms between request starts).
* Retries timeouts, connection errors, 5xx and 429 (``Retry-After`` honoured up to 60 s,
  else exponential backoff), 3 attempts; then :class:`TmdbError`.
* Timeout 10 s. Logs carry the path only, never the key or the query string.
* The key comes from ``TMDB_API_KEY``: a v4 read access token (a JWT, ``eyJ…``) is sent as
  ``Authorization: Bearer``; a v3 key as the ``api_key`` query parameter.
* ``/configuration`` (the image base URL) is fetched at most once per run, and callers that
  persist it may pass a cached copy younger than 7 days instead (plan P1-09).

TMDB data is used under its non-commercial terms with the required attribution (OD5).
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from types import TracebackType
from typing import Any, Self

import httpx
from structlog.typing import FilteringBoundLogger
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt

from ..core.logging import get_logger
from ..core.retry import parse_retry_after

API_BASE = "https://api.themoviedb.org/3"
DEFAULT_IMAGE_BASE = "https://image.tmdb.org/t/p/"
MIN_INTERVAL_S = 0.2  # 5 requests per second
TIMEOUT_S = 10.0
ATTEMPTS = 3
RETRY_AFTER_MAX_S = 60.0
CONFIG_MAX_AGE = timedelta(days=7)


class TmdbError(Exception):
    """TMDB could not answer (after retries). Callers degrade, never crash (§10.4 step 7)."""


class _Retryable(Exception):
    def __init__(self, status: int, retry_after_s: float | None = None) -> None:
        super().__init__(f"TMDB answered {status}")
        self.status = status
        self.retry_after_s = retry_after_s


class RateLimiter:
    """Thread-safe minimum spacing between request starts."""

    def __init__(
        self,
        min_interval_s: float = MIN_INTERVAL_S,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval_s = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next = float("-inf")

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if now < self._next:
                self._sleep(self._next - now)
                now = self._next
            self._next = now + self.min_interval_s


@dataclass(frozen=True)
class TmdbCandidate:
    tmdb_id: int
    title: str
    original_title: str | None
    release_date: date | None

    @property
    def year(self) -> int | None:
        return self.release_date.year if self.release_date else None


@dataclass(frozen=True)
class TmdbMovie:
    tmdb_id: int
    title: str
    original_title: str | None
    overview: str | None
    runtime_min: int | None
    genres: tuple[str, ...]
    release_date: date | None
    poster_path: str | None  # handed to the image step (P1-23); never stored


@dataclass(frozen=True)
class TmdbConfiguration:
    image_base_url: str
    fetched_at: datetime

    def is_fresh(self, now: datetime) -> bool:
        return now - self.fetched_at < CONFIG_MAX_AGE


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) and value else None
    except ValueError:
        return None


def _str(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


class TmdbClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        limiter: RateLimiter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        logger: FilteringBoundLogger | None = None,
        language: str = "en-US",
        region: str = "PK",
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("TMDB_API_KEY is empty")
        headers = {"Accept": "application/json"}
        self._params: dict[str, str] = {"language": language}
        if key.startswith("eyJ"):  # v4 read access token (JWT)
            headers["Authorization"] = f"Bearer {key}"
        else:  # v3 API key
            self._params["api_key"] = key
        self.region = region
        self._client = httpx.Client(
            base_url=API_BASE, headers=headers, timeout=TIMEOUT_S, transport=transport
        )
        self.limiter = limiter or RateLimiter(sleep=sleep)
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 (jitter, not security)
        self._log = logger or get_logger()
        self._config: TmdbConfiguration | None = None
        self.calls = 0

    # --- lifecycle --------------------------------------------------------------------

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

    # --- transport ----------------------------------------------------------------------

    def _wait(self, state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        if isinstance(exc, _Retryable) and exc.retry_after_s is not None:
            return min(exc.retry_after_s, RETRY_AFTER_MAX_S)
        return float(2 ** (state.attempt_number - 1)) + self._rng.uniform(0, 0.5)

    def _get(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        retrying = Retrying(
            stop=stop_after_attempt(ATTEMPTS),
            wait=self._wait,
            retry=retry_if_exception(
                lambda e: isinstance(e, _Retryable | httpx.TimeoutException | httpx.TransportError)
            ),
            sleep=self._sleep,
            reraise=True,
        )
        try:
            for attempt in retrying:
                with attempt:
                    return self._send(path, params)
        except (_Retryable, httpx.HTTPError) as exc:
            raise TmdbError(f"TMDB {path} failed: {exc}") from exc
        raise AssertionError("unreachable")  # pragma: no cover

    def _send(self, path: str, params: Mapping[str, str] | None) -> Any:
        self.limiter.wait()
        self.calls += 1
        started = time.monotonic()
        try:
            resp = self._client.get(path, params={**self._params, **(params or {})})
        except httpx.HTTPError as exc:
            self._log.warning("tmdb.error", url_path=path, error=type(exc).__name__)
            raise
        self._log.info(
            "tmdb.request",
            url_path=path,
            status=resp.status_code,
            durationMs=round((time.monotonic() - started) * 1000),
        )
        if resp.status_code == 429 or resp.status_code >= 500:
            raise _Retryable(resp.status_code, parse_retry_after(resp.headers.get("retry-after")))
        if resp.status_code != 200:
            raise TmdbError(f"TMDB {path} answered {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise TmdbError(f"TMDB {path} returned invalid JSON") from exc

    # --- API ------------------------------------------------------------------------------

    def search_movie(self, query: str, year: int | None = None) -> list[TmdbCandidate]:
        params = {"query": query, "include_adult": "false", "region": self.region}
        if year:
            params["year"] = str(year)
        data = self._get("/search/movie", params)
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise TmdbError("TMDB /search/movie: no results list")
        out = []
        for item in results:
            if (
                isinstance(item, dict)
                and isinstance(item.get("id"), int)
                and _str(item.get("title"))
            ):
                out.append(
                    TmdbCandidate(
                        tmdb_id=item["id"],
                        title=item["title"].strip(),
                        original_title=_str(item.get("original_title")),
                        release_date=_date(item.get("release_date")),
                    )
                )
        return out

    def movie_details(self, tmdb_id: int) -> TmdbMovie:
        data = self._get(f"/movie/{tmdb_id}")
        if not isinstance(data, dict) or data.get("id") != tmdb_id:
            raise TmdbError(f"TMDB /movie/{tmdb_id}: unexpected payload")
        runtime = data.get("runtime")
        genres = tuple(
            g["name"]
            for g in data.get("genres") or []
            if isinstance(g, dict) and _str(g.get("name"))
        )
        return TmdbMovie(
            tmdb_id=tmdb_id,
            title=_str(data.get("title")) or "",
            original_title=_str(data.get("original_title")),
            overview=_str(data.get("overview")),
            runtime_min=runtime if isinstance(runtime, int) and runtime > 0 else None,
            genres=genres,
            release_date=_date(data.get("release_date")),
            poster_path=_str(data.get("poster_path")),
        )

    def configuration(
        self, *, cached: TmdbConfiguration | None = None, now: datetime | None = None
    ) -> TmdbConfiguration:
        """The image base URL: a cached copy younger than 7 days, else at most one fetch
        per run; on failure the documented default ``https://image.tmdb.org/t/p/``."""
        moment = now or datetime.now(UTC)
        if cached is not None and cached.is_fresh(moment):
            return cached
        if self._config is None:
            try:
                data = self._get("/configuration")
                base = _str(((data or {}).get("images") or {}).get("secure_base_url"))
            except TmdbError as exc:
                self._log.warning("tmdb.configuration_fallback", error=str(exc))
                base = None
            self._config = TmdbConfiguration(base or DEFAULT_IMAGE_BASE, moment)
        return self._config
