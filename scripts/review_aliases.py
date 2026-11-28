#!/usr/bin/env python3
"""Alias review (plan P2-04, runbook "Alias review"; weekly).

    python scripts/review_aliases.py            # review interactively
    python scripts/review_aliases.py --list     # only list what needs review
    python scripts/review_aliases.py --add "avengers endgame encore re release" \\
        --tmdb-id 299534 --note "re-release of Avengers: Endgame"

Lists, from the database, the titles that need a human: TMDB suggestions the matcher was
unsure about (``pending`` aliases, score 70-89) and ``unmatched`` movies that still have
upcoming showtimes, each with TMDB candidates. The reviewer picks a candidate, types a
TMDB id, or joins the title to an existing local movie; the tool appends the entry to
``scraper/config/aliases.yml`` (validated like every config load). The reviewer then opens
a PR; after merge, the next ``full`` run re-links the showtimes (no duplicates).

Reads ``MONGODB_URI_SCRAPER`` and ``MONGODB_DB`` (read only) and, for candidates,
``TMDB_API_KEY``. Writes nothing but ``aliases.yml``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from moviespk_scraper.core.config import CONFIG_DIR, ConfigError, load_config
from moviespk_scraper.db import repositories as repo
from moviespk_scraper.db.client import DB, DatabaseUnavailableError, DbSettings, connect
from moviespk_scraper.pipeline.match import score_candidate
from moviespk_scraper.pipeline.normalize import NormalizedMovie, title_key
from moviespk_scraper.services.tmdb import TmdbCandidate, TmdbClient, TmdbError

MAX_CANDIDATES = 5
NOTE_MAX = 200


@dataclass
class ReviewItem:
    key: str  # the normalized title the matcher looks up (the alias)
    title: str
    status: str  # "pending" (matcher suggestion) or "unmatched"
    shows: int = 0
    cinemas: list[str] = field(default_factory=list)
    year: int | None = None
    suggested_tmdb_id: int | None = None


@dataclass(frozen=True)
class Candidate:
    tmdb_id: int
    title: str
    year: int | None
    score: float


@dataclass(frozen=True)
class Decision:
    alias: str
    note: str
    tmdb_id: int | None = None
    local_key: str | None = None
    cinema_id: str | None = None


# --- what needs review ------------------------------------------------------------------


def review_items(db: DB, manual_keys: set[str], now: datetime) -> list[ReviewItem]:
    """Pending aliases and unmatched movies with upcoming showtimes, minus titles that
    already have a manual alias in aliases.yml."""
    upcoming: dict[Any, tuple[int, set[str]]] = {}
    for row in db[repo.SHOWTIMES].aggregate(
        [
            {"$match": {"status": "active", "startsAt": {"$gte": now}}},
            {"$group": {"_id": "$movieId", "n": {"$sum": 1}, "c": {"$addToSet": "$cinemaId"}}},
        ]
    ):
        upcoming[row["_id"]] = (int(row["n"]), set(row["c"]))

    items: dict[str, ReviewItem] = {}
    for doc in db[repo.ALIASES].find({"source": "pending"}).sort("_id", 1):
        key = str(doc["_id"]).split("|", 1)[0]
        movie_key = str(doc.get("movieKey", ""))
        if key in manual_keys or key in items:
            continue
        items[key] = ReviewItem(
            key=key,
            title=key,
            status="pending",
            suggested_tmdb_id=int(movie_key) if movie_key.isdigit() else None,
        )

    query = {"matchStatus": "unmatched", "_id": {"$in": list(upcoming)}}
    for doc in db[repo.MOVIES].find(query).sort("title", 1):
        key = title_key(doc["title"])
        if key in manual_keys:
            continue
        n, cinemas = upcoming[doc["_id"]]
        item = items.setdefault(key, ReviewItem(key=key, title=doc["title"], status="unmatched"))
        item.title, item.year = doc["title"], doc.get("year")
        item.shows += n
        item.cinemas = sorted(set(item.cinemas) | cinemas)
    return list(items.values())


def candidates(
    item: ReviewItem, search: Callable[[str, int | None], list[TmdbCandidate]]
) -> list[Candidate]:
    found = search(item.title, None)
    probe = NormalizedMovie(
        title=item.title,
        title_key=item.key,
        local_key=None,
        original_title=None,
        runtime_min=None,
        genres=(),
        languages=(),
        synopsis=None,
        release_date=None,
        year=item.year,
        certification=None,
    )
    ranked = sorted(
        (Candidate(c.tmdb_id, c.title, c.year, score_candidate(probe, c)) for c in found),
        key=lambda c: -c.score,
    )
    if item.suggested_tmdb_id and all(c.tmdb_id != item.suggested_tmdb_id for c in ranked):
        ranked.insert(0, Candidate(item.suggested_tmdb_id, "(matcher suggestion)", None, 0))
    return ranked[:MAX_CANDIDATES]


# --- aliases.yml --------------------------------------------------------------------------


def note_for(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= NOTE_MAX else text[: NOTE_MAX - 1] + "…"


def entry_yaml(d: Decision) -> str:
    entry: dict[str, Any] = {"alias": d.alias}
    if d.tmdb_id is not None:
        entry["tmdb_id"] = d.tmdb_id
    if d.local_key is not None:
        entry["local_key"] = d.local_key
    if d.cinema_id is not None:
        entry["cinema_id"] = d.cinema_id
    entry["note"] = note_for(d.note)
    return yaml.safe_dump([entry], sort_keys=False, allow_unicode=True, width=1000)


def appended(text: str, decisions: Iterable[Decision]) -> str:
    """``aliases.yml`` text with the entries appended; comments are kept."""
    body = text.rstrip()
    if body.endswith("[]"):  # the empty list of a fresh file
        body = body[:-2].rstrip()
    for d in decisions:
        body += "\n\n" + entry_yaml(d).rstrip()
    return body + "\n"


def write_aliases(config_dir: Path, decisions: list[Decision]) -> None:
    """Append and validate (the whole config is loaded from a temporary copy first).
    Raises :class:`ConfigError` and leaves the file untouched when anything is wrong."""
    path = config_dir / "aliases.yml"
    current = load_config(config_dir)
    taken = {(a.alias, a.cinema_id) for a in current.aliases}
    for d in decisions:
        if (d.alias, d.cinema_id) in taken:
            raise ConfigError([f"aliases.yml already has {d.alias!r} (cinema {d.cinema_id})"])
        taken.add((d.alias, d.cinema_id))
    new_text = appended(path.read_text(encoding="utf-8"), decisions)
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("cinemas.yml", "cities.yml"):
            shutil.copy(config_dir / name, Path(tmp) / name)
        (Path(tmp) / "aliases.yml").write_text(new_text, encoding="utf-8", newline="\n")
        load_config(Path(tmp))  # raises ConfigError
    path.write_text(new_text, encoding="utf-8", newline="\n")


# --- interactive review ---------------------------------------------------------------


def describe(item: ReviewItem) -> str:
    where = f"{item.shows} upcoming shows at {', '.join(item.cinemas)}" if item.cinemas else ""
    return f"{item.title}  ({item.status}{'; ' + where if where else ''})"


HELP = (
    "  number = pick · t <id> = TMDB id · l <localKey> = join a local movie · s = skip · q = quit"
)


def review(
    items: list[ReviewItem],
    find: Callable[[ReviewItem], list[Candidate]],
    ask: Callable[[str], str],
    say: Callable[[str], None],
    today: date,
) -> list[Decision]:
    decisions: list[Decision] = []
    for n, item in enumerate(items, 1):
        say(f"\n[{n}/{len(items)}] {describe(item)}")
        say(f'  alias: "{item.key}"')
        found = find(item)
        for i, c in enumerate(found, 1):
            year = f" ({c.year})" if c.year else ""
            say(f"  {i}) {c.title}{year}  tmdb {c.tmdb_id}  score {c.score:.0f}")
        if not found:
            say("  no TMDB candidates")
        say(HELP)
        while True:
            answer = ask("> ").strip()
            if answer in ("s", ""):
                break
            if answer == "q":
                return decisions
            pick = _decide(item, answer, found, today)
            if pick is None:
                say("  ?" + HELP)
                continue
            decisions.append(pick)
            say(f"  → {pick.note}")
            break
    return decisions


def _decide(item: ReviewItem, answer: str, found: list[Candidate], today: date) -> Decision | None:
    stamp = f"review {today.isoformat()}: {item.title}"
    if answer.isdigit() and 1 <= int(answer) <= len(found):
        c = found[int(answer) - 1]
        year = f" ({c.year})" if c.year else ""
        return Decision(item.key, f"{stamp} → {c.title}{year}", tmdb_id=c.tmdb_id)
    verb, _, value = answer.partition(" ")
    value = value.strip()
    if verb == "t" and value.isdigit() and int(value) > 0:
        return Decision(item.key, f"{stamp} → TMDB {value}", tmdb_id=int(value))
    if verb == "l" and value:
        return Decision(item.key, f"{stamp} → local movie {value}", local_key=value)
    return None


# --- command line ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review unmatched titles into aliases.yml.")
    parser.add_argument("--list", action="store_true", help="only list what needs review")
    parser.add_argument("--add", metavar="ALIAS", help="append one alias without the database")
    parser.add_argument("--tmdb-id", type=int, help="with --add")
    parser.add_argument("--local-key", help="with --add")
    parser.add_argument("--cinema-id", help="with --add: only for this cinema")
    parser.add_argument("--note", help="with --add: why this correction exists")
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    args = parser.parse_args(argv)

    if args.add:
        if (args.tmdb_id is None) == (args.local_key is None) or not args.note:
            parser.error("--add needs exactly one of --tmdb-id/--local-key, and --note")
        decision = Decision(
            args.add, args.note, args.tmdb_id, args.local_key, args.cinema_id or None
        )
        return _write(args.config_dir, [decision])

    try:
        manual = {a.alias for a in load_config(args.config_dir).aliases}
        client, db = connect(DbSettings.from_env())
    except (ConfigError, DatabaseUnavailableError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        items = review_items(db, manual, datetime.now(UTC))
    finally:
        client.close()
    if not items:
        print("nothing to review")
        return 0
    if args.list:
        for item in items:
            print(f'- "{item.key}": {describe(item)}')
        return 0

    key = os.environ.get("TMDB_API_KEY", "").strip()
    tmdb = TmdbClient(key) if key else None
    if tmdb is None:
        print("note: TMDB_API_KEY not set; no candidates (type t <id> or l <localKey>)")

    def find(item: ReviewItem) -> list[Candidate]:
        if tmdb is None:
            return []
        try:
            return candidates(item, tmdb.search_movie)
        except TmdbError as exc:
            print(f"  TMDB search failed: {exc}")
            return []

    try:
        decisions = review(items, find, input, print, datetime.now(UTC).date())
    finally:
        if tmdb is not None:
            tmdb.close()
    if not decisions:
        print("no changes")
        return 0
    return _write(args.config_dir, decisions)


def _write(config_dir: Path, decisions: list[Decision]) -> int:
    try:
        write_aliases(config_dir, decisions)
    except ConfigError as exc:
        print(f"error: aliases.yml not changed: {exc}", file=sys.stderr)
        return 2
    print(f"aliases.yml: {len(decisions)} entr{'y' if len(decisions) == 1 else 'ies'} added.")
    print("Next: open a PR with scraper/config/aliases.yml; the next full run re-links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
