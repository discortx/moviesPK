"""Job runner (plan §10.3, P1-04): runs one job over the selected cinemas.

* at most 3 cinemas in parallel (threads), sequential work within one cinema;
* each cinema gets its own 10-minute budget and logger, and shares the run's HTTP client
  (per-host throttle, robots cache and circuit breaker are per run);
* a cinema's error becomes its run status through :func:`run_status_for`; one cinema's
  failure never stops the others.

Steps not yet built: images (P1-23), health and alerts (P1-12/P1-13). A dry run (no
database) stops after matching; a writing run also upserts and reconciles.
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
from .db import repositories as repo
from .db.client import DB
from .models.vocab import Job, RunStatus
from .pipeline.match import Matcher, MatchResult
from .pipeline.normalize import (
    NormalizedMovie,
    NormalizedShowtime,
    normalize_movie,
    normalize_showtime,
)
from .pipeline.reconcile import MEDIAN_RUNS, guard_reason, reconcile
from .pipeline.upsert import UpsertCounts, upsert_cinema
from .pipeline.validate import validate
from .services.alerts import Alert, Alerter, run_url
from .services.health import RunError, RunRecord, github_run_id, last_success, record_run
from .services.images import ImageStep

MAX_PARALLEL_CINEMAS = 3
SHOWTIME_DAYS = 7


@dataclass
class CinemaResult:
    cinema_id: str
    status: RunStatus
    movies: list[RawMovie] = field(default_factory=list)
    showtimes: list[RawShowtime] = field(default_factory=list)
    normalized_movies: list[NormalizedMovie] = field(default_factory=list)
    normalized_showtimes: list[NormalizedShowtime] = field(default_factory=list)
    invalid: int = 0
    matches: dict[str, MatchResult] = field(default_factory=dict)  # by title key
    upserted: int = 0
    cancelled: int = 0
    images_uploaded: int = 0
    images_failed: int = 0
    error: str | None = None
    error_type: str | None = None
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


@dataclass(frozen=True)
class Services:
    """Run-wide services shared by every cinema (one TMDB client and matcher per run)."""

    matcher: Matcher = field(default_factory=lambda: Matcher(None))
    #: The database to write to; ``None`` for a dry run (nothing is written).
    db: DB | None = None
    #: Where alerts go (GitHub Issues, or printed on a dry run); ``None`` = no alerts.
    alerter: Alerter | None = None
    #: The poster step (writing runs with TMDB and R2 configured); ``None`` = no images.
    images: ImageStep | None = None


def _match_all(
    services: Services,
    cinema: CinemaConfig,
    movies: list[NormalizedMovie],
    showtimes: list[NormalizedShowtime],
) -> dict[str, MatchResult]:
    """Match every listed movie, plus any showtime title without a movie entry."""
    by_key = {m.title_key: m for m in movies}
    for show in showtimes:
        if show.title_key not in by_key:
            by_key[show.title_key] = NormalizedMovie(
                title=show.movie_title,
                title_key=show.title_key,
                local_key=show.movie_local_key,
                original_title=None,
                runtime_min=None,
                genres=(),
                languages=(),
                synopsis=None,
                release_date=None,
                year=None,
                certification=None,
            )
    return {key: services.matcher.match(m, cinema.id) for key, m in by_key.items()}


def _run_full(ctx: RunContext, cinema: CinemaConfig, services: Services) -> CinemaResult:
    adapter = registry.get_adapter(cinema.adapter)
    movies = adapter.list_movies(ctx, cinema)
    showtimes = adapter.list_showtimes(ctx, cinema, days=SHOWTIME_DAYS)
    checked = validate(
        [normalize_movie(m, ctx.log) for m in movies],
        [normalize_showtime(s, ctx.log) for s in showtimes],
        now=ctx.now,
        log=ctx.log,
    )
    result = CinemaResult(
        cinema.id,
        "ok",
        movies=movies,
        showtimes=showtimes,
        normalized_movies=checked.movies,
        normalized_showtimes=checked.showtimes,
        invalid=checked.invalid,
    )
    if checked.failed:
        result.status = "failed"
        result.error_type = "InvalidRate"
        result.error = (
            f"{checked.invalid} of {checked.total} showtimes invalid "
            f"({checked.invalid_rate:.0%} > {checked.max_invalid_rate:.0%}): "
            + ", ".join(f"{k} x{v}" for k, v in checked.reasons.most_common(3))
        )
        return result
    history = (
        repo.recent_ok_showtime_counts(services.db, cinema.id, MEDIAN_RUNS)
        if services.db is not None
        else []
    )
    reason = guard_reason(len(checked.showtimes), history)
    if reason is not None:  # zero-result / median guard: nothing is written (§8.4)
        result.status = "failed"
        result.error_type = "ZeroResult" if "zero result" in reason else "MedianGuard"
        result.error = reason
        return result
    result.matches = _match_all(services, cinema, checked.movies, checked.showtimes)
    if services.db is not None:
        counts = upsert_cinema(
            services.db, cinema, checked.movies, checked.showtimes, result.matches, ctx.now
        )
        result.upserted = counts.showtimes
        # Reconcile only an ok run, and only up to the latest show this run saw.
        rec = reconcile(
            services.db,
            cinema.id,
            counts.showtime_ids,
            now=ctx.now,
            until=max(s.starts_at for s in checked.showtimes),
        )
        result.cancelled = rec.cancelled
        if services.images is not None:
            _run_images(services.images, result, counts, ctx)
        ctx.log.info(
            "upsert.done",
            phase="upsert",
            movies=counts.movies,
            showtimes=counts.showtimes,
            aliases=counts.aliases,
            relinked=counts.relinked,
            missed=rec.missed,
            cancelled=rec.cancelled,
        )
    return result


def _run_images(
    images: ImageStep, result: CinemaResult, counts: UpsertCounts, ctx: RunContext
) -> None:
    """Posters for matched movies that have none, were refreshed from TMDB this run, or on
    --rebuild-images (plan §10.3 step 5a). Failures are counted, never raised."""
    for key, match in result.matches.items():
        stored = counts.stored.get(key)
        if match.status != "matched" or match.tmdb_id is None or stored is None:
            continue
        if stored.poster_key is not None and match.details is None and not images.rebuild:
            continue
        outcome, puts = images.poster_for(
            str(stored.id), match.tmdb_id, match.poster_path, stored.poster_key, ctx.now
        )
        result.images_uploaded += puts
        if outcome == "failed":
            result.images_failed += 1


JOB_STEPS: dict[Job, Callable[[RunContext, CinemaConfig, Services], CinemaResult]] = {
    "full": _run_full
}


def run_cinema(
    http: ScraperHttpClient,
    job: Job,
    cinema: CinemaConfig,
    *,
    now: datetime,
    clock: Callable[[], float],
    log: FilteringBoundLogger | None = None,
    debug_dir: Path | None = None,
    services: Services | None = None,
) -> CinemaResult:
    log = (log or get_logger()).bind(job=job, cinemaId=cinema.id)
    budget = CinemaBudget(cinema.id, clock=clock)
    ctx = RunContext(http=http, job=job, now=now, log=log, budget=budget, debug_dir=debug_dir)
    log.info("cinema.start", phase="start")
    services = services or Services()
    started_at = datetime.now(UTC)
    try:
        result = JOB_STEPS[job](ctx, cinema, services)
    except Exception as exc:
        status = run_status_for(exc)
        log.warning("cinema.end", phase="end", status=status, error=type(exc).__name__)
        result = CinemaResult(
            cinema.id, status, error=f"{type(exc).__name__}: {exc}", error_type=type(exc).__name__
        )
    else:
        log.info(
            "cinema.end",
            phase="end",
            status=result.status,
            movies=len(result.movies),
            showtimes=len(result.showtimes),
        )
    result.duration_s = budget.elapsed_s
    _report_health(services, job, cinema, result, started_at, now, log)
    return result


def _report_health(
    services: Services,
    job: Job,
    cinema: CinemaConfig,
    result: CinemaResult,
    started_at: datetime,
    now: datetime,
    log: FilteringBoundLogger,
) -> None:
    """``scrape_runs`` + ``cinemas.health`` (writing runs only), then alerts (§18.1)."""
    previous_success = None
    if services.db is not None:
        previous_success = last_success(services.db, cinema.id)
        record_run(
            services.db,
            RunRecord(
                job=job,
                cinema_id=cinema.id,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                status=result.status,
                counts={
                    "movies": len(result.normalized_movies),
                    "showtimes": len(result.normalized_showtimes),
                    "upserted": result.upserted,
                    "invalid": result.invalid,
                    "cancelled": result.cancelled,
                    "imagesUploaded": result.images_uploaded,
                    "imagesFailed": result.images_failed,
                },
                errors=[RunError(result.error_type or "Error", result.error)]
                if result.error
                else [],
                github_run_id=github_run_id(),
            ),
        )
    if services.alerter is None:
        return
    if result.ok:
        services.alerter.resolve(cinema.id, now)
    else:
        services.alerter.raise_alert(
            Alert(
                cinema_id=cinema.id,
                type=result.status,
                summary=result.error or result.status,
                state=f"{result.status}:{result.error_type or 'Error'}",
                run_url=run_url(),
                last_success=previous_success,
            ),
            now,
        )


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
    services: Services | None = None,
) -> RunReport:
    started = now or datetime.now(UTC)
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CINEMAS) as pool:
        results = list(
            pool.map(
                lambda c: run_cinema(
                    http,
                    job,
                    c,
                    now=started,
                    clock=clock,
                    log=log,
                    debug_dir=debug_dir,
                    services=services,
                ),
                cinemas,
            )
        )
    return RunReport(job=job, dry_run=dry_run, started_at=started, results=results)
