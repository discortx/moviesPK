"""Run health (plan §8.1 ``scrape_runs``, P1-12).

One ``scrape_runs`` document per cinema per job run, checked against the shared
``ScrapeRun`` contract before it is written, then ``cinemas.health`` (and, on success,
``lastScrapedAt``). Error messages are capped at 300 characters, URLs are reduced to their
path, and documents expire after 30 days (TTL on ``expireAt``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..db import repositories as repo
from ..db.client import DB, Document
from ..models.contract import ScrapeRun
from ..models.vocab import Job, RunStatus

RUN_TTL = timedelta(days=30)
MAX_ERRORS = 20
MESSAGE_MAX = 300
_URL = re.compile(r"https?://[^\s/]+(/[^\s?#]*)?(\?[^\s#]*)?")


@dataclass(frozen=True)
class RunError:
    type: str
    message: str
    url: str | None = None


@dataclass(frozen=True)
class RunRecord:
    job: Job
    cinema_id: str
    started_at: datetime
    finished_at: datetime
    status: RunStatus
    counts: dict[str, int]
    errors: list[RunError] = field(default_factory=list)
    github_run_id: str | None = None


def clean_message(message: str) -> str:
    """No query strings (tokens, coordinates) and at most 300 characters."""
    text = _URL.sub(lambda m: m.group(1) or "/", message)
    text = " ".join(text.split())
    return text if len(text) <= MESSAGE_MAX else text[: MESSAGE_MAX - 1] + "…"


def github_run_id() -> str | None:
    value = os.environ.get("GITHUB_RUN_ID", "").strip()
    return value if value.isdigit() else None


def run_document(record: RunRecord) -> Document:
    counts = {
        "movies": 0,
        "showtimes": 0,
        "upserted": 0,
        "invalid": 0,
        "cancelled": 0,
        "imagesUploaded": 0,
        "imagesFailed": 0,
        **record.counts,
    }
    doc: Document = {
        "job": record.job,
        "cinemaId": record.cinema_id,
        "startedAt": record.started_at,
        "finishedAt": record.finished_at,
        "status": record.status,
        "counts": counts,
        "errors": [
            {
                "type": e.type[:60] or "Error",
                "message": clean_message(e.message),
                **({"url": e.url} if e.url else {}),
            }
            for e in record.errors[:MAX_ERRORS]
        ],
    }
    if record.github_run_id:
        doc["githubRunId"] = record.github_run_id
    ScrapeRun.model_validate(doc)  # the shared contract (shared/schemas/ScrapeRun.json)
    doc["expireAt"] = record.finished_at + RUN_TTL
    return doc


def last_success(db: DB, cinema_id: str) -> datetime | None:
    cinema = db[repo.CINEMAS].find_one({"_id": cinema_id}, {"health.lastSuccessAt": 1})
    health: Any = (cinema or {}).get("health") or {}
    value = health.get("lastSuccessAt")
    return value if isinstance(value, datetime) else None


def record_run(db: DB, record: RunRecord) -> None:
    db[repo.SCRAPE_RUNS].insert_one(run_document(record))
    health: Document = {
        "health.status": record.status,
        "health.lastRunAt": record.finished_at,
    }
    if record.status in ("ok", "partial"):
        health["health.lastSuccessAt"] = record.finished_at
        if record.job == "full":
            health["lastScrapedAt"] = record.finished_at
    db[repo.CINEMAS].update_one({"_id": record.cinema_id}, {"$set": health})
