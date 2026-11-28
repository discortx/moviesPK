#!/usr/bin/env python3
"""Delete one cinema's data (plan P2-07a; used by §12.5, §17.3, §18.4 and the P4-05 drill).

    python scripts/purge_cinema.py --cinema <id> (--showtimes | --all) [--dry-run] [--yes]

* ``--showtimes``: the cinema's showtimes (rollback before a re-run, §17.3).
* ``--all``: also the ``cinemas`` document, the cinema's ``scrape_runs`` and its
  cinema-specific ``auto``/``pending`` aliases (removal request, §18.4). Refused while
  ``cinemas.yml`` still has ``enabled: true`` for it (the next run would bring it back).
* Never touched: ``movies`` (shared; the next ``full`` run recomputes ``nowShowing`` and
  ``lastShowingAt``), ``manual`` aliases (YAML is their source), R2 objects (movie-level,
  §11.3.5), other cinemas' data.

Every run first prints what it would delete. ``--dry-run`` stops there; otherwise the
operator re-types the cinema id (or passes ``--yes``); anything else aborts with no writes.
Reads ``MONGODB_URI_SCRAPER`` and ``MONGODB_DB``; never prints the URI. One structured log
line per run (``purge.done``) with the cinema, mode, dry-run flag, counts and database.

Exit codes: 0 done (or dry run), 1 aborted at the confirmation, 2 invalid input or refused.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from moviespk_scraper.core.config import CONFIG_DIR, ConfigError, load_config
from moviespk_scraper.core.logging import configure_logging, get_logger
from moviespk_scraper.db import repositories as repo
from moviespk_scraper.db.client import DB, DatabaseUnavailableError, DbSettings, connect

CINEMA_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CINEMA_ID_MAX = 80
EXIT_OK, EXIT_ABORTED, EXIT_INVALID = 0, 1, 2


def targets(cinema_id: str, mode: str) -> dict[str, dict[str, Any]]:
    """Collection → delete filter, in deletion order."""
    filters: dict[str, dict[str, Any]] = {repo.SHOWTIMES: {"cinemaId": cinema_id}}
    if mode == "all":
        filters[repo.SCRAPE_RUNS] = {"cinemaId": cinema_id}
        filters[repo.ALIASES] = {"cinemaId": cinema_id, "source": {"$in": ["auto", "pending"]}}
        filters[repo.CINEMAS] = {"_id": cinema_id}
    return filters


def _fail(message: str, code: int = EXIT_INVALID) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def purge(
    db: DB,
    cinema_id: str,
    mode: str,
    *,
    dry_run: bool,
    yes: bool,
    ask: Callable[[str], str] = input,
    config_dir: Path = CONFIG_DIR,
) -> int:
    if len(cinema_id) > CINEMA_ID_MAX or not CINEMA_ID.fullmatch(cinema_id):
        return _fail(f"--cinema {cinema_id!r} is not a cinema id (lowercase slug, at most 80)")
    if db[repo.CINEMAS].count_documents({"_id": cinema_id}, limit=1) == 0:
        return _fail(f"cinema {cinema_id!r} is not in the database")
    if mode == "all":
        try:
            configured = {c.id: c for c in load_config(config_dir).cinemas}
        except ConfigError as exc:
            return _fail(f"cannot read cinemas.yml: {exc}")
        cinema = configured.get(cinema_id)
        if cinema is not None and cinema.enabled:
            return _fail(
                f"{cinema_id} is still enabled in cinemas.yml; set enabled: false and merge "
                "first (the next run would bring it back)"
            )

    filters = targets(cinema_id, mode)
    counts = {name: db[name].count_documents(f) for name, f in filters.items()}
    print(f"purge --{mode} {cinema_id} in database {db.name!r} would delete:")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    print("  (movies, manual aliases, R2 objects and other cinemas are never touched)")

    log = get_logger()
    if dry_run:
        print("dry run: nothing deleted")
        log.info("purge.done", cinemaId=cinema_id, mode=mode, dryRun=True, deleted={}, db=db.name)
        return EXIT_OK
    if not yes:
        answer = ask(f"Type the cinema id ({cinema_id}) to delete, anything else aborts: ")
        if answer.strip() != cinema_id:
            print("aborted: nothing deleted")
            return EXIT_ABORTED

    deleted = {name: int(db[name].delete_many(f).deleted_count) for name, f in filters.items()}
    for name, count in deleted.items():
        print(f"deleted {name}: {count}")
    log.info("purge.done", cinemaId=cinema_id, mode=mode, dryRun=False, deleted=deleted, db=db.name)
    print("Record this run in the related GitHub issue (runbook §18.4 / §17.3).")
    return EXIT_OK


def main(argv: list[str] | None = None, ask: Callable[[str], str] = input) -> int:
    parser = argparse.ArgumentParser(description="Delete one cinema's data from MongoDB.")
    parser.add_argument("--cinema", required=True, help="cinema id")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--showtimes", action="store_true", help="only the cinema's showtimes")
    scope.add_argument(
        "--all", action="store_true", help="showtimes, cinema doc, run history, auto aliases"
    )
    parser.add_argument("--dry-run", action="store_true", help="only show what would go")
    parser.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    configure_logging("INFO", stream=sys.stderr)
    if len(args.cinema) > CINEMA_ID_MAX or not CINEMA_ID.fullmatch(args.cinema):
        return _fail(f"--cinema {args.cinema!r} is not a cinema id (lowercase slug, at most 80)")
    try:
        client, db = connect(DbSettings.from_env())
    except DatabaseUnavailableError as exc:
        return _fail(str(exc))
    try:
        return purge(
            db,
            args.cinema,
            "all" if args.all else "showtimes",
            dry_run=args.dry_run,
            yes=args.yes,
            ask=ask,
            config_dir=args.config_dir,
        )
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
