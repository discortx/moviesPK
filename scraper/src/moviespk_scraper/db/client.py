"""MongoDB client (plan §9.2-style settings for the scraper, P1-10).

``maxPoolSize=5`` and ``serverSelectionTimeoutMS=5000``; :func:`connect` pings once so a
wrong URI or an unreachable cluster fails the run at the start, not halfway through.
The URI is never logged or printed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

Document = dict[str, Any]
DB = Database[Document]

MAX_POOL_SIZE = 5
SERVER_SELECTION_TIMEOUT_MS = 5000


class DatabaseUnavailableError(RuntimeError):
    """MongoDB could not be reached or the settings are missing (message has no URI)."""


@dataclass(frozen=True)
class DbSettings:
    uri: str
    name: str

    @classmethod
    def from_env(cls) -> DbSettings:
        uri = os.environ.get("MONGODB_URI_SCRAPER", "").strip()
        name = os.environ.get("MONGODB_DB", "").strip()
        if not uri or not name:
            raise DatabaseUnavailableError("set MONGODB_URI_SCRAPER and MONGODB_DB")
        return cls(uri, name)

    def __repr__(self) -> str:  # never show the URI (it holds the password)
        return f"DbSettings(name={self.name!r})"


def connect(settings: DbSettings) -> tuple[MongoClient[Document], DB]:
    """Open the client and ping; raise :class:`DatabaseUnavailableError` on failure."""
    client: MongoClient[Document] = MongoClient(
        settings.uri,
        maxPoolSize=MAX_POOL_SIZE,
        serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
        tz_aware=True,
    )
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        client.close()
        raise DatabaseUnavailableError(
            f"MongoDB not reachable ({type(exc).__name__}); database {settings.name!r}"
        ) from None
    return client, client[settings.name]
