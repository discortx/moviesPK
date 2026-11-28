"""P2-07a: scripts/purge_cinema.py against MongoDB (plan §12.5, §17.3, §18.4).

* ``--dry-run`` deletes nothing;
* ``--showtimes`` removes only that cinema's showtimes; other cinemas untouched;
* ``--all`` removes the cinema document, its scrape_runs and its non-manual
  cinema-specific aliases, while movies stay;
* an unknown or malformed id exits 2 with no writes;
* a wrong confirmation aborts with no writes;
* ``--all`` is refused while the YAML entry is enabled.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from moviespk_scraper.core.config import CONFIG_DIR
from moviespk_scraper.db.client import DB

from .test_upsert import run_pipeline

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "purge_cinema.py"
TARGET = "cinestar-township-lahore"
OTHER = "universal-emporium-mall-lahore"
COLLECTIONS = ("cinemas", "showtimes", "scrape_runs", "movie_aliases", "movies")


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("purge_cinema", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["purge_cinema"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seeded(db: DB) -> DB:
    run_pipeline(db, [TARGET, OTHER])
    now = datetime(2026, 11, 28, tzinfo=UTC)
    for cinema in (TARGET, OTHER):
        db.scrape_runs.insert_one({"job": "full", "cinemaId": cinema, "startedAt": now})
    db.movie_aliases.insert_many(
        [
            {"_id": f"hexed|{TARGET}", "movieKey": "1", "source": "auto", "cinemaId": TARGET},
            {"_id": f"hope|{TARGET}", "movieKey": "2", "source": "pending", "cinemaId": TARGET},
            {"_id": f"kept|{TARGET}", "movieKey": "3", "source": "manual", "cinemaId": TARGET},
            {"_id": f"hexed|{OTHER}", "movieKey": "1", "source": "auto", "cinemaId": OTHER},
            {"_id": "global", "movieKey": "4", "source": "auto"},
        ]
    )
    return db


@pytest.fixture
def disabled_config(tmp_path: Path) -> Path:
    """cinemas.yml with TARGET set to enabled: false (step 1 of §18.4)."""
    for name in ("cinemas.yml", "cities.yml", "aliases.yml"):
        shutil.copy(CONFIG_DIR / name, tmp_path / name)
    data = yaml.safe_load((tmp_path / "cinemas.yml").read_text(encoding="utf-8"))
    for item in data:
        if item["id"] == TARGET:
            item["enabled"] = False
    (tmp_path / "cinemas.yml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return tmp_path


def counts(db: DB) -> dict[str, int]:
    return {c: db[c].count_documents({}) for c in COLLECTIONS}


def run(
    tool: ModuleType,
    db: DB,
    cinema: str,
    mode: str,
    *,
    dry_run: bool = False,
    yes: bool = False,
    answer: str = "",
    config_dir: Path = CONFIG_DIR,
) -> int:
    code: int = tool.purge(
        db, cinema, mode, dry_run=dry_run, yes=yes, ask=lambda _p: answer, config_dir=config_dir
    )
    return code


def test_dry_run_deletes_nothing(
    tool: ModuleType, seeded: DB, capsys: pytest.CaptureFixture[str]
) -> None:
    before = counts(seeded)
    shows = seeded.showtimes.count_documents({"cinemaId": TARGET})
    assert run(tool, seeded, TARGET, "showtimes", dry_run=True) == 0
    assert counts(seeded) == before
    out = capsys.readouterr().out
    assert f"showtimes: {shows}" in out and "dry run: nothing deleted" in out


def test_showtimes_removes_only_that_cinemas_showtimes(tool: ModuleType, seeded: DB) -> None:
    other = seeded.showtimes.count_documents({"cinemaId": OTHER})
    before = counts(seeded)
    assert run(tool, seeded, TARGET, "showtimes", answer=TARGET) == 0
    assert seeded.showtimes.count_documents({"cinemaId": TARGET}) == 0
    assert seeded.showtimes.count_documents({"cinemaId": OTHER}) == other == 97
    after = counts(seeded)
    assert {k: v for k, v in after.items() if k != "showtimes"} == {
        k: v for k, v in before.items() if k != "showtimes"
    }


def test_all_removes_cinema_runs_and_non_manual_aliases_movies_stay(
    tool: ModuleType, seeded: DB, disabled_config: Path
) -> None:
    movies = seeded.movies.count_documents({})
    assert run(tool, seeded, TARGET, "all", yes=True, config_dir=disabled_config) == 0
    assert seeded.cinemas.count_documents({"_id": TARGET}) == 0
    assert seeded.showtimes.count_documents({"cinemaId": TARGET}) == 0
    assert seeded.scrape_runs.count_documents({"cinemaId": TARGET}) == 0
    assert sorted(d["_id"] for d in seeded.movie_aliases.find({})) == [
        "global",
        f"hexed|{OTHER}",
        f"kept|{TARGET}",  # manual: YAML is its source
    ]
    assert seeded.movies.count_documents({}) == movies
    assert seeded.cinemas.count_documents({"_id": OTHER}) == 1
    assert seeded.scrape_runs.count_documents({"cinemaId": OTHER}) == 1


@pytest.mark.parametrize("cinema", ["nowhere-cinema", "Bad_ID", "../etc", "a" * 81, ""])
def test_unknown_or_malformed_id_exits_2_with_no_writes(
    tool: ModuleType, seeded: DB, cinema: str
) -> None:
    before = counts(seeded)
    assert run(tool, seeded, cinema, "showtimes", yes=True) == 2
    assert counts(seeded) == before


def test_wrong_confirmation_aborts_with_no_writes(tool: ModuleType, seeded: DB) -> None:
    before = counts(seeded)
    assert run(tool, seeded, TARGET, "showtimes", answer="cinestar") == 1
    assert run(tool, seeded, TARGET, "showtimes", answer="") == 1
    assert counts(seeded) == before


def test_all_refused_while_enabled_in_yaml(
    tool: ModuleType, seeded: DB, capsys: pytest.CaptureFixture[str]
) -> None:
    before = counts(seeded)
    assert run(tool, seeded, TARGET, "all", yes=True) == 2  # the real cinemas.yml: enabled
    assert counts(seeded) == before
    assert "still enabled" in capsys.readouterr().err


def test_command_line(
    tool: ModuleType, seeded: DB, mongo_uri: str, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    monkeypatch.setenv("MONGODB_URI_SCRAPER", mongo_uri)
    monkeypatch.setenv("MONGODB_DB", seeded.name)
    with pytest.raises(SystemExit):  # exactly one of --showtimes / --all
        tool.main(["--cinema", TARGET])
    with pytest.raises(SystemExit):
        tool.main(["--cinema", TARGET, "--showtimes", "--all"])
    assert tool.main(["--cinema", "Bad_ID", "--showtimes"]) == 2
    assert tool.main(["--cinema", TARGET, "--showtimes", "--yes"]) == 0
    out: Any = capsys.readouterr()
    assert seeded.showtimes.count_documents({"cinemaId": TARGET}) == 0
    assert mongo_uri not in out.out + out.err
    assert "purge.done" in out.err  # the structured log line
