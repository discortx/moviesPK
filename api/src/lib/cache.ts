import type { RequestHandler } from "express";

/** Edge cache policy for one route (plan §9.1, §9.2). */
export interface CachePolicy {
  /** Edge TTL in seconds. */
  cdnTtl: number;
  /** stale-while-revalidate in seconds. */
  swr?: number;
  /** stale-if-error in seconds. */
  sie?: number;
}

/**
 * Sets the plan §9.2 cache headers: `Vercel-CDN-Cache-Control` for the Vercel edge,
 * `Cache-Control: public, max-age=60` for browsers, and `x-vercel-enable-rewrite-caching: 1`
 * so the response is cached when reached through the web project's rewrite.
 */
export function cacheHeaders(policy: CachePolicy): RequestHandler {
  const parts = [`max-age=${policy.cdnTtl}`];
  if (policy.swr !== undefined) parts.push(`stale-while-revalidate=${policy.swr}`);
  if (policy.sie !== undefined) parts.push(`stale-if-error=${policy.sie}`);
  const cdn = parts.join(", ");
  return (_req, res, next) => {
    res.set("Vercel-CDN-Cache-Control", cdn);
    res.set("Cache-Control", "public, max-age=60");
    res.set("x-vercel-enable-rewrite-caching", "1");
    next();
  };
}
