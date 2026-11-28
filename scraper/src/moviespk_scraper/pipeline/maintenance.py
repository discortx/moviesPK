"""Daily maintenance inside the canary (plan P2-10, §11.3.5, §7.4.3 item 6).

* **TMDB purge (daily):** movies whose ``lastShowingAt`` is older than
  ``PURGE_AFTER_DAYS`` (90) lose their R2 poster objects and their TMDB-derived fields
  (``poster``, ``synopsis``, ``genres``, ``runtimeMin``, ``rating.tmdbScore``,
  ``trailerUrl``, ``releaseDate``, ``originalTitle``, ``tmdbRefreshedAt``). ``tmdbId``,
  ``title``, ``slug`` and the aliases stay as identifiers; a movie that shows again is
  re-matched and refreshed. Only movies with TMDB data (a poster or ``tmdbRefreshedAt``)
  are touched, so a purged movie is not purged again.
* **R2 usage (daily):** the bucket's total size and object count go into the canary's
  ``scrape_runs`` document; above 1 GB, one ``[alert] r2: storage`` issue (posted once,
  never repeated). It is an observation: uploads are never stopped (OD11).
* **Orphan cleanup (UTC day 1):** objects under ``movies/`` whose stem is not any movie's
  ``poster.key`` and that are older than 7 days (grace for in-flight runs) are deleted.

A dry run counts what it would do and changes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from ..core.config import PURGE_AFTER_DAYS
from ..db import repositories as repo
from ..db.client import DB
from ..services.alerts import Alert, Alerter, run_url
from ..services.images import WIDTHS
from ..services.r2 import StoredObject

R2_ALERT_BYTES = 1024**3  # 1 GB, 10% of the free 10 GB (§7.4.3)
ORPHAN_GRACE = timedelta(days=7)
POSTER_PREFIX = "movies/"
_VARIANT = re.compile(r"^(?P<stem>.+)-w\d+\.webp$")

#: TMDB-derived movie fields removed by the purge (§11.3.5); ``poster`` is set to null.
PURGED_FIELDS = (
    "synopsis",
    "runtimeMin",
    "rating.tmdbScore",
    "trailerUrl",
    "releaseDate",
    "originalTitle",
    "tmdbRefreshedAt",
)


class Bucket(Protocol):
    def list(self, prefix: str) -> Iterable[StoredObject]: ...

    def delete(self, key: str) -> None: ...


@dataclass
class MaintenanceCounts:
    purged_movies: int = 0
    purged_objects: int = 0
    r2_bytes: int | None = None
    r2_objects: int | None = None
    orphans_deleted: int = 0
    orphan_cleanup_ran: bool = False
    notes: list[str] = field(default_factory=list)

    def as_document(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "purgedMovies": self.purged_movies,
            "purgedObjects": self.purged_objects,
            "orphansDeleted": self.orphans_deleted,
        }
        if self.r2_bytes is not None:
            doc["r2Bytes"] = self.r2_bytes
            doc["r2Objects"] = self.r2_objects or 0
        return doc


def variant_keys(stem: str) -> list[str]:
    return [f"{stem}-w{width}.webp" for width in WIDTHS]


# --- TMDB purge ----------------------------------------------------------------------------


def purge_candidates(db: DB, now: datetime, days: int = PURGE_AFTER_DAYS) -> list[dict[str, Any]]:
    cutoff = now - timedelta(days=days)
    return list(
        db[repo.MOVIES].find(
            {
                "lastShowingAt": {"$lt": cutoff},
                "$or": [{"poster": {"$ne": None}}, {"tmdbRefreshedAt": {"$exists": True}}],
            },
            {"poster": 1, "title": 1},
        )
    )


def purge_tmdb(
    db: DB,
    bucket: Bucket | None,
    now: datetime,
    counts: MaintenanceCounts,
    *,
    dry_run: bool,
    days: int = PURGE_AFTER_DAYS,
) -> None:
    for movie in purge_candidates(db, now, days):
        poster = movie.get("poster") or {}
        stem = poster.get("key") if isinstance(poster, dict) else None
        if stem and bucket is None:
            counts.notes.append(f"purge of {movie['_id']} postponed: R2 not configured")
            continue  # never clear the reference while the objects cannot be deleted
        counts.purged_movies += 1
        if stem:
            counts.purged_objects += len(WIDTHS)
        if dry_run:
            continue
        if stem and bucket is not None:
            for key in variant_keys(stem):
                bucket.delete(key)
        db[repo.MOVIES].update_one(
            {"_id": movie["_id"]},
            {
                "$set": {"poster": None, "genres": [], "updatedAt": now},
                "$unset": dict.fromkeys(PURGED_FIELDS, ""),
            },
        )


# --- R2 usage -------------------------------------------------------------------------------


def usage_alert(total_bytes: int) -> Alert | None:
    if total_bytes <= R2_ALERT_BYTES:
        return None
    gb = total_bytes / 1024**3
    return Alert(
        cinema_id="r2",
        type="storage",
        summary=(
            f"The poster bucket holds {gb:.2f} GB, above the 1 GB alert line (10% of the free "
            "10 GB). Observation only: uploads continue (OD11). Check §7.4.2 and the purge."
        ),
        state="storage:over-1gb",
        run_url=run_url(),
        repeat_after=None,
    )


def record_usage(
    bucket: Bucket, counts: MaintenanceCounts, alerter: Alerter | None, now: datetime
) -> None:
    total = n = 0
    for obj in bucket.list(""):
        total += obj.size
        n += 1
    counts.r2_bytes, counts.r2_objects = total, n
    if alerter is None:
        return
    alert = usage_alert(total)
    if alert is not None:
        alerter.raise_alert(alert, now)
    else:
        alerter.resolve("r2", now, ("storage",))


# --- orphan cleanup ---------------------------------------------------------------------------


def orphans(
    objects: Iterable[StoredObject], referenced: set[str], now: datetime
) -> list[StoredObject]:
    """Objects whose stem no movie references and that are older than the grace period."""
    found = []
    for obj in objects:
        match = _VARIANT.match(obj.key)
        stem = match.group("stem") if match else obj.key
        if stem not in referenced and now - obj.last_modified > ORPHAN_GRACE:
            found.append(obj)
    return found


def referenced_stems(db: DB) -> set[str]:
    return {
        str(d["poster"]["key"])
        for d in db[repo.MOVIES].find({"poster.key": {"$exists": True}}, {"poster.key": 1})
        if isinstance(d.get("poster"), dict) and d["poster"].get("key")
    }


def cleanup_orphans(
    db: DB,
    bucket: Bucket,
    now: datetime,
    counts: MaintenanceCounts,
    *,
    dry_run: bool,
    prefix: str = POSTER_PREFIX,
) -> None:
    counts.orphan_cleanup_ran = True
    for obj in orphans(bucket.list(prefix), referenced_stems(db), now):
        counts.orphans_deleted += 1
        if not dry_run:
            bucket.delete(obj.key)


def run_maintenance(
    db: DB,
    bucket: Bucket | None,
    alerter: Alerter | None,
    now: datetime,
    *,
    dry_run: bool,
) -> MaintenanceCounts:
    counts = MaintenanceCounts()
    purge_tmdb(db, bucket, now, counts, dry_run=dry_run)
    if bucket is None:
        counts.notes.append("R2 usage and orphan cleanup skipped (R2 not configured)")
        return counts
    if now.day == 1:
        cleanup_orphans(db, bucket, now, counts, dry_run=dry_run)
    record_usage(bucket, counts, None if dry_run else alerter, now)  # after the cleanup
    return counts
