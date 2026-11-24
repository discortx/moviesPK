"""Integration fixtures: need MongoDB at MONGODB_URI_SCRAPER (CI: mongo:7 service)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError


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
