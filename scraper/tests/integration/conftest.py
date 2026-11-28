"""Integration fixtures: need MongoDB at MONGODB_URI_SCRAPER (CI: mongo:7 service)."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from moviespk_scraper.db.client import DB, DbSettings, connect

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def mongo_uri() -> str:
    uri = os.environ.get("MONGODB_URI_SCRAPER", "mongodb://localhost:27017")
    try:
        with MongoClient(uri, serverSelectionTimeoutMS=2_000) as client:
            client.admin.command("ping")
    except PyMongoError:
        pytest.skip("MongoDB not reachable; integration tests skipped")
    return uri


@pytest.fixture
def db_name(mongo_uri: str) -> Iterator[str]:
    name = f"moviespk_test_{uuid.uuid4().hex[:8]}_dev"
    yield name
    client: MongoClient[dict[str, Any]] = MongoClient(mongo_uri)
    client.drop_database(name)
    client.close()


@pytest.fixture
def db(mongo_uri: str, db_name: str) -> Iterator[DB]:
    """A fresh database with the real indexes (scripts/create_indexes.js)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed (needed for scripts/create_indexes.js)")
    env = os.environ | {"MONGODB_URI_SCRAPER": mongo_uri, "MONGODB_DB": db_name}
    proc = subprocess.run(
        [node, "scripts/create_indexes.js"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    client, database = connect(DbSettings(mongo_uri, db_name))
    yield database
    client.close()
