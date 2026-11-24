// Shared vocabularies, written by hand to match shared/constants/*.json.
// The contract suite asserts equality (plan §13). Change shared/, Pydantic and Zod together.

export const FORMATS = ["2D", "3D", "IMAX", "4DX", "OTHER"] as const;
export const SEAT_STATUSES = ["available", "filling", "sold_out", "unknown"] as const;
export const MATCH_STATUSES = ["matched", "provisional", "unmatched"] as const;
export const RUN_STATUSES = ["ok", "partial", "failed", "blocked", "drift"] as const;
export const HEALTH_STATUSES = ["ok", "partial", "failed", "blocked", "drift", "unknown"] as const;
export const JOBS = ["full", "seats", "canary"] as const;
export const SHOWTIME_STATUSES = ["active", "cancelled"] as const;
export const ALIAS_SOURCES = ["auto", "manual", "pending"] as const;
export const RADIUS_KM = [5, 10, 25, 50] as const;
export const GENRES = [
  "action",
  "adventure",
  "animation",
  "comedy",
  "crime",
  "documentary",
  "drama",
  "family",
  "fantasy",
  "history",
  "horror",
  "music",
  "mystery",
  "romance",
  "science-fiction",
  "thriller",
  "war",
  "western",
  "other",
] as const;
export const LANGUAGES = ["ur", "en", "pa", "hi", "ps", "sd", "other"] as const;
export const RESERVED_PATHS = [
  "about",
  "privacy",
  "status",
  "search",
  "near-me",
  "movies",
  "cinemas",
  "api",
] as const;

export const POSTER_WIDTHS = [185, 342, 780] as const;
export const POSTER_KEY_PATTERN = "^movies/[0-9a-f]{24}/poster-[0-9a-f]{8}$";

// Pakistan bounding box (plan §8.1).
export const BOUNDS = { minLng: 60.8, maxLng: 77.9, minLat: 23.6, maxLat: 37.1 } as const;

/** shared/constants file stem → the values declared here. */
export const VOCABULARIES: Record<string, readonly (string | number)[]> = {
  formats: FORMATS,
  "seat-statuses": SEAT_STATUSES,
  "match-statuses": MATCH_STATUSES,
  "run-statuses": RUN_STATUSES,
  "health-statuses": HEALTH_STATUSES,
  jobs: JOBS,
  "showtime-statuses": SHOWTIME_STATUSES,
  "alias-sources": ALIAS_SOURCES,
  "radius-km": RADIUS_KM,
  genres: GENRES,
  languages: LANGUAGES,
  "reserved-paths": RESERVED_PATHS,
};
