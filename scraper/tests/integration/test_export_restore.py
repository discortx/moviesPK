"""P2-05 acceptance: weekly export and scripts/restore_export.py (plan §17.3, §19).

* a valid export restored into a scratch database reproduces the documents and counts;
* restore + one ``full`` run gives working data again (showtimes back, no duplicate movies);
* a truncated gzip, a missing collection file, a count mismatch, a missing manifest, bad
  JSON, a checksum mismatch and an unknown schema version are each rejected with zero
  writes;
* ``--target-db moviespk`` without ``--force`` is refused.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import shutil
import sys
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pymongo import MongoClient

from moviespk_scraper.cli import main as cli_main
from moviespk_scraper.db.client import DB
from moviespk_scraper.services.export import COLLECTIONS, MANIFEST, load_export, write_export

from .test_upsert import CINEPAX, run_pipeline

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "restore_export.py"
NOW = datetime(2026, 11, 29, 3, 41, tzinfo=UTC)
VISTA = ["universal-emporium-mall-lahore", "cinestar-township-lahore"]
ALL = [*CINEPAX, *VISTA]
SHOWTIMES = 19 + 12 + 33 + 97 + 20


@pytest.fixture(scope="module")
def restore() -> ModuleType:
    spec = importlib.util.spec_from_file_location("restore_export", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["restore_export"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source(db: DB) -> DB:
    run_pipeline(db, ALL)
    db.movie_aliases.insert_one({"_id": "belkis", "movieKey": "belkis-2026", "source": "manual"})
    return db


@pytest.fixture
def target(mongo_uri: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, DB]]:
    """A scratch database (``moviespk_restore_test_*``) with one sentinel document per
    collection, so "nothing written" also means "nothing deleted"."""
    monkeypatch.setenv("MONGODB_URI_SCRAPER", mongo_uri)
    name = f"moviespk_restore_test_{uuid.uuid4().hex[:8]}"
    client: MongoClient[dict[str, Any]] = MongoClient(mongo_uri, tz_aware=True)
    db = client[name]
    for coll in COLLECTIONS:
        db[coll].insert_one({"_id": "sentinel", "localKey": "sentinel", "slug": "sentinel"})
    yield name, db
    client.drop_database(name)
    client.close()


def snapshot(db: DB) -> dict[str, list[dict[str, Any]]]:
    return {c: list(db[c].find({}).sort("_id", 1)) for c in COLLECTIONS}


def sentinels_only(db: DB) -> bool:
    return all([d["_id"] for d in db[c].find({}, {"_id": 1})] == ["sentinel"] for c in COLLECTIONS)


# --- valid export -----------------------------------------------------------------------


def test_restore_reproduces_the_export(
    restore: ModuleType, source: DB, target: tuple[str, DB], tmp_path: Path
) -> None:
    manifest = write_export(source, tmp_path / "export", NOW)
    assert manifest["schemaVersion"] == 1 and manifest["exportedAt"] == "2026-11-29T03:41:00Z"
    assert {c: e["count"] for c, e in manifest["collections"].items()} == {
        c: source[c].count_documents({}) for c in COLLECTIONS
    }
    name, restored = target
    code = restore.main(["--input", str(tmp_path / "export"), "--target-db", name])
    assert code == 0
    assert snapshot(restored) == snapshot(source)  # same documents, same types
    assert restored.showtimes.count_documents({}) == 0  # showtimes come back with a full run


def test_restore_then_one_full_run_gives_working_data(
    restore: ModuleType, source: DB, target: tuple[str, DB], tmp_path: Path
) -> None:
    write_export(source, tmp_path / "export", NOW)
    name, restored = target
    assert restore.main(["--input", str(tmp_path / "export"), "--target-db", name]) == 0
    movies = restored.movies.count_documents({})
    run_pipeline(restored, ALL)
    assert restored.showtimes.count_documents({}) == SHOWTIMES
    assert restored.movies.count_documents({}) == movies  # re-used, not duplicated
    linked = restored.showtimes.distinct("movieId")
    assert restored.movies.count_documents({"_id": {"$in": linked}}) == len(linked)
    assert "localKey_unique" in restored.movies.index_information()  # indexes ensured


def test_export_is_deterministic(source: DB, tmp_path: Path) -> None:
    first = write_export(source, tmp_path / "a", NOW)
    second = write_export(source, tmp_path / "b", NOW)
    assert first == second


def test_cli_export_job(
    source: DB, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mongo_uri: str
) -> None:
    monkeypatch.setenv("MONGODB_URI_SCRAPER", mongo_uri)
    monkeypatch.setenv("MONGODB_DB", source.name)
    out = tmp_path / "export"
    assert cli_main(["run", "--job", "export", "--export-dir", str(out)]) == 0
    manifest, docs = load_export(out)
    assert len(docs["cinemas"]) == 5 and manifest["collections"]["movies"]["count"] > 0
    assert (
        cli_main(["run", "--job", "export", "--dry-run", "--export-dir", str(tmp_path / "x")]) == 0
    )
    assert not (tmp_path / "x").exists()


# --- invalid exports: rejected, nothing written ------------------------------------------


def _rewrite(path: Path, data: bytes, export: Path) -> None:
    """Replace a collection file and fix its checksum, so the check under test is reached."""
    path.write_bytes(data)
    manifest = json.loads((export / MANIFEST).read_text(encoding="utf-8"))
    for entry in manifest["collections"].values():
        if entry["file"] == path.name:
            entry["sha256"] = hashlib.sha256(data).hexdigest()
    (export / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


def _manifest(export: Path, change: Callable[[dict[str, Any]], None]) -> None:
    manifest = json.loads((export / MANIFEST).read_text(encoding="utf-8"))
    change(manifest)
    (export / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


def truncated_gzip(e: Path) -> None:
    data = (e / "movies.json.gz").read_bytes()
    _rewrite(e / "movies.json.gz", data[: len(data) // 2], e)


def missing_file(e: Path) -> None:
    (e / "movie_aliases.json.gz").unlink()


def count_mismatch(e: Path) -> None:
    _manifest(e, lambda m: m["collections"]["cinemas"].update(count=4))


def missing_manifest(e: Path) -> None:
    (e / MANIFEST).unlink()


def bad_json(e: Path) -> None:
    _rewrite(e / "cinemas.json.gz", gzip.compress(b"[{not json"), e)


def checksum_mismatch(e: Path) -> None:
    (e / "cinemas.json.gz").write_bytes(gzip.compress(b"[]"))


def unknown_schema(e: Path) -> None:
    _manifest(e, lambda m: m.update(schemaVersion=2))


def collection_not_listed(e: Path) -> None:
    _manifest(e, lambda m: m["collections"].pop("movies"))


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (truncated_gzip, "not a complete gzip"),
        (missing_file, "is missing"),
        (count_mismatch, "manifest says 4"),
        (missing_manifest, "manifest.json is missing"),
        (bad_json, "not valid JSON"),
        (checksum_mismatch, "sha256"),
        (unknown_schema, "unknown schemaVersion"),
        (collection_not_listed, "does not list"),
    ],
    ids=lambda v: v.__name__ if callable(v) else "",
)
def test_damaged_export_is_rejected_with_zero_writes(
    restore: ModuleType,
    source: DB,
    target: tuple[str, DB],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    damage: Callable[[Path], None],
    message: str,
) -> None:
    export = tmp_path / "export"
    write_export(source, export, NOW)
    damage(export)
    name, db = target
    assert restore.main(["--input", str(export), "--target-db", name]) == 1
    err = capsys.readouterr().err
    assert message in err and "nothing written" in err
    assert sentinels_only(db)


def test_production_needs_force(
    restore: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert restore.main(["--input", str(tmp_path), "--target-db", "moviespk"]) == 2
    assert "without --force" in capsys.readouterr().err


def test_connection_string_is_never_printed(
    restore: ModuleType,
    source: DB,
    target: tuple[str, DB],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mongo_uri: str,
) -> None:
    write_export(source, tmp_path / "export", NOW)
    name, _ = target
    restore.main(["--input", str(tmp_path / "export"), "--target-db", name])
    out = capsys.readouterr()
    assert mongo_uri not in out.out + out.err


def test_copying_an_export_keeps_it_valid(source: DB, tmp_path: Path) -> None:
    write_export(source, tmp_path / "export", NOW)
    shutil.copytree(tmp_path / "export", tmp_path / "copy")
    load_export(tmp_path / "copy")
