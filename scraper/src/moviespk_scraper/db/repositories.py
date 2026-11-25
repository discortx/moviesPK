"""Collection access (plan §8.1, §8.4, P1-10). Writes are idempotent upserts by
deterministic id; nothing here deletes documents."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from pymongo import UpdateOne
from pymongo.results import BulkWriteResult

from ..models.vocab import AliasSource
from .client import DB, Document

CINEMAS = "cinemas"
MOVIES = "movies"
SHOWTIMES = "showtimes"
ALIASES = "movie_aliases"
SCRAPE_RUNS = "scrape_runs"


def bulk_upsert(db: DB, collection: str, ops: Sequence[UpdateOne]) -> BulkWriteResult | None:
    """Unordered bulk write; one failing document does not stop the others (§8.4)."""
    if not ops:
        return None
    return db[collection].bulk_write(list(ops), ordered=False)


# --- cinemas ------------------------------------------------------------------------------


def cinema_ids(db: DB) -> set[str]:
    return {str(d["_id"]) for d in db[CINEMAS].find({}, {"_id": 1})}


def disable_cinemas(db: DB, ids: Iterable[str], now: datetime) -> int:
    ids = list(ids)
    if not ids:
        return 0
    result = db[CINEMAS].update_many(
        {"_id": {"$in": ids}, "enabled": {"$ne": False}},
        {"$set": {"enabled": False, "updatedAt": now}},
    )
    return int(result.modified_count)


# --- movies --------------------------------------------------------------------------------


def find_movie(
    db: DB, *, tmdb_id: int | None = None, local_key: str | None = None
) -> Document | None:
    if tmdb_id is not None:
        found = db[MOVIES].find_one({"tmdbId": tmdb_id})
        if found is not None:
            return found
    if local_key is not None:
        return db[MOVIES].find_one({"localKey": local_key})
    return None


def slug_taken(db: DB, slug: str, *, except_id: Any = None) -> bool:
    query: Document = {"$or": [{"slug": slug}, {"localKey": slug}]}
    if except_id is not None:
        query["_id"] = {"$ne": except_id}
    return db[MOVIES].count_documents(query, limit=1) > 0


def upsert_movie(
    db: DB, movie_id: Any, set_fields: Document, on_insert: Document, unset: Sequence[str] = ()
) -> None:
    update: Document = {"$set": set_fields, "$setOnInsert": on_insert}
    if unset:
        update["$unset"] = dict.fromkeys(unset, "")
    db[MOVIES].update_one({"_id": movie_id}, update, upsert=True)


def raise_last_showing(db: DB, latest: dict[Any, datetime]) -> None:
    """``lastShowingAt`` only moves forward (``$max``)."""
    ops = [
        UpdateOne({"_id": mid}, {"$max": {"lastShowingAt": when}}) for mid, when in latest.items()
    ]
    bulk_upsert(db, MOVIES, ops)


# --- aliases -------------------------------------------------------------------------------


def load_aliases(db: DB) -> list[Document]:
    return list(db[ALIASES].find({}))


def alias_id(alias: str, cinema_id: str | None) -> str:
    """``_id`` is the normalized alias; a cinema-specific alias is ``alias|cinemaId``."""
    return f"{alias}|{cinema_id}" if cinema_id else alias


def alias_op(
    alias: str,
    *,
    movie_key: str,
    source: AliasSource,
    confidence: float | None,
    cinema_id: str | None,
    now: datetime,
) -> UpdateOne:
    doc: Document = {"movieKey": movie_key, "source": source}
    if confidence is not None:
        doc["confidence"] = round(confidence, 1)
    if cinema_id:
        doc["cinemaId"] = cinema_id
    return UpdateOne(
        {"_id": alias_id(alias, cinema_id)},
        {"$set": doc, "$setOnInsert": {"createdAt": now}},
        upsert=True,
    )


# --- scrape runs ---------------------------------------------------------------------------


def recent_ok_showtime_counts(db: DB, cinema_id: str, limit: int) -> list[int]:
    """Showtime counts of the cinema's latest ``ok`` ``full`` runs, newest first."""
    cursor = (
        db[SCRAPE_RUNS]
        .find(
            {"cinemaId": cinema_id, "job": "full", "status": "ok"},
            {"counts.showtimes": 1},
        )
        .sort("startedAt", -1)
        .limit(limit)
    )
    return [int(d["counts"]["showtimes"]) for d in cursor if "counts" in d]
