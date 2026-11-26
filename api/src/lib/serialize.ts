import type { Document, ObjectId } from "mongodb";
import { toLatLng, type GeoPoint } from "./geo.js";

/**
 * Stored documents → API items (plan §9.1). Internal fields (`localKey`, `missCount`,
 * `lastSeenAt`, `expireAt`, `createdAt`, `updatedAt`, `enabled`, ...) are never exposed;
 * ObjectIds become hex strings and dates ISO strings; optional fields are omitted when
 * absent, never `null` (except `poster`, which the contract allows to be null).
 */

type Json = Record<string, unknown>;

const iso = (value: unknown): string | undefined =>
  value instanceof Date ? value.toISOString() : undefined;

function pick(doc: Document, keys: readonly string[]): Json {
  const out: Json = {};
  for (const key of keys) {
    const value: unknown = doc[key];
    if (value !== undefined && value !== null)
      out[key] = value instanceof Date ? iso(value) : value;
  }
  return out;
}

const CINEMA_FIELDS = [
  "chain",
  "name",
  "city",
  "address",
  "phone",
  "websiteUrl",
  "bookingUrlTemplate",
  "facilities",
  "seatsEnabled",
  "lastScrapedAt",
] as const;

export function cinemaItem(doc: Document): Json {
  const health = (doc.health ?? {}) as Document;
  return {
    id: doc._id,
    ...pick(doc, CINEMA_FIELDS),
    facilities: doc.facilities ?? [],
    seatsEnabled: Boolean(doc.seatsEnabled),
    health: pick({ status: health.status ?? "unknown", ...health }, [
      "status",
      "lastSuccessAt",
      "lastRunAt",
    ]),
    location: toLatLng(doc.location as GeoPoint),
  };
}

const MOVIE_FIELDS = [
  "tmdbId",
  "slug",
  "title",
  "originalTitle",
  "year",
  "synopsis",
  "runtimeMin",
  "trailerUrl",
  "releaseDate",
  "matchStatus",
] as const;

export function movieItem(doc: Document): Json {
  return {
    id: (doc._id as ObjectId).toHexString(),
    ...pick(doc, MOVIE_FIELDS),
    genres: doc.genres ?? [],
    languages: doc.languages ?? [],
    rating: pick((doc.rating ?? {}) as Document, ["certification", "tmdbScore"]),
    poster: doc.poster ?? null,
    nowShowing: Boolean(doc.nowShowing),
  };
}

const SHOWTIME_FIELDS = [
  "cinemaId",
  "startsAt",
  "endsAt",
  "hall",
  "format",
  "language",
  "bookingUrl",
  "status",
] as const;

export function showtimeItem(doc: Document): Json {
  const seats = (doc.seats ?? { status: "unknown" }) as Document;
  const movie = (doc.movie ?? {}) as Document;
  return {
    id: doc._id,
    movieId: (doc.movieId as ObjectId).toHexString(),
    ...pick(doc, SHOWTIME_FIELDS),
    seats: pick(seats, ["status", "available", "total", "asOf"]),
    cinema: pick((doc.cinema ?? {}) as Document, ["name", "city"]),
    movie: {
      ...pick(movie, ["title", "slug", "genres", "runtimeMin"]),
      posterKey: movie.posterKey ?? null,
      genres: movie.genres ?? [],
    },
  };
}
