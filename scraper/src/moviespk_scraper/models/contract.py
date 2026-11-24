"""Pydantic models for the shared contract (``shared/schemas/*.json``).

Written by hand (no code generation). Semantics mirror the JSON Schemas:

* unknown fields are rejected (``extra="forbid"``);
* strict types: no string-to-number or number-to-string coercion;
* an optional field may be omitted but never sent as ``null``, unless the field is
  explicitly nullable (``Movie.poster``, ``ShowtimeMovie.posterKey``);
* timestamps are UTC strings ending in ``Z``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    Strict,
    StringConstraints,
    model_validator,
)

from moviespk_scraper.models.vocab import (
    MAX_LAT,
    MAX_LNG,
    MIN_LAT,
    MIN_LNG,
    POSTER_KEY_PATTERN,
    Format,
    Genre,
    HealthStatus,
    Job,
    Language,
    MatchStatus,
    RadiusKm,
    RunStatus,
    SeatStatusValue,
    ShowtimeStatus,
)

_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")


def _utc_string_form(value: Any) -> Any:
    if isinstance(value, str) and not _UTC_RE.match(value):
        raise ValueError("timestamp must be ISO 8601 UTC ending in 'Z'")
    return value


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != UTC.utcoffset(None):
        raise ValueError("timestamp must be in UTC")
    return value


UtcDateTime = Annotated[
    AwareDatetime,
    Strict(False),
    BeforeValidator(_utc_string_form),
    AfterValidator(_require_utc),
]
IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)]
ObjectIdHex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{24}$")]
Url = Annotated[str, StringConstraints(pattern=r"^https?://", max_length=2048)]
PosterKey = Annotated[str, StringConstraints(pattern=POSTER_KEY_PATTERN)]
Latitude = Annotated[float, Field(ge=MIN_LAT, le=MAX_LAT)]
Longitude = Annotated[float, Field(ge=MIN_LNG, le=MAX_LNG)]
NonNegInt = Annotated[int, Field(ge=0)]


def _text(max_length: int, min_length: int = 1) -> StringConstraints:
    return StringConstraints(min_length=min_length, max_length=max_length)


Text20 = Annotated[str, _text(20)]
Text40 = Annotated[str, _text(40)]
Text60 = Annotated[str, _text(60)]
Text80 = Annotated[str, _text(80)]
Text120 = Annotated[str, _text(120)]
Text200 = Annotated[str, _text(200)]
Text300 = Annotated[str, _text(300)]
Text500 = Annotated[str, _text(500)]
Synopsis = Annotated[str, _text(2000, 0)]
ErrorMessage = Annotated[str, _text(300, 0)]


class ContractModel(BaseModel):
    """Base: strict, closed, and ``null`` only where explicitly allowed."""

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    #: Field names (Python names) that may be ``null``.
    nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for name, field in cls.model_fields.items():
                key = field.alias or name
                if key in data and data[key] is None and name not in cls.nullable:
                    raise ValueError(f"'{key}' must be omitted rather than null")
        return data


class LatLng(ContractModel):
    lat: Latitude
    lng: Longitude


def _check_lng_lat(value: list[float]) -> list[float]:
    lng, lat = value
    if not (MIN_LNG <= lng <= MAX_LNG and MIN_LAT <= lat <= MAX_LAT):
        raise ValueError("coordinates must be [lng, lat] inside Pakistan's bounding box")
    return value


class GeoPoint(ContractModel):
    type: Annotated[str, StringConstraints(pattern=r"^Point$")]
    coordinates: Annotated[
        list[float], Field(min_length=2, max_length=2), AfterValidator(_check_lng_lat)
    ]


class CinemaHealth(ContractModel):
    status: HealthStatus
    last_success_at: UtcDateTime | None = Field(default=None, alias="lastSuccessAt")
    last_run_at: UtcDateTime | None = Field(default=None, alias="lastRunAt")


class SeatStatus(ContractModel):
    status: SeatStatusValue
    available: NonNegInt | None = None
    total: Annotated[int, Field(ge=1)] | None = None
    as_of: UtcDateTime | None = Field(default=None, alias="asOf")


class City(ContractModel):
    slug: Slug
    name: Text80
    center: LatLng
    default_radius_km: RadiusKm = Field(alias="defaultRadiusKm")


class _CinemaBase(ContractModel):
    chain: Text80
    name: Text120
    city: Slug
    address: Text300
    phone: Text40 | None = None
    website_url: Url = Field(alias="websiteUrl")
    booking_url_template: Url | None = Field(default=None, alias="bookingUrlTemplate")
    facilities: list[Text60]
    seats_enabled: bool = Field(alias="seatsEnabled")
    last_scraped_at: UtcDateTime | None = Field(default=None, alias="lastScrapedAt")
    health: CinemaHealth


class Cinema(_CinemaBase):
    """Stored ``cinemas`` document (GeoJSON location)."""

    id: Slug = Field(alias="_id")
    location: GeoPoint
    enabled: bool
    created_at: UtcDateTime = Field(alias="createdAt")
    updated_at: UtcDateTime = Field(alias="updatedAt")


class CinemaResponse(_CinemaBase):
    """Cinema item as returned by the API (``{lat, lng}`` location)."""

    id: Slug
    location: LatLng
    distance_km: Annotated[float, Field(ge=0)] | None = Field(default=None, alias="distanceKm")


class Poster(ContractModel):
    key: PosterKey
    width: Annotated[int, Field(ge=1)]
    height: Annotated[int, Field(ge=1)]


class Rating(ContractModel):
    certification: Text20 | None = None
    tmdb_score: Annotated[float, Field(ge=0, le=10)] | None = Field(default=None, alias="tmdbScore")


class Movie(ContractModel):
    nullable: ClassVar[frozenset[str]] = frozenset({"poster"})

    id: ObjectIdHex
    tmdb_id: Annotated[int, Field(ge=1)] | None = Field(default=None, alias="tmdbId")
    slug: Slug
    title: Text200
    original_title: Text200 | None = Field(default=None, alias="originalTitle")
    year: Annotated[int, Field(ge=1900, le=2100)] | None = None
    synopsis: Synopsis | None = None
    genres: list[Genre]
    runtime_min: Annotated[int, Field(ge=30, le=300)] | None = Field(
        default=None, alias="runtimeMin"
    )
    languages: list[Language]
    rating: Rating
    poster: Poster | None
    trailer_url: Url | None = Field(default=None, alias="trailerUrl")
    release_date: IsoDate | None = Field(default=None, alias="releaseDate")
    match_status: MatchStatus = Field(alias="matchStatus")
    now_showing: bool = Field(alias="nowShowing")


class ShowtimeCinema(ContractModel):
    name: Text120
    city: Slug


class ShowtimeMovie(ContractModel):
    nullable: ClassVar[frozenset[str]] = frozenset({"poster_key"})

    title: Text200
    slug: Slug
    poster_key: PosterKey | None = Field(alias="posterKey")
    genres: list[Genre]
    runtime_min: Annotated[int, Field(ge=30, le=300)] | None = Field(
        default=None, alias="runtimeMin"
    )


class Showtime(ContractModel):
    id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    cinema_id: Slug = Field(alias="cinemaId")
    movie_id: ObjectIdHex = Field(alias="movieId")
    starts_at: UtcDateTime = Field(alias="startsAt")
    ends_at: UtcDateTime | None = Field(default=None, alias="endsAt")
    hall: Text60 | None = None
    format: Format
    language: Language
    seats: SeatStatus
    booking_url: Url | None = Field(default=None, alias="bookingUrl")
    status: ShowtimeStatus
    cinema: ShowtimeCinema
    movie: ShowtimeMovie


class RunCounts(ContractModel):
    movies: NonNegInt
    showtimes: NonNegInt
    upserted: NonNegInt
    invalid: NonNegInt
    cancelled: NonNegInt
    images_uploaded: NonNegInt = Field(alias="imagesUploaded")
    images_failed: NonNegInt = Field(alias="imagesFailed")


class RunError(ContractModel):
    type: Text60
    message: ErrorMessage
    url: Annotated[str, StringConstraints(max_length=2048)] | None = None


class ScrapeRun(ContractModel):
    job: Job
    cinema_id: Slug = Field(alias="cinemaId")
    started_at: UtcDateTime = Field(alias="startedAt")
    finished_at: UtcDateTime | None = Field(default=None, alias="finishedAt")
    status: RunStatus
    counts: RunCounts
    errors: Annotated[list[RunError], Field(max_length=20)]
    github_run_id: Annotated[str, StringConstraints(pattern=r"^\d+$")] | None = Field(
        default=None, alias="githubRunId"
    )


class Meta(ContractModel):
    generated_at: UtcDateTime = Field(alias="generatedAt")
    data_as_of: UtcDateTime | None = Field(default=None, alias="dataAsOf")


class Envelope(ContractModel):
    nullable: ClassVar[frozenset[str]] = frozenset({"data"})

    data: Any
    meta: Meta


class ErrorBody(ContractModel):
    nullable: ClassVar[frozenset[str]] = frozenset({"details"})

    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]*$")]
    message: Text500
    details: Any = None


class ErrorResponse(ContractModel):
    error: ErrorBody


#: Contract type name (``shared/schemas/<Name>.json``) → Pydantic model.
CONTRACT_MODELS: dict[str, type[ContractModel]] = {
    "Cinema": Cinema,
    "CinemaResponse": CinemaResponse,
    "City": City,
    "Movie": Movie,
    "Showtime": Showtime,
    "SeatStatus": SeatStatus,
    "ScrapeRun": ScrapeRun,
    "Envelope": Envelope,
    "Error": ErrorResponse,
}
