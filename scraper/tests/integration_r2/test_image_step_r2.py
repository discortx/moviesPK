"""P1-24: the image step against the real dev bucket (plan §10.3 step 5a, §7.4.3).

Runs only from `integration-r2.yml` (workflow_dispatch, environment `dev`), never on PRs;
skipped everywhere else. Uses two test-only movie ids and deletes its own objects at the
end, so `moviespk-dev` keeps only real posters. The poster bytes are generated locally
(no TMDB call); everything from processing onward is the production code path.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import mongomock
import pytest
from bson import ObjectId
from PIL import Image

from moviespk_scraper.services.images import WIDTHS, ImageStep, process_poster
from moviespk_scraper.services.r2 import CACHE_CONTROL, R2Settings, R2Store, make_client

pytestmark = pytest.mark.r2

SETTINGS = R2Settings.from_env()
if SETTINGS is None or SETTINGS.bucket != "moviespk-dev":
    pytest.skip(
        "R2 integration needs the dev bucket credentials (integration-r2.yml)",
        allow_module_level=True,
    )

NOW = datetime(2026, 11, 28, tzinfo=UTC)
#: Test-only movie ids (never produced by the scraper, which uses fresh ObjectIds).
MOVIES = [ObjectId("ffffffffffffffffffff0001"), ObjectId("ffffffffffffffffffff0002")]


def poster(color: tuple[int, int, int], height: int = 1500) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1000, height), color).save(out, format="JPEG")
    return out.getvalue()


class FakeTmdb:
    """Serves locally generated posters instead of calling TMDB."""

    def __init__(self) -> None:
        self.posters: dict[str, bytes] = {}

    def configuration(self) -> Any:
        return SimpleNamespace(image_base_url="https://image.tmdb.org/t/p/")

    def download_poster(self, base: str, path: str) -> bytes:
        return self.posters[path]


@pytest.fixture(scope="module")
def s3() -> Iterator[Any]:
    assert SETTINGS is not None
    client = make_client(SETTINGS)
    yield client
    for movie in MOVIES:  # clean up everything this test created
        listed = client.list_objects_v2(Bucket=SETTINGS.bucket, Prefix=f"movies/{movie}/")
        for obj in listed.get("Contents", []):
            client.delete_object(Bucket=SETTINGS.bucket, Key=obj["Key"])


def keys(s3: Any, movie: ObjectId) -> set[str]:
    assert SETTINGS is not None
    listed = s3.list_objects_v2(Bucket=SETTINGS.bucket, Prefix=f"movies/{movie}/")
    return {o["Key"] for o in listed.get("Contents", [])}


def run(s3: Any, tmdb: FakeTmdb, db: Any) -> tuple[int, ImageStep]:
    """One run of the step for both movies, like one scrape run."""
    assert SETTINGS is not None
    step = ImageStep(tmdb=tmdb, store=R2Store(s3, SETTINGS.bucket), db=db)  # type: ignore[arg-type]
    puts = 0
    for movie in MOVIES:
        current = (db.movies.find_one({"_id": movie}) or {}).get("poster") or {}
        outcome, n = step.poster_for(str(movie), 1, f"/{movie}.jpg", current.get("key"), NOW)
        assert outcome in ("uploaded", "unchanged")
        puts += n
    return puts, step


def test_second_run_creates_no_objects_and_changes_get_new_keys(s3: Any) -> None:
    assert SETTINGS is not None
    db = mongomock.MongoClient().db
    db.movies.insert_many([{"_id": m, "poster": None} for m in MOVIES])
    tmdb = FakeTmdb()
    tmdb.posters = {f"/{m}.jpg": poster((10 * i, 120, 200)) for i, m in enumerate(MOVIES)}

    # First run: three new objects per movie.
    puts, _ = run(s3, tmdb, db)
    assert puts == 3 * len(MOVIES)
    first = {m: keys(s3, m) for m in MOVIES}
    for m in MOVIES:
        stem = db.movies.find_one({"_id": m})["poster"]["key"]
        assert first[m] == {f"{stem}-w{w}.webp" for w in WIDTHS}

    # Every object carries the right metadata.
    for m in MOVIES:
        for key in first[m]:
            head = s3.head_object(Bucket=SETTINGS.bucket, Key=key)
            assert head["ContentType"] == "image/webp"
            assert head["CacheControl"] == CACHE_CONTROL
            assert head["ContentLength"] <= 1024 * 1024

    # Second run, same sources: no PUT at all (no new Class A writes), same keys.
    puts, _ = run(s3, tmdb, db)
    assert puts == 0
    assert {m: keys(s3, m) for m in MOVIES} == first

    # A changed source image for one movie: a new key; the old objects stay for cleanup.
    changed = MOVIES[0]
    tmdb.posters[f"/{changed}.jpg"] = poster((250, 250, 0), height=1400)
    new_stem = process_poster(tmdb.posters[f"/{changed}.jpg"]).stem(str(changed))
    puts, _ = run(s3, tmdb, db)
    assert puts == 3
    after = keys(s3, changed)
    assert first[changed] < after  # the old objects are still there
    assert after - first[changed] == {f"{new_stem}-w{w}.webp" for w in WIDTHS}
    assert db.movies.find_one({"_id": changed})["poster"]["key"] == new_stem
    assert keys(s3, MOVIES[1]) == first[MOVIES[1]]
