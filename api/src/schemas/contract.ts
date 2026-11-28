// Zod schemas for the shared contract (shared/schemas/*.json), written by hand.
// Semantics mirror the JSON Schemas: closed objects, no type coercion, optional fields may
// be omitted but not null (except Movie.poster and Showtime.movie.posterKey), UTC "Z" times.
import { z } from "zod";
import {
  BOUNDS,
  FORMATS,
  GENRES,
  HEALTH_STATUSES,
  JOBS,
  LANGUAGES,
  MATCH_STATUSES,
  POSTER_KEY_PATTERN,
  RUN_STATUSES,
  SEAT_STATUSES,
  SHOWTIME_STATUSES,
} from "./vocab.js";

const text = (max: number, min = 1) => z.string().min(min).max(max);

export const UtcDateTime = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$/)
  .refine((s) => !Number.isNaN(Date.parse(s)), "invalid date");
export const IsoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
export const Slug = z
  .string()
  .max(80)
  .regex(/^[a-z0-9]+(-[a-z0-9]+)*$/);
export const ObjectIdHex = z.string().regex(/^[0-9a-f]{24}$/);
export const Url = z
  .string()
  .max(2048)
  .regex(/^https?:\/\//);
export const PosterKey = z.string().regex(new RegExp(POSTER_KEY_PATTERN));
export const Latitude = z.number().min(BOUNDS.minLat).max(BOUNDS.maxLat);
export const Longitude = z.number().min(BOUNDS.minLng).max(BOUNDS.maxLng);
const NonNegInt = z.int().min(0);

export const Genre = z.enum(GENRES);
export const Language = z.enum(LANGUAGES);
export const Format = z.enum(FORMATS);

export const LatLng = z.strictObject({ lat: Latitude, lng: Longitude });

export const GeoPoint = z.strictObject({
  type: z.literal("Point"),
  coordinates: z.tuple([Longitude, Latitude]),
});

export const CinemaHealth = z.strictObject({
  status: z.enum(HEALTH_STATUSES),
  lastSuccessAt: UtcDateTime.optional(),
  lastRunAt: UtcDateTime.optional(),
});

export const SeatStatus = z.strictObject({
  status: z.enum(SEAT_STATUSES),
  available: NonNegInt.optional(),
  total: z.int().min(1).optional(),
  asOf: UtcDateTime.optional(),
});

export const City = z.strictObject({
  slug: Slug,
  name: text(80),
  center: LatLng,
  defaultRadiusKm: z.union([z.literal(5), z.literal(10), z.literal(25), z.literal(50)]),
});

const cinemaBase = {
  chain: text(80),
  name: text(120),
  city: Slug,
  address: text(300),
  phone: text(40).optional(),
  websiteUrl: Url,
  bookingUrlTemplate: Url.optional(),
  facilities: z.array(text(60)),
  seatsEnabled: z.boolean(),
  lastScrapedAt: UtcDateTime.optional(),
  health: CinemaHealth,
};

/** Stored cinemas document (GeoJSON location). */
export const Cinema = z.strictObject({
  ...cinemaBase,
  _id: Slug,
  location: GeoPoint,
  enabled: z.boolean(),
  createdAt: UtcDateTime,
  updatedAt: UtcDateTime,
});

/** Cinema item returned by the API ({lat, lng} location). */
export const CinemaResponse = z.strictObject({
  ...cinemaBase,
  id: Slug,
  location: LatLng,
  distanceKm: z.number().min(0).optional(),
});

export const Poster = z.strictObject({
  key: PosterKey,
  width: z.int().min(1),
  height: z.int().min(1),
});

const RuntimeMin = z.int().min(30).max(300);

export const Movie = z.strictObject({
  id: ObjectIdHex,
  tmdbId: z.int().min(1).optional(),
  slug: Slug,
  title: text(200),
  originalTitle: text(200).optional(),
  year: z.int().min(1900).max(2100).optional(),
  synopsis: text(2000, 0).optional(),
  genres: z.array(Genre),
  runtimeMin: RuntimeMin.optional(),
  languages: z.array(Language),
  rating: z.strictObject({
    certification: text(20).optional(),
    tmdbScore: z.number().min(0).max(10).optional(),
  }),
  poster: Poster.nullable(),
  trailerUrl: Url.optional(),
  releaseDate: IsoDate.optional(),
  matchStatus: z.enum(MATCH_STATUSES),
  nowShowing: z.boolean(),
});

export const Showtime = z.strictObject({
  id: z.string().regex(/^[0-9a-f]{40}$/),
  cinemaId: Slug,
  movieId: ObjectIdHex,
  startsAt: UtcDateTime,
  endsAt: UtcDateTime.optional(),
  hall: text(60).optional(),
  format: Format,
  language: Language,
  seats: SeatStatus,
  bookingUrl: Url.optional(),
  status: z.enum(SHOWTIME_STATUSES),
  cinema: z.strictObject({ name: text(120), city: Slug }),
  movie: z.strictObject({
    title: text(200),
    slug: Slug,
    posterKey: PosterKey.nullable(),
    genres: z.array(Genre),
    runtimeMin: RuntimeMin.optional(),
  }),
});

export const ScrapeRun = z.strictObject({
  job: z.enum(JOBS),
  cinemaId: Slug,
  startedAt: UtcDateTime,
  finishedAt: UtcDateTime.optional(),
  status: z.enum(RUN_STATUSES),
  counts: z.strictObject({
    movies: NonNegInt,
    showtimes: NonNegInt,
    upserted: NonNegInt,
    invalid: NonNegInt,
    cancelled: NonNegInt,
    imagesUploaded: NonNegInt,
    imagesFailed: NonNegInt,
  }),
  errors: z
    .array(
      z.strictObject({
        type: text(60),
        message: text(300, 0),
        url: z.string().max(2048).optional(),
      }),
    )
    .max(20),
  githubRunId: z.string().regex(/^\d+$/).optional(),
  /** canary only: Atlas data + index bytes (P2-03). */
  storageBytes: NonNegInt.optional(),
});

export const Meta = z.strictObject({
  generatedAt: UtcDateTime,
  dataAsOf: UtcDateTime.optional(),
});

export const Envelope = z
  .strictObject({ data: z.unknown(), meta: Meta })
  .refine((o) => o.data !== undefined, { message: "data is required", path: ["data"] });

export const ErrorResponse = z.strictObject({
  error: z.strictObject({
    code: z.string().regex(/^[a-z][a-z_]*$/),
    message: text(500),
    details: z.unknown().optional(),
  }),
});

/** Contract type name (shared/schemas/<Name>.json) → Zod schema. */
export const CONTRACT_SCHEMAS: Record<string, z.ZodType> = {
  Cinema,
  CinemaResponse,
  City,
  Movie,
  Showtime,
  SeatStatus,
  ScrapeRun,
  Envelope,
  Error: ErrorResponse,
};
