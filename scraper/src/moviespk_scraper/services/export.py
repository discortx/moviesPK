"""Weekly export and its validation (plan P2-05, §19).

``--job export`` writes ``movies``, ``movie_aliases`` and ``cinemas`` (the three
collections that are not cheaply re-scraped; showtimes come back with one ``full`` run) as
gzip MongoDB Extended JSON (relaxed), one array per file, sorted by ``_id``, plus
``manifest.json``::

    {"schemaVersion": 1, "exportedAt": "...Z", "collections": {
        "movies": {"file": "movies.json.gz", "count": 41, "sha256": "..."}, ...}}

The export holds only public cinema and movie data: no personal data, no secrets. It is
kept as an Actions artifact for 60 days (TMDB 6-month rule, §11.3.5), never in R2.

:func:`load_export` validates a whole export before anything is written
(``scripts/restore_export.py``): manifest present and known, every file present, gzip and
JSON valid, checksum and document count equal to the manifest.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bson import json_util
from bson.json_util import JSONMode, JSONOptions

from ..db import repositories as repo
from ..db.client import DB, Document

SCHEMA_VERSION = 1
KNOWN_SCHEMA_VERSIONS = frozenset({1})
COLLECTIONS = (repo.MOVIES, repo.ALIASES, repo.CINEMAS)
MANIFEST = "manifest.json"
_JSON = JSONOptions(json_mode=JSONMode.RELAXED, tz_aware=True, tzinfo=UTC)


class ExportError(Exception):
    """The export is incomplete or damaged; nothing may be restored from it."""


@dataclass(frozen=True)
class CollectionExport:
    name: str
    file: str
    count: int
    sha256: str


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_export(db: DB, out_dir: Path, now: datetime) -> dict[str, Any]:
    """Export the three collections to ``out_dir``; returns the manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: dict[str, Any] = {}
    for name in COLLECTIONS:
        docs = list(db[name].find({}).sort("_id", 1))
        raw = json_util.dumps(docs, json_options=_JSON).encode("utf-8")
        # mtime=0: the same data gives the same bytes (and checksum) on every run.
        data = gzip.compress(raw, mtime=0)
        file = f"{name}.json.gz"
        (out_dir / file).write_bytes(data)
        entries[name] = {
            "file": file,
            "count": len(docs),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    manifest = {"schemaVersion": SCHEMA_VERSION, "exportedAt": _iso(now), "collections": entries}
    (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def count_documents(db: DB) -> dict[str, int]:
    return {name: db[name].count_documents({}) for name in COLLECTIONS}


def load_export(in_dir: Path) -> tuple[dict[str, Any], dict[str, list[Document]]]:
    """Read and validate every part of an export. Raises :class:`ExportError` with a clear
    message on the first problem; returns (manifest, documents by collection)."""
    manifest_path = in_dir / MANIFEST
    if not manifest_path.is_file():
        raise ExportError(f"{MANIFEST} is missing in {in_dir}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExportError(f"{MANIFEST} is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ExportError(f"{MANIFEST} is not an object")
    version = manifest.get("schemaVersion")
    if version not in KNOWN_SCHEMA_VERSIONS:
        raise ExportError(
            f"unknown schemaVersion {version!r} (known: {sorted(KNOWN_SCHEMA_VERSIONS)})"
        )
    entries = manifest.get("collections")
    if not isinstance(entries, dict):
        raise ExportError(f"{MANIFEST} has no collections object")

    loaded: dict[str, list[Document]] = {}
    for name in COLLECTIONS:
        entry = entries.get(name)
        if not isinstance(entry, dict):
            raise ExportError(f"{MANIFEST} does not list the {name!r} collection")
        file, count, digest = entry.get("file"), entry.get("count"), entry.get("sha256")
        if not isinstance(file, str) or Path(file).name != file:
            raise ExportError(f"{name}: bad file name {file!r}")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ExportError(f"{name}: bad count {count!r}")
        path = in_dir / file
        if not path.is_file():
            raise ExportError(f"{name}: {file} is missing")
        data = path.read_bytes()
        if isinstance(digest, str) and hashlib.sha256(data).hexdigest() != digest:
            raise ExportError(f"{name}: {file} does not match its sha256 in the manifest")
        try:
            raw = gzip.decompress(data)
        except (OSError, EOFError, zlib.error) as exc:
            raise ExportError(f"{name}: {file} is not a complete gzip file ({exc})") from exc
        try:
            docs = json_util.loads(raw.decode("utf-8"), json_options=_JSON)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ExportError(f"{name}: {file} is not valid JSON ({exc})") from exc
        if not isinstance(docs, list) or not all(isinstance(d, dict) for d in docs):
            raise ExportError(f"{name}: {file} is not a list of documents")
        if len(docs) != count:
            raise ExportError(f"{name}: {len(docs)} documents, manifest says {count}")
        loaded[name] = docs
    return manifest, loaded
