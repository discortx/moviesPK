"""``cinemas.yml`` → ``cinemas`` (plan §8.1, P1-10), at the start of every ``full`` run.

YAML wins: every configured cinema is upserted with its current fields; a cinema that is
disabled in YAML, or no longer in YAML at all, gets ``enabled: false`` and is **not**
deleted (removal is ``scripts/purge_cinema.py``, §18.4). Run state (``health``,
``lastScrapedAt``) is only initialized on insert, never overwritten here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pymongo import UpdateOne

from ..core.config import CinemaConfig
from ..db import repositories as repo
from ..db.client import DB


@dataclass(frozen=True)
class SyncResult:
    upserted: int
    disabled_missing: int


def cinema_update(cinema: CinemaConfig, now: datetime) -> UpdateOne:
    fields: dict[str, Any] = {
        "chain": cinema.chain,
        "name": cinema.name,
        "city": cinema.city,
        "address": cinema.address,
        "location": {"type": "Point", "coordinates": [cinema.location[0], cinema.location[1]]},
        "websiteUrl": cinema.base_url,
        "enabled": cinema.enabled,
        "seatsEnabled": cinema.seats_allowed,
        "updatedAt": now,
    }
    unset: dict[str, str] = {}
    for key, value in (
        ("phone", cinema.phone),
        ("bookingUrlTemplate", cinema.booking_url_template),
    ):
        if value:
            fields[key] = value
        else:
            unset[key] = ""  # optional fields are omitted, never empty strings (§8.1)
    update: dict[str, Any] = {
        "$set": fields,
        "$setOnInsert": {
            "createdAt": now,
            "facilities": [],
            "health": {"status": "unknown"},
        },
    }
    if unset:
        update["$unset"] = unset
    return UpdateOne({"_id": cinema.id}, update, upsert=True)


def sync_cinemas(db: DB, cinemas: Sequence[CinemaConfig], now: datetime) -> SyncResult:
    repo.bulk_upsert(db, repo.CINEMAS, [cinema_update(c, now) for c in cinemas])
    configured = {c.id for c in cinemas}
    missing = repo.cinema_ids(db) - configured
    return SyncResult(
        upserted=len(cinemas), disabled_missing=repo.disable_cinemas(db, missing, now)
    )
