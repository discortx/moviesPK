"""P2-10 integration: TMDB purge and orphan cleanup against MongoDB, with an in-memory
bucket (the real dev bucket: tests/integration_r2/test_maintenance_r2.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId

from moviespk_scraper.db.client import DB
from moviespk_scraper.pipeline.maintenance import (
    PURGED_FIELDS,
    MaintenanceCounts,
    purge_tmdb,
    run_maintenance,
    variant_keys,
)
from moviespk_scraper.services.r2 import StoredObject

pytestmark = pytest.mark.integration

NOW = datetime(2026, 12, 1, 4, 23, tzinfo=UTC)  # UTC day 1
ORPHAN_OLD = "movies/ffffffffffffffffffff0005/poster-aaaaaaaa-w342.webp"
ORPHAN_NEW = "movies/ffffffffffffffffffff0006/poster-bbbbbbbb-w342.webp"


class MemoryBucket:
    def __init__(self) -> None:
        self.objects: dict[str, datetime] = {}

    def put(self, key: str, when: datetime) -> None:
        self.objects[key] = when

    def list(self, prefix: str) -> list[StoredObject]:
        return [
            StoredObject(k, 100, t) for k, t in sorted(self.objects.items()) if k.startswith(prefix)
        ]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def movie(db: DB, bucket: MemoryBucket, *, last_shown_days: int) -> dict[str, Any]:
    mid = ObjectId()
    stem = f"movies/{mid}/poster-{str(mid)[-8:]}"
    doc: dict[str, Any] = {
        "_id": mid,
        "slug": f"m-{mid}",
        "localKey": f"m-{mid}",
        "title": "Some Film",
        "tmdbId": int(str(mid)[-6:], 16),
        "matchStatus": "matched",
        "synopsis": "From TMDB.",
        "genres": ["drama"],
        "runtimeMin": 120,
        "releaseDate": "2026-05-01",
        "originalTitle": "Some Film",
        "rating": {"certification": "U", "tmdbScore": 7.1},
        "tmdbRefreshedAt": NOW - timedelta(days=last_shown_days + 3),
        "lastShowingAt": NOW - timedelta(days=last_shown_days),
        "poster": {"key": stem, "width": 780, "height": 1170},
    }
    db.movies.insert_one(doc)
    for key in variant_keys(stem):
        bucket.put(key, NOW - timedelta(days=last_shown_days))
    return doc


def test_91_days_is_purged_89_days_untouched(db: DB) -> None:
    bucket = MemoryBucket()
    old = movie(db, bucket, last_shown_days=91)
    recent = movie(db, bucket, last_shown_days=89)
    counts = MaintenanceCounts()
    purge_tmdb(db, bucket, NOW, counts, dry_run=False)

    assert (counts.purged_movies, counts.purged_objects) == (1, 3)
    purged = db.movies.find_one({"_id": old["_id"]})
    assert purged is not None and purged["poster"] is None and purged["genres"] == []
    for name in PURGED_FIELDS:
        top, _, sub = name.partition(".")
        assert (sub not in purged.get(top, {})) if sub else (top not in purged)
    assert purged["tmdbId"] == old["tmdbId"] and purged["slug"] == old["slug"]
    assert purged["rating"] == {"certification": "U"}
    assert not any(k.startswith(old["poster"]["key"]) for k in bucket.objects)

    assert db.movies.find_one({"_id": recent["_id"]}) == recent
    assert all(k in bucket.objects for k in variant_keys(recent["poster"]["key"]))

    again = MaintenanceCounts()
    purge_tmdb(db, bucket, NOW, again, dry_run=False)
    assert again.purged_movies == 0  # already purged


def test_dry_run_and_missing_r2_change_nothing(db: DB) -> None:
    bucket = MemoryBucket()
    old = movie(db, bucket, last_shown_days=120)
    before = dict(bucket.objects)
    counts = MaintenanceCounts()
    purge_tmdb(db, bucket, NOW, counts, dry_run=True)
    assert counts.purged_movies == 1 and bucket.objects == before
    assert db.movies.find_one({"_id": old["_id"]}) == old

    no_r2 = MaintenanceCounts()
    purge_tmdb(db, None, NOW, no_r2, dry_run=False)  # never drop the reference alone
    assert no_r2.purged_movies == 0 and "postponed" in no_r2.notes[0]
    assert db.movies.find_one({"_id": old["_id"]}) == old


def test_orphans_only_on_day_one(db: DB) -> None:
    bucket = MemoryBucket()
    kept = movie(db, bucket, last_shown_days=10)  # referenced, 10 days old
    bucket.put(ORPHAN_OLD, NOW - timedelta(days=8))
    bucket.put(ORPHAN_NEW, NOW - timedelta(days=1))

    day2 = run_maintenance(db, bucket, None, NOW + timedelta(days=1), dry_run=False)
    assert not day2.orphan_cleanup_ran and len(bucket.objects) == 5

    day1 = run_maintenance(db, bucket, None, NOW, dry_run=False)
    assert day1.orphan_cleanup_ran and day1.orphans_deleted == 1
    assert ORPHAN_OLD not in bucket.objects and ORPHAN_NEW in bucket.objects
    assert all(k in bucket.objects for k in variant_keys(kept["poster"]["key"]))
    assert day1.r2_objects == 4 and day1.as_document()["r2Bytes"] == 400
