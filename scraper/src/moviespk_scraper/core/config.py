"""Load and validate the human-edited config files (plan §8.3, P1-03).

* ``scraper/config/cities.yml``   — the single source of truth for cities;
* ``scraper/config/cinemas.yml``  — cinemas, their robots evidence and coordinates;
* ``scraper/config/aliases.yml``  — manual movie-title corrections.

Any problem raises :class:`ConfigError` listing **every** problem found, each with the
file and entry it belongs to, so one run of the validator shows everything to fix.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from ..adapters import registry
from ..adapters.base import FetchMode
from ..models.vocab import MAX_LAT, MAX_LNG, MIN_LAT, MIN_LNG, RESERVED_PATHS, RadiusKm
from ..pipeline.text import normalize_text

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
MIN_DELAY_FLOOR_MS = 1500

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)]
HttpUrl = Annotated[str, StringConstraints(pattern=r"^https?://[^\s/]+(/\S*)?$", max_length=2048)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Phone = Annotated[str, StringConstraints(pattern=r"^\+?[0-9][0-9 ()-]{5,30}$")]


class ConfigError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("invalid configuration:\n- " + "\n- ".join(problems))
        self.problems = problems


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_lng_lat(value: tuple[float, float]) -> tuple[float, float]:
    lng, lat = value
    if not (MIN_LNG <= lng <= MAX_LNG and MIN_LAT <= lat <= MAX_LAT):
        raise ValueError(
            f"[{lng}, {lat}] is outside the Pakistan bounding box "
            f"(lng {MIN_LNG}..{MAX_LNG}, lat {MIN_LAT}..{MAX_LAT}); is it [lng, lat]?"
        )
    return value


# --- cities ----------------------------------------------------------------------------


class CityConfig(_Model):
    slug: Slug
    name: Text
    center: tuple[float, float]
    default_radius_km: RadiusKm

    _center = field_validator("center")(_check_lng_lat)

    @field_validator("slug")
    @classmethod
    def _not_reserved(cls, value: str) -> str:
        if value in RESERVED_PATHS:
            raise ValueError(
                f"city slug {value!r} collides with a reserved web path "
                f"({', '.join(RESERVED_PATHS)}; plan §8.3)"
            )
        return value


# --- cinemas ---------------------------------------------------------------------------


class EvidenceEndpoint(_Model):
    path: Annotated[str, StringConstraints(pattern=r"^/\S*$")]
    allowed: bool


class Evidence(_Model):
    checked_at: date
    robots_sha256: Sha256 | None
    terms_url: HttpUrl | None
    terms_sha256: Sha256 | None
    endpoints: list[EvidenceEndpoint] = Field(min_length=1)


class CinemaConfig(_Model):
    id: Slug
    chain: Slug
    adapter: str
    branch: str | None = None
    fetch_mode: FetchMode
    base_url: HttpUrl
    name: Text
    address: Text
    city: Slug
    location: tuple[float, float]
    phone: Phone | None = None
    booking_url_template: HttpUrl | None = None
    min_delay_ms: int = MIN_DELAY_FLOOR_MS
    max_concurrency: Literal[1] = 1
    enabled: bool
    seats_allowed: bool = False
    #: The path seat data is fetched from; needs an Allowed evidence row when seats are on.
    seat_path: str | None = None
    robots_policy: Literal["respect", "permission_granted"]
    permission_ref: str | None = None
    evidence: Evidence

    _location = field_validator("location")(_check_lng_lat)

    @model_validator(mode="before")
    @classmethod
    def _robots_ignore_is_never_allowed(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("robots_policy") == "ignore":
            raise ValueError(
                "robots_policy 'ignore' is not allowed: MoviesPK always respects robots.txt "
                "(ADR-0001, docs/adr/0001-respect-robots-txt.md). Use 'respect', or "
                "'permission_granted' with a permission_ref"
            )
        return data

    @field_validator("min_delay_ms")
    @classmethod
    def _delay_floor(cls, value: int) -> int:
        if value < MIN_DELAY_FLOOR_MS:
            raise ValueError(f"min_delay_ms must be at least {MIN_DELAY_FLOOR_MS} (plan §10.2)")
        return value

    @model_validator(mode="after")
    def _cross_field_rules(self) -> CinemaConfig:
        if self.robots_policy == "permission_granted" and not (self.permission_ref or "").strip():
            raise ValueError("robots_policy 'permission_granted' requires permission_ref")
        allowed = {e.path for e in self.evidence.endpoints if e.allowed}
        if self.seats_allowed:
            if not self.seat_path:
                raise ValueError("seats_allowed: true requires seat_path")
            if self.robots_policy == "respect" and self.seat_path not in allowed:
                raise ValueError(
                    f"seats_allowed: true requires an evidence endpoint row for the seat path "
                    f"{self.seat_path!r} with allowed: true"
                )
        if self.enabled and self.robots_policy == "respect":
            refused = [e.path for e in self.evidence.endpoints if not e.allowed]
            if refused:
                raise ValueError(
                    f"an enabled cinema cannot have Disallowed evidence endpoints {refused} "
                    "(plan P0-08: Disallowed → excluded unless permission is granted)"
                )
        return self


# --- aliases ---------------------------------------------------------------------------


class AliasConfig(_Model):
    alias: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    tmdb_id: Annotated[int, Field(gt=0)] | None = None
    local_key: Annotated[str, StringConstraints(min_length=1, max_length=120)] | None = None
    cinema_id: Slug | None = None
    note: Text

    @field_validator("alias")
    @classmethod
    def _normalized(cls, value: str) -> str:
        expected = normalize_text(value).lower()
        if value != expected:
            raise ValueError(f"alias must be normalized (lowercase, single spaces): {expected!r}")
        return value

    @model_validator(mode="after")
    def _exactly_one_target(self) -> AliasConfig:
        if (self.tmdb_id is None) == (self.local_key is None):
            raise ValueError("give exactly one of tmdb_id or local_key")
        return self


# --- loading ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AppConfig:
    cities: tuple[CityConfig, ...]
    cinemas: tuple[CinemaConfig, ...]
    aliases: tuple[AliasConfig, ...]

    def cinema(self, cinema_id: str) -> CinemaConfig:
        for c in self.cinemas:
            if c.id == cinema_id:
                return c
        raise KeyError(cinema_id)

    @property
    def enabled_cinemas(self) -> tuple[CinemaConfig, ...]:
        return tuple(c for c in self.cinemas if c.enabled)


def _read_list(path: Path, *, required: bool) -> list[Any]:
    if not path.exists():
        if required:
            raise ConfigError([f"{path.name}: file not found ({path})"])
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return []
    if not isinstance(data, list):
        raise ConfigError([f"{path.name}: the top level must be a list"])
    return data


def _where(file: str, index: int, item: Any, key: str) -> str:
    ident = item.get(key) if isinstance(item, dict) else None
    return f"{file}[{index}]" + (f" ({ident})" if ident else "")


def _errors(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        msg = re.sub(r"^(Value|Assertion) error, ", "", err["msg"])
        out.append(f"{loc}: {msg}" if loc else msg)
    return out


def _parse[M: BaseModel](
    model: type[M], items: list[Any], file: str, key: str, problems: list[str]
) -> list[M]:
    parsed: list[M] = []
    for i, item in enumerate(items):
        try:
            parsed.append(model.model_validate(item))
        except ValidationError as exc:
            problems.extend(f"{_where(file, i, item, key)}: {e}" for e in _errors(exc))
    return parsed


def _keys(items: list[Any], key: str) -> list[str]:
    return [str(i[key]) for i in items if isinstance(i, dict) and i.get(key) is not None]


def _duplicates(values: list[str]) -> list[str]:
    return sorted(v for v, n in Counter(values).items() if n > 1)


def load_config(config_dir: Path = CONFIG_DIR) -> AppConfig:
    """Load and validate all three files; raise :class:`ConfigError` listing every problem."""
    problems: list[str] = []

    raw_cities = _read_list(config_dir / "cities.yml", required=True)
    raw_cinemas = _read_list(config_dir / "cinemas.yml", required=True)
    raw_aliases = _read_list(config_dir / "aliases.yml", required=False)
    cities = _parse(CityConfig, raw_cities, "cities.yml", "slug", problems)
    cinemas = _parse(CinemaConfig, raw_cinemas, "cinemas.yml", "id", problems)
    aliases = _parse(AliasConfig, raw_aliases, "aliases.yml", "alias", problems)

    # Duplicates are checked on the raw entries, so an invalid copy still counts.
    for slug in _duplicates(_keys(raw_cities, "slug")):
        problems.append(f"cities.yml: duplicate slug {slug!r}")
    for cid in _duplicates(_keys(raw_cinemas, "id")):
        problems.append(f"cinemas.yml: duplicate id {cid!r}")
    for key in _duplicates([f"{a.alias}|{a.cinema_id or ''}" for a in aliases]):
        alias, _, cinema = key.partition("|")
        problems.append(f"aliases.yml: duplicate alias {alias!r} for cinema {cinema or '(all)'}")

    city_slugs = {c.slug for c in cities}
    cinema_ids = {c.id for c in cinemas}
    for c in cinemas:
        where = f"cinemas.yml ({c.id})"
        if c.city not in city_slugs:
            problems.append(f"{where}: city {c.city!r} is not a slug in cities.yml")
        try:
            spec = registry.spec(c.adapter)
        except registry.UnknownAdapterError:
            known = ", ".join(sorted(registry.specs()))
            problems.append(f"{where}: unknown adapter {c.adapter!r} (known: {known})")
            continue
        if spec.fetch_mode != c.fetch_mode:
            problems.append(
                f"{where}: fetch_mode {c.fetch_mode!r} does not match adapter "
                f"{c.adapter!r} ({spec.fetch_mode})"
            )
        if c.enabled and not spec.implemented:
            problems.append(
                f"{where}: adapter {c.adapter!r} is not implemented yet; keep enabled: false"
            )
    for a in aliases:
        if a.cinema_id is not None and a.cinema_id not in cinema_ids:
            problems.append(f"aliases.yml ({a.alias}): unknown cinema_id {a.cinema_id!r}")

    if problems:
        raise ConfigError(problems)
    return AppConfig(tuple(cities), tuple(cinemas), tuple(aliases))
