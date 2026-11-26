import type { RequestHandler } from "express";

/**
 * CORS for a read-only GET API (plan §9.2): only origins listed in `CORS_ALLOWED_ORIGINS`
 * (comma-separated) get `Access-Control-Allow-Origin`. Browser traffic is normally
 * same-origin through the web project's rewrite, so this matters only for direct calls.
 */
export function cors(
  allowed: string | undefined = process.env.CORS_ALLOWED_ORIGINS,
): RequestHandler {
  const origins = new Set(
    (allowed ?? "")
      .split(",")
      .map((o) => o.trim().replace(/\/+$/, ""))
      .filter(Boolean),
  );
  return (req, res, next) => {
    const origin = req.headers.origin;
    res.vary("Origin");
    if (origin && origins.has(origin)) {
      res.set("Access-Control-Allow-Origin", origin);
      res.set("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
      res.set("Access-Control-Max-Age", "600");
    }
    if (req.method === "OPTIONS") {
      res.status(204).end();
      return;
    }
    next();
  };
}
