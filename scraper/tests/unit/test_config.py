"""P1-03: config loading and validation (plan §8.3)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from moviespk_scraper.adapters import registry
from moviespk_scraper.core.config import CONFIG_DIR, ConfigError, load_config

CITY = {"slug": "lahore", "name": "Lahore", "center": [74.3587, 31.5204], "default_radius_km": 25}

CINEMA: dict[str, Any] = {
    "id": "cinepax-packages-mall",
    "chain": "cinepax",
    "adapter": "cinepax",
    "branch": "0000000014",
    "fetch_mode": "json",
    "base_url": "https://web.cinepax.com",
    "name": "Cinepax Packages Mall",
    "address": "Packages Mall, Walton Road, Lahore",
    "city": "lahore",
    "location": [74.35692, 31.47169],
    "min_delay_ms": 1500,
    "max_concurrency": 1,
    "enabled": False,
    "seats_allowed": False,
    "robots_policy": "respect",
    "evidence": {
        "checked_at": "2026-11-25",
        "robots_sha256": None,
        "terms_url": "https://web.cinepax.com/api/cms/pages/terms",
        "terms_sha256": "62dc051de906e2d48dd27ce4df9a5f7e9a554a6b2b8ba4153b6bf407546a2d56",
        "endpoints": [{"path": "/api/cinemas", "allowed": True}],
    },
}


def write(
    tmp_path: Path,
    *,
    cinemas: list[Any] | None = None,
    cities: list[Any] | None = None,
    aliases: list[Any] | None = None,
) -> Path:
    (tmp_path / "cities.yml").write_text(yaml.safe_dump(cities or [CITY]), encoding="utf-8")
    (tmp_path / "cinemas.yml").write_text(
        yaml.safe_dump(cinemas if cinemas is not None else [CINEMA]), encoding="utf-8"
    )
    if aliases is not None:
        (tmp_path / "aliases.yml").write_text(yaml.safe_dump(aliases), encoding="utf-8")
    return tmp_path


def cinema(**changes: Any) -> dict[str, Any]:
    c = copy.deepcopy(CINEMA)
    for key, value in changes.items():
        if value is None:
            c.pop(key, None)
        else:
            c[key] = value
    return c


def problems(tmp_path: Path, **kwargs: Any) -> str:
    with pytest.raises(ConfigError) as info:
        load_config(write(tmp_path, **kwargs))
    return str(info.value)


# --- the real files ---------------------------------------------------------------------


def test_repository_config_is_valid() -> None:
    config = load_config(CONFIG_DIR)
    assert len(config.cinemas) >= 5
    assert {c.city for c in config.cinemas} <= {c.slug for c in config.cities}


# --- acceptance (plan P1-03) ------------------------------------------------------------


def test_valid_minimal_config_loads(tmp_path: Path) -> None:
    config = load_config(write(tmp_path))
    assert config.cinema("cinepax-packages-mall").min_delay_ms == 1500
    assert config.aliases == ()  # aliases.yml is optional


def test_robots_ignore_cites_adr_0001(tmp_path: Path) -> None:
    msg = problems(tmp_path, cinemas=[cinema(robots_policy="ignore")])
    assert "ADR-0001" in msg


def test_permission_granted_requires_ref(tmp_path: Path) -> None:
    assert "permission_ref" in problems(
        tmp_path, cinemas=[cinema(robots_policy="permission_granted")]
    )
    ok = cinema(robots_policy="permission_granted", permission_ref="email 2026-12-01")
    assert load_config(write(tmp_path, cinemas=[ok])).cinemas[0].permission_ref


@pytest.mark.parametrize(
    "location",
    [[31.47, 74.35], [0.0, 0.0], [80.0, 30.0], [70.0, 40.0]],  # swapped, null island, out
)
def test_coordinates_outside_bounding_box_fail(tmp_path: Path, location: list[float]) -> None:
    assert "bounding box" in problems(tmp_path, cinemas=[cinema(location=location)])


def test_missing_location_fails(tmp_path: Path) -> None:
    assert "location" in problems(tmp_path, cinemas=[cinema(location=None)])


def test_seats_without_seat_evidence_row_fails(tmp_path: Path) -> None:
    no_path = problems(tmp_path, cinemas=[cinema(seats_allowed=True)])
    assert "seat_path" in no_path
    no_row = problems(tmp_path, cinemas=[cinema(seats_allowed=True, seat_path="/api/movies")])
    assert "seat path" in no_row
    ev = copy.deepcopy(CINEMA["evidence"])
    ev["endpoints"].append({"path": "/api/movies", "allowed": True})
    ok = cinema(seats_allowed=True, seat_path="/api/movies", evidence=ev)
    assert load_config(write(tmp_path, cinemas=[ok])).cinemas[0].seats_allowed


def test_seat_path_disallowed_in_evidence_fails(tmp_path: Path) -> None:
    ev = copy.deepcopy(CINEMA["evidence"])
    ev["endpoints"].append({"path": "/api/seats", "allowed": False})
    msg = problems(
        tmp_path, cinemas=[cinema(seats_allowed=True, seat_path="/api/seats", evidence=ev)]
    )
    assert "seat path" in msg


def test_unknown_adapter_fails_at_load(tmp_path: Path) -> None:
    msg = problems(tmp_path, cinemas=[cinema(adapter="nueplex")])
    assert "unknown adapter 'nueplex'" in msg and "cinepax" in msg


def test_fetch_mode_must_match_adapter(tmp_path: Path) -> None:
    assert "does not match adapter" in problems(tmp_path, cinemas=[cinema(fetch_mode="html")])


@pytest.mark.parametrize("slug", ["about", "privacy", "status", "search", "near-me", "api"])
def test_reserved_city_slug_fails(tmp_path: Path, slug: str) -> None:
    city = {**CITY, "slug": slug}
    msg = problems(tmp_path, cities=[CITY, city], cinemas=[])
    assert "reserved web path" in msg


def test_cinema_city_must_exist(tmp_path: Path) -> None:
    assert "not a slug in cities.yml" in problems(tmp_path, cinemas=[cinema(city="quetta")])


def test_phone_is_optional(tmp_path: Path) -> None:
    with_phone = cinema(id="with-phone", phone="+92 42 111-246-372")
    without = cinema(id="without-phone")
    config = load_config(write(tmp_path, cinemas=[with_phone, without]))
    assert config.cinema("with-phone").phone == "+92 42 111-246-372"
    assert config.cinema("without-phone").phone is None
    assert "phone" in problems(tmp_path, cinemas=[cinema(phone="call us")])


# --- further rules ------------------------------------------------------------------------


def test_enabled_needs_an_implemented_adapter(tmp_path: Path) -> None:
    assert not registry.spec("vista").implemented
    vista = cinema(adapter="vista", fetch_mode="html", enabled=True)
    assert "not implemented yet" in problems(tmp_path, cinemas=[vista])


def test_enabled_cinema_cannot_have_disallowed_evidence(tmp_path: Path) -> None:
    ev = copy.deepcopy(CINEMA["evidence"])
    ev["endpoints"].append({"path": "/private", "allowed": False})
    assert "Disallowed" in problems(tmp_path, cinemas=[cinema(evidence=ev, enabled=True)])


def test_min_delay_floor(tmp_path: Path) -> None:
    assert "at least 1500" in problems(tmp_path, cinemas=[cinema(min_delay_ms=500)])


def test_max_concurrency_must_be_one(tmp_path: Path) -> None:
    assert "max_concurrency" in problems(tmp_path, cinemas=[cinema(max_concurrency=2)])


def test_unknown_keys_and_duplicates_fail(tmp_path: Path) -> None:
    msg = problems(tmp_path, cinemas=[cinema(colour="red"), cinema()])
    assert "colour" in msg and "duplicate id 'cinepax-packages-mall'" in msg


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    bad = cinema(id="bad-one", robots_policy="ignore")
    worse = cinema(id="bad-two", city="quetta", location=[0, 0])
    with pytest.raises(ConfigError) as info:
        load_config(write(tmp_path, cinemas=[bad, worse]))
    assert len(info.value.problems) >= 2
    assert any("bad-one" in p for p in info.value.problems)
    assert any("bad-two" in p for p in info.value.problems)


# --- aliases --------------------------------------------------------------------------------


def test_aliases_load(tmp_path: Path) -> None:
    aliases = [
        {"alias": "mission impossible 9", "tmdb_id": 575265, "note": "site drops the subtitle"},
        {
            "alias": "jawani phir nahi ani 3",
            "local_key": "jpna3",
            "cinema_id": "cinepax-packages-mall",
            "note": "not on TMDB yet",
        },
    ]
    config = load_config(write(tmp_path, aliases=aliases))
    assert len(config.aliases) == 2


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ({"alias": "Mission Impossible", "tmdb_id": 1, "note": "n"}, "normalized"),
        ({"alias": "x", "note": "n"}, "exactly one"),
        ({"alias": "x", "tmdb_id": 1, "local_key": "k", "note": "n"}, "exactly one"),
        ({"alias": "x", "tmdb_id": 1, "cinema_id": "nowhere", "note": "n"}, "unknown cinema_id"),
        ({"alias": "x", "tmdb_id": 1}, "note"),
    ],
)
def test_alias_rules(tmp_path: Path, alias: dict[str, Any], expected: str) -> None:
    assert expected in problems(tmp_path, aliases=[alias])


# --- registry -------------------------------------------------------------------------------


def test_registry_rejects_unknown_and_unimplemented() -> None:
    with pytest.raises(registry.UnknownAdapterError):
        registry.get_adapter("nope")
    with pytest.raises(registry.AdapterNotImplementedError):
        registry.get_adapter("vista")


def test_register_checks_fetch_mode() -> None:
    with pytest.raises(ValueError, match="declared as html"):
        registry.register("vista", "json", lambda: None)  # type: ignore[arg-type,return-value]
