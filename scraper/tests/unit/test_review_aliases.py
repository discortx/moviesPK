"""P2-04: scripts/review_aliases.py (appending, validation, the review loop)."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

from moviespk_scraper.core.config import CONFIG_DIR, ConfigError, load_config
from moviespk_scraper.services.tmdb import TmdbCandidate

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "review_aliases.py"
TODAY = date(2026, 11, 28)


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("review_aliases", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["review_aliases"] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    for name in ("cinemas.yml", "cities.yml", "aliases.yml"):
        shutil.copy(CONFIG_DIR / name, tmp_path / name)
    return tmp_path


# --- aliases.yml ------------------------------------------------------------------------


def test_append_keeps_comments_and_existing_entries(tool: ModuleType, config_dir: Path) -> None:
    before = (config_dir / "aliases.yml").read_text(encoding="utf-8")
    d = tool.Decision("avengers endgame encore re release", "re-release", tmdb_id=299534)
    tool.write_aliases(config_dir, [d])
    after = (config_dir / "aliases.yml").read_text(encoding="utf-8")
    assert after.startswith(before.rstrip())  # comments and the Belkis entry untouched
    aliases = {a.alias: a for a in load_config(config_dir).aliases}
    assert aliases["avengers endgame encore re release"].tmdb_id == 299534
    assert aliases["belkis"].local_key == "belkis-2026"


def test_append_to_an_empty_list(tool: ModuleType) -> None:
    text = "# header\n[]\n"
    out = tool.appended(text, [tool.Decision("hope", "x", tmdb_id=1)])
    assert out.startswith("# header\n\n- alias: hope\n") and "[]" not in out


def test_quotes_and_long_notes_are_safe(tool: ModuleType, config_dir: Path) -> None:
    d = tool.Decision("babil in laneti", 'Babil\'in "Laneti": ' + "x" * 300, tmdb_id=1680302)
    tool.write_aliases(config_dir, [d])
    [entry] = [a for a in load_config(config_dir).aliases if a.alias == "babil in laneti"]
    assert len(entry.note) == 200 and entry.note.startswith('Babil\'in "Laneti"')


@pytest.mark.parametrize(
    ("decision", "problem"),
    [
        (("belkis", "dup", None, "belkis-2026", "universal-emporium-mall-lahore"), "already"),
        (("Not Normalized", "x", 5, None, None), "normalized"),
        (("hope", "x", None, None, None), "exactly one"),
    ],
    ids=["duplicate", "not-normalized", "no-target"],
)
def test_invalid_entries_leave_the_file_untouched(
    tool: ModuleType, config_dir: Path, decision: tuple, problem: str
) -> None:
    before = (config_dir / "aliases.yml").read_bytes()
    with pytest.raises(ConfigError, match=problem):
        tool.write_aliases(config_dir, [tool.Decision(*decision)])
    assert (config_dir / "aliases.yml").read_bytes() == before


def test_add_command(tool: ModuleType, config_dir: Path) -> None:
    code = tool.main(
        ["--add", "janj abbey di", "--local-key", "janj-abbey-di", "--note", "no TMDB entry",
         "--config-dir", str(config_dir)]
    )  # fmt: skip
    assert code == 0
    assert "janj abbey di" in {a.alias for a in load_config(config_dir).aliases}


def test_add_needs_one_target(tool: ModuleType, config_dir: Path) -> None:
    with pytest.raises(SystemExit):
        tool.main(["--add", "x", "--note", "n", "--config-dir", str(config_dir)])


# --- review loop ------------------------------------------------------------------------


def item(tool: ModuleType, **kw: object) -> object:
    base = {"key": "hexed", "title": "Hexed", "status": "unmatched", "shows": 4,
            "cinemas": ["cinestar-township-lahore"]}  # fmt: skip
    return tool.ReviewItem(**(base | kw))


def run_review(tool: ModuleType, items: list, answers: list[str], found: list) -> list:
    replies = iter(answers)
    said: list[str] = []
    out = tool.review(items, lambda _i: found, lambda _p: next(replies), said.append, TODAY)
    return out


def test_pick_tmdb_id_local_key_skip_and_quit(tool: ModuleType) -> None:
    found = [tool.Candidate(1538497, "Hexed", 2026, 100.0)]
    items = [item(tool), item(tool, key="hope", title="Hope"), item(tool, key="x", title="X")]
    decisions = run_review(tool, items, ["1", "t 1058424", "q"], found)
    assert [(d.alias, d.tmdb_id) for d in decisions] == [("hexed", 1538497), ("hope", 1058424)]
    assert decisions[0].note == "review 2026-11-28: Hexed → Hexed (2026)"

    [joined] = run_review(tool, [item(tool, key="belkis")], ["l belkis-2026"], [])
    assert joined.local_key == "belkis-2026" and joined.tmdb_id is None
    assert run_review(tool, [item(tool)], ["s"], found) == []


def test_bad_answers_ask_again(tool: ModuleType) -> None:
    found = [tool.Candidate(1, "Hexed", None, 90.0)]
    [d] = run_review(tool, [item(tool)], ["9", "t abc", "zzz", "1"], found)
    assert d.tmdb_id == 1


def test_candidates_are_ranked_and_keep_the_matcher_suggestion(tool: ModuleType) -> None:
    results = [
        TmdbCandidate(10, "Avengers: Infinity War", None, date(2018, 4, 25)),
        TmdbCandidate(299534, "Avengers: Endgame", None, date(2019, 4, 24)),
    ]
    probe = item(tool, key="avengers endgame encore re release",
                 title="Avengers: Endgame Encore (Re-release)", suggested_tmdb_id=777)  # fmt: skip
    ranked = tool.candidates(probe, lambda _q, _y: results)
    assert ranked[0].tmdb_id == 777 and ranked[0].title == "(matcher suggestion)"
    assert [c.tmdb_id for c in ranked[1:]] == [299534, 10]
