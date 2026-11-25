"""Job runner (plan §10.3, P1-04): runs one job over the selected cinemas.

* at most 3 cinemas in parallel (threads), sequential work within one cinema;
* each cinema gets its own 10-minute budget and logger, and shares the run's HTTP client
  (per-host throttle, robots cache and circuit breaker are per run);
* a cinema's error becomes its run status through :func:`run_status_for`; one cinema's
  failure never stops the others.

Pipeline steps 2-8 (normalize, validate, match, upsert, images, reconcile, health,
alerts) are added by P1-07 … P1-13; until then the ``full`` job fetches and parses only.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from structlog.typing import FilteringBoundLogger

from .adapters import registry
from .adapters.base import RawMovie, RawShowtime, RunContext
from .core.circuit_breaker import CinemaBudget
from .core.config import CinemaConfig
from .core.errors import run_status_for
from .core.http import ScraperHttpClient
from .core.logging import get_logger
from .models.vocab import Job, RunStatus

MAX_PARALLEL_CINEMAS = 3
SHOWTIME_DAYS = 7


@dataclass
class CinemaResult:
    cinema_id: str
    status: RunStatus
    movies: list[RawMovie] = field(default_factory=list)
    showtimes: list[RawShowtime] = field(default_factory=list)
    error: str | None = None
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "partial")


@dataclass
class RunReport:
    job: Job
    dry_run: bool
    started_at: datetime
    results: list[CinemaResult]

    @property
    def exit_code(self) -> int:
        """0 = every cinema ok/partial; 1 = any failed, blocked or drift (plan §10.3)."""
        return 0 if all(r.ok for r in self.results) else 1


def _run_full(ctx: RunContext, cinema: CinemaConfig) -> CinemaResult:
    adapter = registry.get_adapter(cinema.adapter)
    movies = adapter.list_movies(ctx, cinema)
    showtimes = adapter.list_showtimes(ctx, cinema, days=SHOWTIME_DAYS)
    return CinemaResult(cinema.id, "ok", movies=movies, showtimes=showtimes)


JOB_STEPS: dict[Job, Callable[[RunContext, CinemaConfig], CinemaResult]] = {"full": _run_full}


def run_cinema(
    http: ScraperHttpClient,
    job: Job,
    cinema: CinemaConfig,
    *,
    now: datetime,
    clock: Callable[[], float],
    log: FilteringBoundLogger | None = None,
    debug_dir: Path | None = None,
) -> CinemaResult:
    log = (log or get_logger()).bind(job=job, cinemaId=cinema.id)
    budget = CinemaBudget(cinema.id, clock=clock)
    ctx = RunContext(http=http, job=job, now=now, log=log, budget=budget, debug_dir=debug_dir)
    log.info("cinema.start", phase="start")
    try:
        result = JOB_STEPS[job](ctx, cinema)
    except Exception as exc:
        status = run_status_for(exc)
        log.warning("cinema.end", phase="end", status=status, error=type(exc).__name__)
        result = CinemaResult(cinema.id, status, error=f"{type(exc).__name__}: {exc}")
    else:
        log.info(
            "cinema.end",
            phase="end",
            status=result.status,
            movies=len(result.movies),
            showtimes=len(result.showtimes),
        )
    result.duration_s = budget.elapsed_s
    return result


def run_job(
    http: ScraperHttpClient,
    job: Job,
    cinemas: Sequence[CinemaConfig],
    *,
    dry_run: bool,
    clock: Callable[[], float],
    now: datetime | None = None,
    log: FilteringBoundLogger | None = None,
    debug_dir: Path | None = None,
) -> RunReport:
    started = now or datetime.now(UTC)
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CINEMAS) as pool:
        results = list(
            pool.map(
                lambda c: run_cinema(
                    http, job, c, now=started, clock=clock, log=log, debug_dir=debug_dir
                ),
                cinemas,
            )
        )
    return RunReport(job=job, dry_run=dry_run, started_at=started, results=results)
