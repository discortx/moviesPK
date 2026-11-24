"""Integration: scripts/create_indexes.js and scripts/seed_dev.py (plan P0-06)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pymongo import MongoClient

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]


def _env(uri: str, db: str) -> dict[str, str]:
    return os.environ | {"MONGODB_URI_SCRAPER": uri, "MONGODB_DB": db}


def _run(cmd: list[str], uri: str, db: str) -> str:
    proc = subprocess.run(
        cmd, cwd=ROOT, env=_env(uri, db), capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_index_script_is_idempotent(mongo_uri: str, db_name: str) -> None:
    node = shutil.which("node")
    assert node
    first = _run([node, "scripts/create_indexes.js"], mongo_uri, db_name)
    second = _run([node, "scripts/create_indexes.js"], mongo_uri, db_name)
    assert first == second
    assert "expireAfterSeconds: 0" in second
    assert mongo_uri not in second
    with MongoClient(mongo_uri) as client:
        ttl = {
            ix["name"]: ix
            for ix in client[db_name]["showtimes"].list_indexes()
            if "expireAfterSeconds" in ix
        }
        assert ttl["expireAt_ttl"]["expireAfterSeconds"] == 0
        names = {ix["name"] for ix in client[db_name]["movies"].list_indexes()}
        assert {"tmdbId_unique", "localKey_unique", "slug_unique", "title_text"} <= names


def _snapshot(uri: str, db: str) -> str:
    with MongoClient(uri) as client:
        data: dict[str, Any] = {}
        for name in ("cinemas", "movies", "showtimes"):
            docs = (
                client[db][name]
                .find({}, {"lastSeenAt": 0, "createdAt": 0, "updatedAt": 0, "lastShowingAt": 0})
                .sort("_id")
            )
            data[name] = [json.dumps(d, default=str, sort_keys=True) for d in docs]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()


def test_seed_is_idempotent(mongo_uri: str, db_name: str) -> None:
    out = _run([sys.executable, "scripts/seed_dev.py"], mongo_uri, db_name)
    assert "showtimes: 28 upserted" in out
    first = _snapshot(mongo_uri, db_name)
    _run([sys.executable, "scripts/seed_dev.py"], mongo_uri, db_name)
    assert _snapshot(mongo_uri, db_name) == first
    with MongoClient(mongo_uri) as client:
        showtimes = client[db_name]["showtimes"]
        assert showtimes.count_documents({}) == 28
        assert showtimes.count_documents({"hall": {"$exists": False}}) > 0
        assert showtimes.count_documents({"hall": ""}) == 0


def test_seed_refuses_non_dev_database(mongo_uri: str) -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/seed_dev.py"],
        cwd=ROOT,
        env=_env(mongo_uri, "moviespk"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "refusing" in proc.stderr
