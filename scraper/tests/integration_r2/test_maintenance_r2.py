"""P2-10 acceptance against the real dev bucket (plan §11.3.5, §7.4.3 item 6).

Runs only from `integration-r2.yml` (environment `dev`); skipped everywhere else. Uses
test-only movie ids (``ffffffffffffffffffff00xx``, never produced by the scraper) and only
looks under their prefix, so real dev posters are never listed for deletion; everything it
creates is removed at the end. The database is mongomock, seeded by the test.

* a movie last shown 91 days ago loses its three poster objects and its TMDB fields;
  one last shown 89 days ago is untouched;
* an orphan older than 7 days is deleted; a referenced object and a 1-day-old orphan are
  kept (object age is simulated by running the cleanup "later": R2 sets LastModified).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import mongomock
import pytest
from bson import ObjectId

from moviespk_scraper.pipeline.maintenance import (
    MaintenanceCounts,
    cleanup_orphans,
    purge_tmdb,
    variant_keys,
)
from moviespk_scraper.services.r2 import R2Bucket, R2Settings, make_client

pytestmark = pytest.mark.r2

SETTINGS = R2Settings.from_env()
if SETTINGS is None or SETTINGS.bucket != "moviespk-dev":
    pytest.skip(
        "R2 integration needs the dev bucket credentials (integration-r2.yml)",
        allow_module_level=True,
    )

TEST_PREFIX = "movies/ffffffffffffffffffff"
OLD, RECENT, ORPHAN, REFERENCED = (
    ObjectId(f"ffffffffffffffffffff00{n}") for n in ("03", "04", "05", "06")
)


def stem(movie: ObjectId) -> str:
    return f"movies/{movie}/poster-{str(movie)[-8:]}"


@pytest.fixture(scope="module")
def bucket() -> Iterator[R2Bucket]:
    assert SETTINGS is not None
    client = make_client(SETTINGS)
    b = R2Bucket(client, SETTINGS.bucket)
    for movie in (OLD, RECENT, ORPHAN, REFERENCED):
        for key in variant_keys(stem(movie)):
            client.put_object(
                Bucket=SETTINGS.bucket, Key=key, Body=b"test", ContentType="image/webp"
            )
    yield b
    for obj in list(b.list(TEST_PREFIX)):  # clean up everything this test created
        b.delete(obj.key)


def keys(bucket: R2Bucket) -> set[str]:
    return {o.key for o in bucket.list(TEST_PREFIX)}


def seed_movie(db: Any, movie: ObjectId, now: datetime, last_shown_days: int) -> None:
    db.movies.insert_one(
        {
            "_id": movie,
            "title": "R2 test film",
            "tmdbId": 990000 + int(str(movie)[-2:]),
            "synopsis": "From TMDB.",
            "genres": ["drama"],
            "runtimeMin": 100,
            "releaseDate": "2026-01-01",
            "tmdbRefreshedAt": now - timedelta(days=last_shown_days),
            "lastShowingAt": now - timedelta(days=last_shown_days),
            "poster": {"key": stem(movie), "width": 780, "height": 1170},
        }
    )


def test_purge_91_days_deletes_objects_89_days_untouched(bucket: R2Bucket) -> None:
    now = datetime.now(UTC)
    db = mongomock.MongoClient(tz_aware=True).db
    seed_movie(db, OLD, now, 91)
    seed_movie(db, RECENT, now, 89)
    counts = MaintenanceCounts()
    purge_tmdb(db, bucket, now, counts, dry_run=False)

    assert (counts.purged_movies, counts.purged_objects) == (1, 3)
    present = keys(bucket)
    assert not set(variant_keys(stem(OLD))) & present
    assert set(variant_keys(stem(RECENT))) <= present
    old = db.movies.find_one({"_id": OLD})
    assert old["poster"] is None and "synopsis" not in old and old["genres"] == []
    assert old["tmdbId"] == 990003  # kept as an identifier
    assert db.movies.find_one({"_id": RECENT})["synopsis"] == "From TMDB."


def test_orphans_older_than_7_days_go_referenced_and_new_stay(bucket: R2Bucket) -> None:
    db = mongomock.MongoClient(tz_aware=True).db
    db.movies.insert_one({"_id": REFERENCED, "poster": {"key": stem(REFERENCED)}})
    orphan, referenced = set(variant_keys(stem(ORPHAN))), set(variant_keys(stem(REFERENCED)))

    one_day_later = datetime.now(UTC) + timedelta(days=1)  # the orphan is 1 day old
    counts = MaintenanceCounts()
    cleanup_orphans(db, bucket, one_day_later, counts, dry_run=False, prefix=TEST_PREFIX)
    assert orphan <= keys(bucket) and referenced <= keys(bucket)

    eight_days_later = datetime.now(UTC) + timedelta(days=8)
    cleanup_orphans(db, bucket, eight_days_later, counts, dry_run=False, prefix=TEST_PREFIX)
    present = keys(bucket)
    assert not orphan & present and referenced <= present
