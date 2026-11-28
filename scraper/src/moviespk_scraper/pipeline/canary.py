"""Daily canary (plan §10.5 ``scrape-canary``, §18.1, P2-03).

Checks, each raising a GitHub-issue alert (``services/alerts.py``) and closing it again
once the condition clears:

1. **Evidence** per enabled cinema: every evidence path that was Allowed must still be
   allowed by robots.txt (alert ``robots``; the HTTP client refuses the path anyway), and
   the terms page must still have the recorded hash (alert ``terms-changed``; scraping
   continues until the owner reviews, unless the owner sets ``enabled: false``). A robots
   hash change without a verdict change is logged only. Both alerts are posted once per
   state and never repeated (``repeat_after=None``): the owner must review them. To clear
   one, re-run ``scripts/snapshot_evidence.py`` and update ``cinemas.yml``.
2. **Structural probe**: one known page per adapter (its first enabled cinema) must parse
   (alert ``probe`` on ``adapter-<id>``). Network errors are noted, not alerted: the
   hourly ``full`` runs already alert on those.
3. **Count rule**: the latest ``ok`` ``full`` run below 50% of the median of the 7 ``ok``
   runs before it → ``low-results``. Warm-up: no alert until 8 ``ok`` runs exist.
4. **Staleness**: no successful ``full`` run in 18 h → ``stale``; for seat-enabled
   cinemas, no successful ``seats`` run in 6 h → ``stale-seats``.
5. **Atlas storage**: data + indexes above 70% of 512 MB → ``storage`` on ``atlas``.
6. **Digest**: new provisional and unmatched titles of the last 24 h in one issue
   ``[digest] unmatched titles YYYY-MM-DD`` (PKT date); digests close after 7 days.
7. **Maintenance** (P2-10, ``pipeline/maintenance.py``): TMDB 6-month purge and R2 usage
   record daily, orphan-image cleanup on UTC day 1; functions in :data:`MAINTENANCE_HOOKS`,
   run last.

Findings are issues, not job failures: the job's exit code is 1 only when a check could
not run (for example the database is unreachable).
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

from structlog.typing import FilteringBoundLogger

from ..adapters.base import RunContext
from ..adapters.registry import get_adapter
from ..core.circuit_breaker import CinemaBudget
from ..core.clock import pkt_date
from ..core.config import CinemaConfig
from ..core.errors import SchemaDriftError
from ..core.evidence import terms_sha256
from ..core.http import ScraperHttpClient
from ..core.robots import RobotsDisallowedError
from ..db import repositories as repo
from ..db.client import DB
from ..services.alerts import REPEAT_AFTER, Alert, Alerter, run_url
from .maintenance import Bucket, MaintenanceCounts, run_maintenance

COUNT_HISTORY = 7  # runs in the median
COUNT_RATIO = 0.5
STALE_FULL = timedelta(hours=18)
STALE_SEATS = timedelta(hours=6)
ATLAS_LIMIT_BYTES = 512 * 1024 * 1024
ATLAS_ALERT_RATIO = 0.7
DIGEST_WINDOW = timedelta(hours=24)
DIGEST_LIFETIME = timedelta(days=7)

EVIDENCE_TYPES = ("robots", "terms-changed")
DB_CINEMA_TYPES = ("low-results", "stale", "stale-seats")


@dataclass
class CanaryReport:
    alerts: list[Alert] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Checks that could not run at all (these fail the job).
    errors: list[str] = field(default_factory=list)
    storage_bytes: int | None = None
    digest_titles: int = 0
    maintenance: MaintenanceCounts | None = None

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0


@dataclass(frozen=True)
class CanaryContext:
    """What a maintenance hook gets (P2-10)."""

    db: DB | None
    now: datetime
    dry_run: bool
    report: CanaryReport
    log: FilteringBoundLogger
    alerter: Alerter | None = None
    bucket: Bucket | None = None


def maintenance_hook(ctx: CanaryContext) -> None:
    """P2-10: TMDB purge, R2 usage record, orphan cleanup on UTC day 1."""
    if ctx.db is None:
        ctx.report.notes.append("maintenance skipped (no database)")
        return
    counts = run_maintenance(ctx.db, ctx.bucket, ctx.alerter, ctx.now, dry_run=ctx.dry_run)
    ctx.report.maintenance = counts
    ctx.report.notes.extend(counts.notes)
    if counts.r2_bytes is not None and counts.r2_bytes > 1024**3:
        ctx.report.alerts.append(Alert("r2", "storage", "bucket above 1 GB", "storage"))


MAINTENANCE_HOOKS: list[Callable[[CanaryContext], None]] = [maintenance_hook]


def _alert(
    subject: str,
    kind: str,
    summary: str,
    state: str,
    *,
    repeat_after: timedelta | None = REPEAT_AFTER,
    last_success: datetime | None = None,
) -> Alert:
    return Alert(
        cinema_id=subject,
        type=kind,
        summary=summary,
        state=state,
        run_url=run_url(),
        last_success=last_success,
        repeat_after=repeat_after,
    )


# --- 1. evidence -------------------------------------------------------------------------


def evidence_alerts(
    http: ScraperHttpClient,
    cinema: CinemaConfig,
    log: FilteringBoundLogger,
    terms_cache: dict[str, str | None],
) -> tuple[list[Alert], list[str]]:
    """Robots and terms re-check for one cinema: (alerts, notes)."""
    alerts: list[Alert] = []
    notes: list[str] = []
    ev = cinema.evidence
    base = str(cinema.base_url)
    if cinema.robots_policy == "respect":
        policy = http.robots_for(base, min_delay_ms=cinema.min_delay_ms)
        if policy.blocked:
            notes.append(f"{cinema.id}: robots.txt unreachable; evidence not re-checked")
        else:
            newly = [
                e.path
                for e in ev.endpoints
                if e.allowed and not policy.can_fetch(urljoin(base, e.path))
            ]
            if newly:
                alerts.append(
                    _alert(
                        cinema.id,
                        "robots",
                        f"robots.txt now disallows {', '.join(newly)} (allowed in the "
                        f"evidence of {ev.checked_at}). The scraper refuses these paths; "
                        "review and set enabled: false or update the evidence.",
                        "robots:" + ",".join(sorted(newly)),
                        repeat_after=None,
                    )
                )
            elif policy.body_sha256() != ev.robots_sha256:
                log.info("canary.robots_hash_changed", cinemaId=cinema.id)
                notes.append(f"{cinema.id}: robots.txt changed, verdicts unchanged (logged only)")
    if ev.terms_url and ev.terms_sha256:
        url = str(ev.terms_url)
        if url not in terms_cache:
            terms_cache[url] = _terms_hash(http, cinema, url, notes)
        current = terms_cache[url]
        if current is not None and current != ev.terms_sha256:
            alerts.append(
                _alert(
                    cinema.id,
                    "terms-changed",
                    f"The terms page {url} changed since {ev.checked_at} (sha256 "
                    f"{ev.terms_sha256[:8]}… → {current[:8]}…). Scraping continues until "
                    "the owner reviews it.",
                    f"terms:{current[:16]}",
                    repeat_after=None,
                )
            )
    return alerts, notes


def _terms_hash(
    http: ScraperHttpClient, cinema: CinemaConfig, url: str, notes: list[str]
) -> str | None:
    try:
        resp = http.get(
            url,
            min_delay_ms=cinema.min_delay_ms,
            robots_policy=cinema.robots_policy,
            permission_ref=cinema.permission_ref,
        )
    except RobotsDisallowedError:
        notes.append(f"{cinema.id}: terms page is disallowed by robots.txt; not fetched")
        return None
    except Exception as exc:
        notes.append(f"{cinema.id}: terms page not fetched ({type(exc).__name__})")
        return None
    if resp.status_code != 200:
        notes.append(f"{cinema.id}: terms page answered {resp.status_code}")
        return None
    return terms_sha256(resp.text)


# --- 2. structural probe -----------------------------------------------------------------


def probe_targets(cinemas: Sequence[CinemaConfig]) -> dict[str, CinemaConfig]:
    """The first enabled cinema of each adapter."""
    targets: dict[str, CinemaConfig] = {}
    for cinema in cinemas:
        targets.setdefault(cinema.adapter, cinema)
    return targets


@dataclass(frozen=True)
class ProbeResult:
    note: str
    alert: Alert | None = None
    #: False when the page could not be fetched: nothing is concluded either way.
    ran: bool = True


def probe(
    http: ScraperHttpClient,
    adapter_id: str,
    cinema: CinemaConfig,
    now: datetime,
    log: FilteringBoundLogger,
    debug_dir: Path | None,
) -> ProbeResult:
    """Fetch and parse one adapter's known page."""
    ctx = RunContext(
        http=http,
        job="canary",
        now=now,
        log=log,
        budget=CinemaBudget(cinema.id),
        debug_dir=debug_dir,
    )
    adapter = get_adapter(adapter_id)
    try:
        movies = adapter.list_movies(ctx, cinema)
        shows = adapter.list_showtimes(ctx, cinema)
    except SchemaDriftError as exc:
        return ProbeResult(
            f"probe {adapter_id} ({cinema.id}): drift",
            _alert(
                f"adapter-{adapter_id}",
                "probe",
                f"The {adapter_id} page of {cinema.id} no longer parses: {exc}",
                f"probe:{type(exc).__name__}",
            ),
        )
    except Exception as exc:
        return ProbeResult(
            f"probe {adapter_id} ({cinema.id}): not fetched ({type(exc).__name__})", ran=False
        )
    return ProbeResult(
        f"probe {adapter_id} ({cinema.id}): {len(movies)} movies, {len(shows)} showtimes"
    )


# --- 3-5. database rules (pure) -----------------------------------------------------------


def count_alert(cinema_id: str, counts_newest_first: Sequence[int]) -> Alert | None:
    """Latest ``ok`` count vs the median of the 7 ``ok`` runs before it. Needs 8 runs."""
    if len(counts_newest_first) < COUNT_HISTORY + 1:
        return None  # warm-up
    latest = counts_newest_first[0]
    median = statistics.median(counts_newest_first[1 : COUNT_HISTORY + 1])
    if latest >= COUNT_RATIO * median:
        return None
    return _alert(
        cinema_id,
        "low-results",
        f"The latest full run found {latest} showtimes, below 50% of the 7-run median "
        f"({median:g}).",
        "low-results",
    )


def stale_alert(
    cinema_id: str, kind: str, last_success: datetime | None, now: datetime, limit: timedelta
) -> Alert | None:
    if last_success is not None and now - last_success <= limit:
        return None
    hours = int(limit.total_seconds() // 3600)
    job = "seats" if kind == "stale-seats" else "full"
    when = "never (in the 30-day run history)" if last_success is None else last_success.isoformat()
    return _alert(
        cinema_id,
        kind,
        f"No successful {job} run for over {hours} h. Last success: {when}.",
        kind,
        last_success=last_success,
    )


def storage_alert(used_bytes: int) -> Alert | None:
    if used_bytes <= ATLAS_ALERT_RATIO * ATLAS_LIMIT_BYTES:
        return None
    mb = used_bytes / 1024 / 1024
    return _alert(
        "atlas",
        "storage",
        f"Atlas data + indexes use {mb:.0f} MB, above 70% of the 512 MB free tier.",
        "storage",
    )


def digest_body(titles: Sequence[dict[str, object]]) -> str:
    lines = [
        "New provisional and unmatched titles from the last 24 h. Review them with",
        "`python scripts/review_aliases.py` (runbook: Alias review).",
        "",
    ]
    for t in titles:
        lines.append(f"- **{t.get('title')}** (`{t.get('slug')}`, {t.get('matchStatus')})")
    lines += ["", "_Closed automatically after 7 days._"]
    return "\n".join(lines)


# --- orchestration -----------------------------------------------------------------------


def run_canary(
    http: ScraperHttpClient,
    cinemas: Sequence[CinemaConfig],
    *,
    db: DB | None,
    alerter: Alerter | None,
    now: datetime,
    log: FilteringBoundLogger,
    dry_run: bool = False,
    debug_dir: Path | None = None,
    bucket: Bucket | None = None,
) -> CanaryReport:
    report = CanaryReport()

    def emit(subject: str, types: tuple[str, ...], found: Sequence[Alert]) -> None:
        report.alerts.extend(found)
        if alerter is None:
            return
        for a in found:
            alerter.raise_alert(a, now)
        cleared = tuple(t for t in types if t not in {a.type for a in found})
        if cleared:
            alerter.resolve(subject, now, cleared)

    terms_cache: dict[str, str | None] = {}
    for cinema in cinemas:
        found, notes = evidence_alerts(http, cinema, log, terms_cache)
        report.notes.extend(notes)
        emit(cinema.id, EVIDENCE_TYPES, found)

    for adapter_id, cinema in probe_targets(cinemas).items():
        result = probe(http, adapter_id, cinema, now, log, debug_dir)
        report.notes.append(result.note)
        if result.ran:
            emit(f"adapter-{adapter_id}", ("probe",), [result.alert] if result.alert else [])

    if db is None:
        report.notes.append("database checks skipped (no database)")
    else:
        try:
            _database_checks(db, cinemas, now, report, emit, alerter)
        except Exception as exc:
            report.errors.append(f"database checks failed: {type(exc).__name__}")

    ctx = CanaryContext(
        db=db, now=now, dry_run=dry_run, report=report, log=log, alerter=alerter, bucket=bucket
    )
    for hook in MAINTENANCE_HOOKS:
        try:
            hook(ctx)
        except Exception as exc:
            report.errors.append(f"maintenance hook {hook.__name__} failed: {type(exc).__name__}")
    return report


def _database_checks(
    db: DB,
    cinemas: Sequence[CinemaConfig],
    now: datetime,
    report: CanaryReport,
    emit: Callable[[str, tuple[str, ...], Sequence[Alert]], None],
    alerter: Alerter | None,
) -> None:
    for cinema in cinemas:
        found = [
            a
            for a in (
                count_alert(
                    cinema.id, repo.recent_ok_showtime_counts(db, cinema.id, COUNT_HISTORY + 1)
                ),
                stale_alert(
                    cinema.id, "stale", repo.last_success_at(db, cinema.id, "full"), now, STALE_FULL
                ),
                stale_alert(
                    cinema.id,
                    "stale-seats",
                    repo.last_success_at(db, cinema.id, "seats"),
                    now,
                    STALE_SEATS,
                )
                if cinema.seats_allowed
                else None,
            )
            if a is not None
        ]
        emit(cinema.id, DB_CINEMA_TYPES, found)

    report.storage_bytes = repo.storage_bytes(db)
    found_storage = storage_alert(report.storage_bytes)
    emit("atlas", ("storage",), [found_storage] if found_storage else [])

    titles = repo.new_unresolved_movies(db, now - DIGEST_WINDOW)
    report.digest_titles = len(titles)
    if alerter is not None:
        if titles:
            alerter.post_digest(
                f"[digest] unmatched titles {pkt_date(now).isoformat()}", digest_body(titles)
            )
        alerter.close_digests(now - DIGEST_LIFETIME)
