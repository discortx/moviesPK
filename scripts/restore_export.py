#!/usr/bin/env python3
"""Restore a weekly export (plan P2-05, §17.3, §19; runbook "Restore from export").

    python scripts/restore_export.py --input <export dir> --target-db <name> [--force]

1. Validates the **whole** export first: manifest present with a known schema version,
   all three collection files present, gzip and JSON valid, checksums and document counts
   equal to the manifest. Any problem exits 1 with a message and writes nothing.
2. Refuses the production database ``moviespk`` unless ``--force`` is given.
3. Replaces ``movies``, ``movie_aliases`` and ``cinemas`` in the target database with the
   export's documents (other collections are not touched; showtimes come back with the
   next ``full`` run), then runs ``scripts/create_indexes.js`` (or prints the command
   when Node.js is not installed).

The connection string comes from ``MONGODB_URI_SCRAPER`` and is never printed.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from pymongo.errors import PyMongoError

from moviespk_scraper.db.client import DatabaseUnavailableError, DbSettings, connect
from moviespk_scraper.services.export import COLLECTIONS, ExportError, load_export

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DB = "moviespk"
DB_NAME = re.compile(r"^[A-Za-z0-9_-]{1,63}$")
EXIT_OK, EXIT_INVALID, EXIT_USAGE = 0, 1, 2


def _fail(message: str, code: int = EXIT_INVALID) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def create_indexes(target_db: str) -> None:
    node = shutil.which("node")
    command = "node scripts/create_indexes.js"
    if node is None:
        print(f"note: Node.js not found; run with MONGODB_DB={target_db}: {command}")
        return
    env = os.environ | {"MONGODB_DB": target_db}
    proc = subprocess.run(  # noqa: S603 (fixed argv: node and a repository script, no shell)
        [node, "scripts/create_indexes.js"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"warning: {command} failed; run it again with MONGODB_DB={target_db}")
    else:
        print("indexes: ensured (scripts/create_indexes.js)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore a MoviesPK export into a database.")
    parser.add_argument("--input", type=Path, required=True, help="the export directory")
    parser.add_argument("--target-db", required=True, help="database to restore into")
    parser.add_argument(
        "--force", action="store_true", help=f"allow restoring into {PRODUCTION_DB!r}"
    )
    parser.add_argument(
        "--skip-indexes", action="store_true", help="do not run scripts/create_indexes.js"
    )
    args = parser.parse_args(argv)

    if not DB_NAME.fullmatch(args.target_db):
        return _fail(f"--target-db {args.target_db!r} is not a valid database name", EXIT_USAGE)
    if args.target_db == PRODUCTION_DB and not args.force:
        return _fail(
            f"refusing to overwrite the production database {PRODUCTION_DB!r} without --force",
            EXIT_USAGE,
        )

    try:
        manifest, docs = load_export(args.input)
    except ExportError as exc:
        return _fail(f"export not restored, nothing written: {exc}")
    print(f"export of {manifest.get('exportedAt')}: valid")

    uri = os.environ.get("MONGODB_URI_SCRAPER", "").strip()
    if not uri:
        return _fail("set MONGODB_URI_SCRAPER (the target cluster)", EXIT_USAGE)
    try:
        client, db = connect(DbSettings(uri, args.target_db))
    except DatabaseUnavailableError as exc:
        return _fail(f"database unavailable: {exc}", EXIT_USAGE)
    try:
        for name in COLLECTIONS:
            db[name].delete_many({})
            if docs[name]:
                db[name].insert_many(docs[name], ordered=True)
            restored = db[name].count_documents({})
            print(f"{name}: {restored} documents")
            if restored != len(docs[name]):
                return _fail(f"{name}: restored {restored}, expected {len(docs[name])}")
    except PyMongoError as exc:
        return _fail(f"restore failed part-way ({type(exc).__name__}); run it again")
    finally:
        client.close()

    if args.skip_indexes:
        print("indexes: skipped")
    else:
        create_indexes(args.target_db)
    print(f"done. Next: dispatch scrape-full (showtimes) against {args.target_db}.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
