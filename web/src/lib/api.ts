/**
 * Server-side API access (plan §9.2, §9.3). Server components call the API project's
 * production domain directly (`API_ORIGIN`); browsers use the same-origin `/api/*`
 * rewrite in next.config.ts. A failed call returns `null` so pages render a fallback
 * instead of failing the build or the request.
 */

export interface City {
  slug: string;
  name: string;
  center: { lat: number; lng: number };
  defaultRadiusKm: number;
}

export function apiOrigin(): string | null {
  const origin = process.env.API_ORIGIN?.trim().replace(/\/+$/, "");
  return origin ? origin : null;
}

function isCity(value: unknown): value is City {
  if (typeof value !== "object" || value === null) return false;
  const c = value as Record<string, unknown>;
  const center = c.center as Record<string, unknown> | undefined;
  return (
    typeof c.slug === "string" &&
    typeof c.name === "string" &&
    typeof center?.lat === "number" &&
    typeof center.lng === "number" &&
    typeof c.defaultRadiusKm === "number"
  );
}

/** `GET /api/v1/cities`, revalidated hourly like the API's edge cache. */
export async function fetchCities(): Promise<City[] | null> {
  const origin = apiOrigin();
  if (origin === null) return null;
  try {
    const res = await fetch(`${origin}/api/v1/cities`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    const body: unknown = await res.json();
    const data = (body as { data?: unknown }).data;
    return Array.isArray(data) && data.every(isCity) ? data : null;
  } catch {
    return null;
  }
}
