"""P1-23: the poster image step (plan §10.3 step 5a, §7.4.3) with botocore's Stubber."""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import boto3
import httpx
import mongomock
import pytest
import respx
from botocore.stub import ANY, Stubber
from bson import ObjectId
from PIL import Image

from moviespk_scraper.services.images import (
    WIDTHS,
    ImageStep,
    PosterProcessingError,
    process_poster,
)
from moviespk_scraper.services.r2 import (
    CACHE_CONTROL,
    MAX_OBJECT_BYTES,
    R2Error,
    R2Store,
    UploadCapReached,
)
from moviespk_scraper.services.tmdb import PosterDownloadError, TmdbClient, TmdbMovie

NOW = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
BUCKET = "moviespk-dev"
MOVIE = ObjectId("6740a1b2c3d4e5f6a7b8c9d0")


def jpeg(width: int = 1000, height: int = 1500, exif: bool = False) -> bytes:
    img = Image.new("RGB", (width, height), (200, 30, 30))
    out = io.BytesIO()
    if exif:
        meta = Image.Exif()
        meta[0x010E] = "secret camera note"  # ImageDescription
        img.save(out, format="JPEG", exif=meta)
    else:
        img.save(out, format="JPEG")
    return out.getvalue()


# --- processing ---------------------------------------------------------------------------


def test_three_webp_widths_keep_the_aspect_ratio() -> None:
    p = process_poster(jpeg(1000, 1500))
    assert set(p.variants) == set(WIDTHS)
    for width, data in p.variants.items():
        with Image.open(io.BytesIO(data)) as img:
            assert img.format == "WEBP"
            assert img.width == width and img.height == round(1500 * width / 1000)
    assert (p.width, p.height) == (780, 1170)
    assert len(p.hash8) == 8 and int(p.hash8, 16) >= 0
    assert p.stem(str(MOVIE)) == f"movies/{MOVIE}/poster-{p.hash8}"


def test_never_upscales() -> None:
    p = process_poster(jpeg(300, 450))
    with Image.open(io.BytesIO(p.variants[780])) as img:
        assert img.size == (300, 450)
    assert (p.width, p.height) == (300, 450)


def test_metadata_is_stripped_and_alpha_dropped() -> None:
    p = process_poster(jpeg(exif=True))
    with Image.open(io.BytesIO(p.variants[342])) as img:
        assert not img.getexif() and "icc_profile" not in img.info
    rgba = io.BytesIO()
    Image.new("RGBA", (400, 600), (0, 0, 255, 128)).save(rgba, format="PNG")
    with Image.open(io.BytesIO(process_poster(rgba.getvalue()).variants[185])) as img:
        assert img.mode == "RGB"


def test_hash_is_deterministic_and_content_addressed() -> None:
    assert process_poster(jpeg()).hash8 == process_poster(jpeg()).hash8
    assert process_poster(jpeg()).hash8 != process_poster(jpeg(1000, 1400)).hash8


def test_undecodable_data_is_rejected() -> None:
    with pytest.raises(PosterProcessingError):
        process_poster(b"<html>not an image</html>")


# --- TMDB download ------------------------------------------------------------------------

CDN = "https://image.tmdb.org/t/p/"


@pytest.fixture
def tmdb() -> Iterator[TmdbClient]:
    with TmdbClient("eyJv4token", sleep=lambda _s: None) as client:
        yield client


@respx.mock
def test_download_sends_no_credentials_and_uses_w780(tmdb: TmdbClient) -> None:
    route = respx.get(f"{CDN}w780/abc.jpg").mock(
        return_value=httpx.Response(200, content=jpeg(), headers={"content-type": "image/jpeg"})
    )
    assert tmdb.download_poster(CDN, "/abc.jpg")[:2] == b"\xff\xd8"
    request = route.calls.last.request
    assert "authorization" not in request.headers and "api_key" not in str(request.url)


@pytest.mark.parametrize(
    ("headers", "content", "message"),
    [
        ({"content-type": "text/html"}, b"<html>", "content type"),
        ({"content-type": "image/jpeg", "content-length": str(6 * 1024 * 1024)}, b"x", "bytes"),
    ],
)
@respx.mock
def test_download_rejections(
    tmdb: TmdbClient, headers: dict[str, str], content: bytes, message: str
) -> None:
    respx.get(f"{CDN}w780/p.jpg").mock(
        return_value=httpx.Response(200, content=content, headers=headers)
    )
    with pytest.raises(PosterDownloadError, match=message):
        tmdb.download_poster(CDN, "/p.jpg")


@respx.mock
def test_download_stream_cap_without_content_length(tmdb: TmdbClient) -> None:
    """A server that omits (or lies about) Content-Length is still stopped at 5 MB."""

    def chunks() -> Iterator[bytes]:
        for _ in range(6):
            yield b"x" * (1024 * 1024)

    respx.get(f"{CDN}w780/p.jpg").mock(
        return_value=httpx.Response(200, content=chunks(), headers={"content-type": "image/jpeg"})
    )
    with pytest.raises(PosterDownloadError, match="exceeds"):
        tmdb.download_poster(CDN, "/p.jpg")


@pytest.mark.parametrize("path", ["abc.jpg", "/a/b.jpg", "/../x.jpg"])
def test_download_rejects_odd_paths(tmdb: TmdbClient, path: str) -> None:
    with pytest.raises(PosterDownloadError, match="unexpected"):
        tmdb.download_poster(CDN, path)


# --- R2 store (Stubber) --------------------------------------------------------------------


@pytest.fixture
def s3() -> Iterator[tuple[Any, Stubber]]:
    client = boto3.client(
        "s3",
        region_name="auto",
        endpoint_url="https://acct.r2.cloudflarestorage.com",
        aws_access_key_id="k",
        aws_secret_access_key="s",
    )
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def missing(stubber: Stubber, key: str) -> None:
    stubber.add_client_error(
        "head_object", "404", "Not Found", 404, expected_params={"Bucket": BUCKET, "Key": key}
    )


def put(stubber: Stubber, key: str) -> None:
    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": BUCKET,
            "Key": key,
            "Body": ANY,
            "ContentType": "image/webp",
            "CacheControl": CACHE_CONTROL,
        },
    )


def test_head_then_put_with_metadata(s3: tuple[Any, Stubber]) -> None:
    client, stubber = s3
    missing(stubber, "k.webp")
    put(stubber, "k.webp")
    assert R2Store(client, BUCKET).ensure("k.webp", b"webp") is True


def test_existing_object_is_not_uploaded_again(s3: tuple[Any, Stubber]) -> None:
    client, stubber = s3
    stubber.add_response("head_object", {}, {"Bucket": BUCKET, "Key": "k.webp"})
    store = R2Store(client, BUCKET)
    assert store.ensure("k.webp", b"webp") is False and store.uploads == 0


def test_object_over_1mb_is_refused_without_any_call(s3: tuple[Any, Stubber]) -> None:
    client, _ = s3
    with pytest.raises(R2Error, match="1 MB"):
        R2Store(client, BUCKET).ensure("k.webp", b"x" * (MAX_OBJECT_BYTES + 1))


def test_upload_cap(s3: tuple[Any, Stubber]) -> None:
    client, stubber = s3
    store = R2Store(client, BUCKET, max_uploads=1)
    missing(stubber, "a.webp")
    put(stubber, "a.webp")
    store.ensure("a.webp", b"1")
    missing(stubber, "b.webp")
    with pytest.raises(UploadCapReached):
        store.ensure("b.webp", b"2")


def test_head_server_error_is_an_r2_error(s3: tuple[Any, Stubber]) -> None:
    client, stubber = s3
    stubber.add_client_error("head_object", "InternalError", "boom", 500)
    with pytest.raises(R2Error, match="HEAD failed"):
        R2Store(client, BUCKET).ensure("k.webp", b"1")


# --- the step ---------------------------------------------------------------------------------


class FakeTmdb:
    def __init__(self, data: bytes, poster_path: str | None = "/p.jpg") -> None:
        self.data = data
        self.poster_path = poster_path
        self.downloads = 0
        self.details_calls = 0

    def configuration(self) -> Any:
        return SimpleNamespace(image_base_url=CDN)

    def movie_details(self, tmdb_id: int) -> TmdbMovie:
        self.details_calls += 1
        return TmdbMovie(tmdb_id, "T", None, None, 100, (), None, self.poster_path)

    def download_poster(self, base: str, path: str) -> bytes:
        self.downloads += 1
        return self.data


@pytest.fixture
def db() -> Any:
    database = mongomock.MongoClient().db
    database.movies.insert_one({"_id": MOVIE, "poster": None})
    database.showtimes.insert_many([{"_id": "s1", "movieId": MOVIE, "movie": {"posterKey": None}}])
    return database


def step(tmdb: FakeTmdb, client: Any, db: Any, **kw: Any) -> ImageStep:
    return ImageStep(tmdb=tmdb, store=R2Store(client, BUCKET), db=db, **kw)  # type: ignore[arg-type]


def test_uploads_three_variants_then_stores_the_key(s3: tuple[Any, Stubber], db: Any) -> None:
    client, stubber = s3
    data = jpeg()
    stem = process_poster(data).stem(str(MOVIE))
    for w in WIDTHS:
        missing(stubber, f"{stem}-w{w}.webp")
        put(stubber, f"{stem}-w{w}.webp")
    outcome, puts = step(FakeTmdb(data), client, db).poster_for(str(MOVIE), 7, "/p.jpg", None, NOW)
    assert (outcome, puts) == ("uploaded", 3)
    assert db.movies.find_one({"_id": MOVIE})["poster"] == {
        "key": stem,
        "width": 780,
        "height": 1170,
    }
    assert db.showtimes.find_one({"_id": "s1"})["movie"]["posterKey"] == stem


def test_unchanged_poster_makes_zero_r2_calls(s3: tuple[Any, Stubber], db: Any) -> None:
    client, _ = s3  # no stubbed responses: any S3 call fails the test
    data = jpeg()
    stem = process_poster(data).stem(str(MOVIE))
    outcome, puts = step(FakeTmdb(data), client, db).poster_for(str(MOVIE), 7, "/p.jpg", stem, NOW)
    assert (outcome, puts) == ("unchanged", 0)


def test_rebuild_ignores_the_shortcut_but_never_reuploads(s3: tuple[Any, Stubber], db: Any) -> None:
    client, stubber = s3
    data = jpeg()
    stem = process_poster(data).stem(str(MOVIE))
    for w in WIDTHS:
        stubber.add_response("head_object", {}, {"Bucket": BUCKET, "Key": f"{stem}-w{w}.webp"})
    images = step(FakeTmdb(data), client, db, rebuild=True)
    assert images.poster_for(str(MOVIE), 7, "/p.jpg", stem, NOW) == ("uploaded", 0)


def test_failed_upload_keeps_the_previous_poster(s3: tuple[Any, Stubber], db: Any) -> None:
    client, stubber = s3
    data = jpeg()
    stem = process_poster(data).stem(str(MOVIE))
    missing(stubber, f"{stem}-w185.webp")
    stubber.add_client_error("put_object", "InternalError", "boom", 500)
    outcome, _ = step(FakeTmdb(data), client, db).poster_for(str(MOVIE), 7, "/p.jpg", None, NOW)
    assert outcome == "failed"
    assert db.movies.find_one({"_id": MOVIE})["poster"] is None  # only after all three exist


def test_bad_image_counts_as_failed_without_r2(s3: tuple[Any, Stubber], db: Any) -> None:
    client, _ = s3
    assert (
        step(FakeTmdb(b"junk"), client, db).poster_for(str(MOVIE), 7, "/p.jpg", None, NOW)[0]
        == "failed"
    )


def test_each_movie_at_most_once_per_run(s3: tuple[Any, Stubber], db: Any) -> None:
    client, _ = s3
    fake = FakeTmdb(jpeg())
    images = step(fake, client, db)
    stem = process_poster(fake.data).stem(str(MOVIE))
    images.poster_for(str(MOVIE), 7, "/p.jpg", stem, NOW)
    assert images.poster_for(str(MOVIE), 7, "/p.jpg", stem, NOW) == ("skipped", 0)
    assert fake.downloads == 1


def test_missing_poster_path_fetches_details_and_skips_when_tmdb_has_none(
    s3: tuple[Any, Stubber], db: Any
) -> None:
    client, _ = s3
    fake = FakeTmdb(jpeg(), poster_path=None)
    assert step(fake, client, db).poster_for(str(MOVIE), 7, None, None, NOW) == ("skipped", 0)
    assert fake.details_calls == 1 and fake.downloads == 0


def test_cap_reached_reports_once(s3: tuple[Any, Stubber], db: Any) -> None:
    client, stubber = s3
    reports: list[str] = []
    other = ObjectId("6740a1b2c3d4e5f6a7b8c9d1")
    db.movies.insert_one({"_id": other, "poster": None})
    images = ImageStep(
        tmdb=FakeTmdb(jpeg()),
        store=R2Store(client, BUCKET, max_uploads=0),
        db=db,  # type: ignore[arg-type]
        on_cap_reached=lambda: reports.append("cap"),
    )
    for movie in (MOVIE, other):
        missing(stubber, f"{process_poster(jpeg()).stem(str(movie))}-w185.webp")
        assert images.poster_for(str(movie), 7, "/p.jpg", None, NOW)[0] == "failed"
    assert reports == ["cap"]


def test_r2_settings_need_all_four_and_never_show_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    from moviespk_scraper.services.r2 import R2Settings, make_client

    for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    assert R2Settings.from_env() is None
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "AKIDSECRET")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "SUPERSECRET")
    assert R2Settings.from_env() is None  # bucket still missing
    monkeypatch.setenv("R2_BUCKET", BUCKET)
    settings = R2Settings.from_env()
    assert settings is not None
    assert "SECRET" not in repr(settings) and BUCKET in repr(settings)
    client = make_client(settings)
    assert client.meta.endpoint_url == "https://acct.r2.cloudflarestorage.com"
    assert client.meta.region_name == "auto"


def test_dry_run_builds_no_image_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dry run (no database) never creates the image step, so it makes zero S3 calls."""
    import argparse

    from moviespk_scraper.cli import _image_step

    for name, value in {
        "R2_ACCOUNT_ID": "acct",
        "R2_ACCESS_KEY_ID": "k",
        "R2_SECRET_ACCESS_KEY": "s",
        "R2_BUCKET": BUCKET,
    }.items():
        monkeypatch.setenv(name, value)
    args = argparse.Namespace(rebuild_images=False)
    with TmdbClient("key", sleep=lambda _s: None) as tmdb_client:
        assert _image_step(args, None, tmdb_client, None) is None  # dry run: db is None
    assert _image_step(args, mongomock.MongoClient().db, None, None) is None  # no TMDB key
