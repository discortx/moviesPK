"""Command line (plan P1-04)::

    python -m moviespk_scraper run --job {full|seats|canary|export} [--cinema ID]
                                   [--dry-run] [--offline FIXTURE_DIR] [--rebuild-images]

Exit codes: 0 = all ok, 1 = any cinema failed/blocked/drift, 2 = config or usage error.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from . import __version__
from .core.clock import PKT
from .core.config import CONFIG_DIR, ConfigError, load_config
from .core.http import ScraperHttpClient
from .core.logging import configure_logging
from .core.offline import FixtureTransport, captured_at
from .pipeline.match import Alias, AliasTable, Matcher
from .pipeline.normalize import NormalizedShowtime
from .runner import CinemaResult, RunReport, Services, run_job
from .services.tmdb import TmdbClient

JOBS = ("full", "seats", "canary", "export")
IMPLEMENTED_JOBS = ("full",)
OFFLINE_USER_AGENT = "MoviesPKBot/1.0 (+offline fixtures)"
SAMPLE_ROWS = 5

EXIT_OK, EXIT_CINEMA_FAILED, EXIT_CONFIG = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="moviespk_scraper",
        description="MoviesPK scraper: collects cinema showtimes into MongoDB.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a job")
    run.add_argument("--job", choices=JOBS, required=True, help="job to run")
    run.add_argument("--cinema", help="run only this cinema id")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="run everything except DB writes, R2 writes and issue posting; print a summary",
    )
    run.add_argument(
        "--offline",
        type=Path,
        metavar="FIXTURE_DIR",
        help="serve HTTP from a saved fixture directory instead of the network",
    )
    run.add_argument(
        "--rebuild-images",
        action="store_true",
        help="ignore the unchanged-poster shortcut (manual recovery only)",
    )
    run.add_argument(
        "--debug-dir",
        type=Path,
        default=Path("debug"),
        help="where raw payloads are kept when parsing fails (uploaded as an artifact)",
    )
    run.add_argument("--config-dir", type=Path, default=CONFIG_DIR, help=argparse.SUPPRESS)
    return parser


def _error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return EXIT_CONFIG


def print_report(report: RunReport, out: TextIO) -> None:
    mode = "dry run" if report.dry_run else "run"
    out.write(f"{report.job} {mode} at {report.started_at.isoformat(timespec='seconds')}\n")
    for r in report.results:
        out.write(
            f"\n[{r.status}] {r.cinema_id}: {len(r.movies)} movies, "
            f"{len(r.normalized_showtimes)} valid showtimes, {r.invalid} invalid "
            f"({r.duration_s:.1f} s)\n"
        )
        if r.error:
            out.write(f"  error: {r.error}\n")
        if r.matches:
            counts = Counter(m.status for m in r.matches.values())
            out.write(
                f"  matches: {counts['matched']} matched, {counts['provisional']} provisional, "
                f"{counts['unmatched']} unmatched\n"
            )
            review = sorted(k for k, m in r.matches.items() if m.status != "matched")
            if review:
                out.write(f"  to review: {', '.join(review)}\n")
        for s in _samples(r):
            local = s.starts_at.astimezone(PKT).strftime("%Y-%m-%d %H:%M")
            hall = f" · {s.hall}" if s.hall else ""
            out.write(f"  {local} PKT  {s.movie_title}{hall} · {s.format} · {s.language}\n")
    failed = [r.cinema_id for r in report.results if not r.ok]
    out.write(f"\n{len(report.results) - len(failed)} ok, {len(failed)} not ok")
    out.write(f" ({', '.join(failed)})\n" if failed else "\n")


def _samples(result: CinemaResult) -> list[NormalizedShowtime]:
    return sorted(result.normalized_showtimes, key=lambda s: s.starts_at)[:SAMPLE_ROWS]


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.job not in IMPLEMENTED_JOBS:
        return _error(f"job {args.job!r} is not implemented yet")
    if not args.dry_run:
        return _error(
            "only --dry-run is available until the pipeline writes to the database "
            "(plan P1-07 … P1-11)"
        )

    try:
        config = load_config(args.config_dir)
    except ConfigError as exc:
        return _error(str(exc))

    if args.cinema:
        try:
            cinemas = [config.cinema(args.cinema)]
        except KeyError:
            return _error(f"unknown cinema {args.cinema!r}")
        if not cinemas[0].enabled and not args.dry_run:
            return _error(f"cinema {args.cinema!r} is disabled; only --dry-run may run it")
    else:
        cinemas = list(config.enabled_cinemas)
        if not cinemas:
            print("no enabled cinemas; nothing to do")
            return EXIT_OK

    transport = None
    now = None
    user_agent = os.environ.get("SCRAPER_USER_AGENT", "").strip()
    sleep = time.sleep
    if args.offline is not None:
        try:
            transport = FixtureTransport(args.offline)
            now = captured_at(args.offline)
        except (OSError, ValueError, KeyError) as exc:
            return _error(f"cannot load fixtures from {args.offline}: {exc}")
        user_agent = user_agent or OFFLINE_USER_AGENT
        sleep = lambda _s: None  # noqa: E731 (fixtures need no politeness delay)
    elif not user_agent:
        return _error("set SCRAPER_USER_AGENT (MoviesPKBot/1.0 (+<repo URL>; <contact email>))")

    configure_logging(os.environ.get("LOG_LEVEL", "INFO"), stream=sys.stderr)
    tmdb_key = os.environ.get("TMDB_API_KEY", "").strip()
    # Offline runs never reach the network, TMDB included; aliases still apply.
    tmdb = TmdbClient(tmdb_key) if tmdb_key and args.offline is None else None
    aliases = AliasTable(manual=[Alias.from_config(a) for a in config.aliases])
    services = Services(matcher=Matcher(tmdb, aliases))
    try:
        with ScraperHttpClient(user_agent, transport=transport, sleep=sleep) as http:
            report = run_job(
                http,
                args.job,
                cinemas,
                dry_run=args.dry_run,
                clock=time.monotonic,
                debug_dir=args.debug_dir,
                now=now,
                services=services,
            )
    finally:
        if tmdb is not None:
            tmdb.close()
    if tmdb is None:
        reason = "offline run" if args.offline is not None else "TMDB_API_KEY not set"
        print(f"note: TMDB matching skipped ({reason}); only aliases were applied")
    print_report(report, sys.stdout)
    return report.exit_code
