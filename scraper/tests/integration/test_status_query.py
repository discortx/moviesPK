"""P2-08: the /status query (plan §9.1: per-cinema health and the last 7 runs) is served by
indexes: cinemas by _id (health is on the cinema document) and scrape_runs by
cinemaId_startedAt, with no collection scan or in-memory sort."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from moviespk_scraper.db.client import DB

pytestmark = pytest.mark.integration


def stages(plan: dict[str, Any]) -> list[str]:
    found = [plan.get("stage", "")]
    for key in ("inputStage", "queryPlan"):
        if isinstance(plan.get(key), dict):
            found += stages(plan[key])
    for child in plan.get("inputStages", []):
        found += stages(child)
    return found


def test_last_runs_per_cinema_use_the_index(db: DB) -> None:
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    db.scrape_runs.insert_many(
        [
            {"cinemaId": f"c{i % 5}", "job": "full", "status": "ok",
             "startedAt": t0 + timedelta(hours=i)}
            for i in range(500)
        ]
    )  # fmt: skip
    explain = (
        db.scrape_runs.find({"cinemaId": "c3"}, {"job": 1, "status": 1, "startedAt": 1})
        .sort("startedAt", -1)
        .limit(7)
        .explain()
    )
    winning = explain["queryPlanner"]["winningPlan"]
    names = stages(winning)
    assert "IXSCAN" in names and "COLLSCAN" not in names and "SORT" not in names
    assert "cinemaId_startedAt" in str(winning)


def test_cinema_health_is_one_document_by_id(db: DB) -> None:
    db.cinemas.insert_one({"_id": "c1", "health": {"status": "ok"}})
    explain = db.cinemas.find({"_id": "c1"}, {"health": 1}).explain()
    names = stages(explain["queryPlanner"]["winningPlan"])
    assert "COLLSCAN" not in names
