#!/usr/bin/env python3
"""Check the MongoDB users' privileges (plan P0-04). Prints OK or FAIL; never the URI.

    MONGODB_URI_SCRAPER=... MONGODB_URI_API=... MONGODB_DB=moviespk_dev \
        python scripts/check_db_access.py

* the scraper user must be able to write (insert and delete a probe document);
* the API user must be able to read and must be **rejected** on write.
Either URI may be omitted to skip that check. Exit code 1 if any check fails.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError

PROBE_COLLECTION = "_access_check"


def _client(uri: str) -> MongoClient[dict[str, Any]]:
    return MongoClient(uri, serverSelectionTimeoutMS=10_000)


def check_scraper(uri: str, db_name: str) -> bool:
    try:
        with _client(uri) as client:
            coll = client[db_name][PROBE_COLLECTION]
            result = coll.insert_one({"probe": "scraper"})
            coll.delete_one({"_id": result.inserted_id})
        return True
    except PyMongoError as exc:
        print(f"  scraper error: {type(exc).__name__}", file=sys.stderr)
        return False


def check_api(uri: str, db_name: str) -> bool:
    try:
        with _client(uri) as client:
            db = client[db_name]
            db.list_collection_names()
            try:
                db[PROBE_COLLECTION].insert_one({"probe": "api"})
            except OperationFailure:
                return True  # write rejected, as required
            print("  api user could WRITE (must be read-only)", file=sys.stderr)
            return False
    except PyMongoError as exc:
        print(f"  api error: {type(exc).__name__}", file=sys.stderr)
        return False


def main() -> int:
    db_name = os.environ.get("MONGODB_DB", "moviespk_dev")
    ok = True
    for label, env, check in (
        ("scraper user can write", "MONGODB_URI_SCRAPER", check_scraper),
        ("api user is read-only", "MONGODB_URI_API", check_api),
    ):
        uri = os.environ.get(env)
        if not uri:
            print(f"SKIP {label} ({env} not set)")
            continue
        passed = check(uri, db_name)
        ok &= passed
        print(f"{'OK  ' if passed else 'FAIL'} {label}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
