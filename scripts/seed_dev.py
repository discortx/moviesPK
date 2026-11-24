#!/usr/bin/env python3
"""Seed the dev database with sample data (plan P0-06).

    MONGODB_URI_SCRAPER=mongodb://localhost:27017 MONGODB_DB=moviespk_dev \
        python scripts/seed_dev.py

Seeds 2 cinemas, 3 movies and 28 showtimes for tomorrow (PKT), including shows that cross
PKT midnight and showtimes without a hall. Showtime IDs come from the canonical
``moviespk_scraper.pipeline.ids`` (requires the scraper package to be installed).
Idempotent: everything is upserted by deterministic ID. Refuses to touch a database whose
name does not end in ``_dev`` unless ``--force`` is given.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from pymongo import MongoClient, ReplaceOne

from moviespk_scraper.pipeline.ids import canonical_hall, movie_key, showtime_id

PKT = timezone(timedelta(hours=5), "PKT")

CINEMAS: list[dict[str, Any]] = [
    {
        "_id": "dev-cinema-lahore",
        "chain": "DevChain",
        "name": "Dev Cinema Lahore",
        "city": "lahore",
        "address": "1 Sample Road, Lahore",
        "location": {"type": "Point", "coordinates": [74.3436, 31.5161]},
        "websiteUrl": "https://example.com/lahore",
        "facilities": ["3D"],
        "enabled": True,
        "seatsEnabled": True,
    },
    {
        "_id": "dev-cinema-karachi",
        "chain": "DevChain",
        "name": "Dev Cinema Karachi",
        "city": "karachi",
        "address": "2 Sample Road, Karachi",
        "location": {"type": "Point", "coordinates": [67.0300, 24.8270]},
        "phone": "+92 21 000 0000",
        "websiteUrl": "https://example.com/karachi",
        "facilities": [],
        "enabled": True,
        "seatsEnabled": False,
    },
]

MOVIES: list[dict[str, Any]] = [
    {
        "_id": ObjectId("6740a1b2c3d4e5f6a7b8c9d0"),
        "tmdbId": 900001,
        "localKey": "dev-action-movie-2026",
        "slug": "dev-action-movie-2026",
        "title": "Dev Action Movie",
        "year": 2026,
        "genres": ["action"],
        "runtimeMin": 128,
        "languages": ["en"],
        "rating": {"certification": "PG-13"},
        "poster": None,
        "matchStatus": "matched",
    },
    {
        "_id": ObjectId("6740a1b2c3d4e5f6a7b8c9d1"),
        "tmdbId": 900002,
        "localKey": "dev-family-movie-2026",
        "slug": "dev-family-movie-2026",
        "title": "Dev Family Movie",
        "year": 2026,
        "genres": ["family", "comedy"],
        "runtimeMin": 95,
        "languages": ["ur"],
        "rating": {},
        "poster": None,
        "matchStatus": "matched",
    },
    {
        "_id": ObjectId("6740a1b2c3d4e5f6a7b8c9d2"),
        "localKey": "dev-local-title-2026",
        "slug": "dev-local-title-2026",
        "title": "Dev Local Title",
        "genres": [],
        "languages": ["pa"],
        "rating": {},
        "poster": None,
        "matchStatus": "unmatched",
    },
]

# (hour, minute, day offset from the seeded PKT date). 23:30 and 00:15 straddle midnight.
SLOTS = [(13, 0, 0), (16, 0, 0), (19, 0, 0), (21, 45, 0), (23, 30, 0)]
LATE = (0, 15, 1)
HALLS = ["Screen 1", None, "  Screen  2 "]


def build_showtimes(day: datetime, now: datetime) -> list[dict[str, Any]]:
    cinema_by_id = {c["_id"]: c for c in CINEMAS}
    docs: list[dict[str, Any]] = []
    for c_index, cinema in enumerate(CINEMAS):
        for m_index, movie in enumerate(MOVIES):
            slots = SLOTS if m_index < 2 else [*SLOTS[2:], LATE]
            for s_index, (hour, minute, offset) in enumerate(slots):
                local = (day + timedelta(days=offset)).replace(hour=hour, minute=minute)
                starts_at = local.astimezone(UTC)
                raw_hall = HALLS[(c_index + m_index + s_index) % len(HALLS)]
                fmt = "3D" if (m_index == 0 and s_index == 2) else "2D"
                key = movie_key(movie.get("tmdbId"), movie["localKey"])
                doc: dict[str, Any] = {
                    "_id": showtime_id(cinema["_id"], key, starts_at, raw_hall, fmt),
                    "cinemaId": cinema["_id"],
                    "movieId": movie["_id"],
                    "startsAt": starts_at,
                    "format": fmt,
                    "language": movie["languages"][0],
                    "seats": {"status": "available" if cinema["seatsEnabled"] else "unknown"},
                    "status": "active",
                    "missCount": 0,
                    "lastSeenAt": now,
                    "cinema": {
                        "name": cinema_by_id[cinema["_id"]]["name"],
                        "city": cinema["city"],
                    },
                    "movie": {
                        "title": movie["title"],
                        "slug": movie["slug"],
                        "posterKey": None,
                        "genres": movie["genres"],
                        **({"runtimeMin": movie["runtimeMin"]} if "runtimeMin" in movie else {}),
                    },
                    "expireAt": starts_at + timedelta(days=7),
                }
                if movie.get("runtimeMin"):
                    doc["endsAt"] = starts_at + timedelta(minutes=movie["runtimeMin"])
                hall = canonical_hall(raw_hall)
                if hall:
                    doc["hall"] = hall
                docs.append(doc)
    return docs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the MoviesPK dev database.")
    parser.add_argument("--force", action="store_true", help="allow a non-*_dev database")
    args = parser.parse_args(argv)
    db_name = os.environ.get("MONGODB_DB", "moviespk_dev")
    if not db_name.endswith("_dev") and not args.force:
        print(f"refusing to seed '{db_name}' (not a *_dev database)", file=sys.stderr)
        return 1
    uri = os.environ.get("MONGODB_URI_SCRAPER", "mongodb://localhost:27017")
    now = datetime.now(UTC)
    tomorrow = (now.astimezone(PKT) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    client: MongoClient[dict[str, Any]] = MongoClient(uri, serverSelectionTimeoutMS=10_000)
    try:
        db = client[db_name]
        cinemas = [
            c | {"health": {"status": "unknown"}, "createdAt": now, "updatedAt": now}
            for c in CINEMAS
        ]
        movies = [
            m | {"nowShowing": True, "lastShowingAt": now, "createdAt": now, "updatedAt": now}
            for m in MOVIES
        ]
        showtimes = build_showtimes(tomorrow, now)
        for name, docs in (("cinemas", cinemas), ("movies", movies), ("showtimes", showtimes)):
            ops = [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs]
            db[name].bulk_write(ops, ordered=False)
            print(f"{name}: {len(docs)} upserted")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
