#!/usr/bin/env python3
"""Generate shared/constants/cities.json from scraper/config/cities.yml (plan §9.2).

    python scripts/gen_constants.py          # write cities.json
    python scripts/gen_constants.py --check  # exit 1 if cities.json is stale (CI)

cities.yml is the only human-edited city list. Validation: unique slugs in slug form,
no slug equal to a reserved web path, centre inside Pakistan's bounding box,
default_radius_km one of the allowed radii.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CITIES_YML = ROOT / "scraper" / "config" / "cities.yml"
CONSTANTS = ROOT / "shared" / "constants"
CITIES_JSON = CONSTANTS / "cities.json"
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class CityConfigError(ValueError):
    pass


def _load_json(name: str) -> Any:
    return json.loads((CONSTANTS / name).read_text(encoding="utf-8"))


def build_cities(raw: Any) -> list[dict[str, Any]]:
    """Validate the parsed YAML and return the cities.json payload."""
    reserved = set(_load_json("reserved-paths.json"))
    radii = set(_load_json("radius-km.json"))
    box = _load_json("bounds.json")["pakistan"]
    if not isinstance(raw, list) or not raw:
        raise CityConfigError("cities.yml must be a non-empty list")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        where = f"cities.yml entry {i}"
        if not isinstance(item, dict):
            raise CityConfigError(f"{where}: must be a mapping")
        unknown = set(item) - {"slug", "name", "center", "default_radius_km"}
        if unknown:
            raise CityConfigError(f"{where}: unknown keys {sorted(unknown)}")
        slug, name = item.get("slug"), item.get("name")
        if not isinstance(slug, str) or not SLUG_RE.match(slug) or len(slug) > 80:
            raise CityConfigError(f"{where}: invalid slug {slug!r}")
        if slug in reserved:
            raise CityConfigError(f"{where}: slug {slug!r} collides with a reserved web path")
        if slug in seen:
            raise CityConfigError(f"{where}: duplicate slug {slug!r}")
        seen.add(slug)
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise CityConfigError(f"{where}: invalid name")
        center = item.get("center")
        if (
            not isinstance(center, list)
            or len(center) != 2
            or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in center)
        ):
            raise CityConfigError(f"{where}: center must be [lng, lat]")
        lng, lat = float(center[0]), float(center[1])
        if not (box["minLng"] <= lng <= box["maxLng"] and box["minLat"] <= lat <= box["maxLat"]):
            raise CityConfigError(f"{where}: center {center} outside Pakistan (is it [lng, lat]?)")
        radius = item.get("default_radius_km")
        if radius not in radii or isinstance(radius, bool):
            raise CityConfigError(f"{where}: default_radius_km must be one of {sorted(radii)}")
        out.append(
            {
                "slug": slug,
                "name": name.strip(),
                "center": {"lat": lat, "lng": lng},
                "defaultRadiusKm": radius,
            }
        )
    return out


def render(cities: list[dict[str, Any]]) -> str:
    return json.dumps(cities, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if cities.json is stale")
    args = parser.parse_args(argv)
    try:
        expected = render(build_cities(yaml.safe_load(CITIES_YML.read_text(encoding="utf-8"))))
    except CityConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.check:
        current = CITIES_JSON.read_text(encoding="utf-8") if CITIES_JSON.exists() else ""
        if current != expected:
            print(
                "error: shared/constants/cities.json is stale; "
                "run `python scripts/gen_constants.py` and commit the result",
                file=sys.stderr,
            )
            return 1
        print("cities.json is up to date")
        return 0
    CITIES_JSON.write_text(expected, encoding="utf-8", newline="\n")
    print(f"wrote {CITIES_JSON.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
