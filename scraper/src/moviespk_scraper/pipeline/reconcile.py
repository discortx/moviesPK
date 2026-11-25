"""Reconcile and run guards (plan §8.4, P1-11).

Guards (checked before anything is written for the cinema):
* **zero result** — 0 valid showtimes → ``failed``;
* **median** — fewer than 50% of the median showtime count of the cinema's last 7 ``ok``
  ``full`` runs → ``failed``; active only after a warm-up of 3 such runs;
* the **invalid-rate** guard (> 20%) lives in ``pipeline/validate.py``.
A failed cinema writes nothing (its ``scrape_runs`` document comes with P1-12).

Reconcile (only for a cinema whose ``full`` run is ``ok``, after the upsert):
* window: active showtimes of the cinema starting from *now* up to the latest start seen
  in this run. Shows beyond what the cinema published this time are not judged, and past
  shows are left to the TTL index (``expireAt``);
* a show in the window that was not seen gets ``missCount += 1``; at 2 it becomes
  ``cancelled``. A show seen again is reset by the upsert (``active``, ``missCount: 0``).
"""

from __future__ import annotations

import statistics
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from ..db import repositories as repo
from ..db.client import DB

MEDIAN_RUNS = 7
WARM_UP_RUNS = 3
MEDIAN_FLOOR = 0.5
CANCEL_AFTER_MISSES = 2


@dataclass(frozen=True)
class ReconcileCounts:
    missed: int
    cancelled: int


def guard_reason(valid_showtimes: int, recent_counts: Sequence[int]) -> str | None:
    """Why this run must be ``failed`` (zero-result or median guard), or ``None``."""
    if valid_showtimes == 0:
        return "zero result: no valid showtimes"
    if len(recent_counts) >= WARM_UP_RUNS:
        median = statistics.median(recent_counts[:MEDIAN_RUNS])
        if valid_showtimes < MEDIAN_FLOOR * median:
            return (
                f"zero-result guard: {valid_showtimes} showtimes is below 50% of the "
                f"median of the last {min(len(recent_counts), MEDIAN_RUNS)} ok runs ({median:g})"
            )
    return None


def reconcile(
    db: DB,
    cinema_id: str,
    seen_ids: Collection[str],
    *,
    now: datetime,
    until: datetime,
) -> ReconcileCounts:
    """Count a miss for every active, unseen show in ``[now, until]``; cancel at 2 misses."""
    window = {
        "cinemaId": cinema_id,
        "status": "active",
        "startsAt": {"$gte": now, "$lte": until},
    }
    missed = db[repo.SHOWTIMES].update_many(
        {**window, "_id": {"$nin": list(seen_ids)}},
        {"$inc": {"missCount": 1}, "$set": {"updatedAt": now}},
    )
    cancelled = db[repo.SHOWTIMES].update_many(
        {**window, "missCount": {"$gte": CANCEL_AFTER_MISSES}},
        {"$set": {"status": "cancelled", "updatedAt": now}},
    )
    return ReconcileCounts(
        missed=int(missed.modified_count), cancelled=int(cancelled.modified_count)
    )
