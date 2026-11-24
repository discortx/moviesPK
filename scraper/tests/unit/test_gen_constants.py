"""Tests for scripts/gen_constants.py (plan P0-06)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gen_constants.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_constants", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = _load()


def _city(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "slug": "lahore",
        "name": "Lahore",
        "center": [74.3587, 31.5204],
        "default_radius_km": 25,
    }
    return base | over


def test_builds_latlng_shape() -> None:
    assert gen.build_cities([_city()]) == [
        {
            "slug": "lahore",
            "name": "Lahore",
            "center": {"lat": 31.5204, "lng": 74.3587},
            "defaultRadiusKm": 25,
        }
    ]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"slug": "about"}, "reserved"),
        ({"slug": "near-me"}, "reserved"),
        ({"slug": "Lahore"}, "invalid slug"),
        ({"center": [31.5204, 74.3587]}, "outside Pakistan"),
        ({"center": [74.3]}, "center must be"),
        ({"default_radius_km": 7}, "default_radius_km"),
        ({"extra": 1}, "unknown keys"),
    ],
)
def test_rejects_bad_city(override: dict[str, Any], message: str) -> None:
    with pytest.raises(gen.CityConfigError, match=message):
        gen.build_cities([_city(**override)])


def test_rejects_duplicates() -> None:
    with pytest.raises(gen.CityConfigError, match="duplicate"):
        gen.build_cities([_city(), _city()])


def test_committed_cities_json_is_current() -> None:
    assert gen.main(["--check"]) == 0


def test_check_fails_when_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stale = tmp_path / "cities.json"
    stale.write_text(json.dumps([]), encoding="utf-8")
    monkeypatch.setattr(gen, "CITIES_JSON", stale)
    assert gen.main(["--check"]) == 1
