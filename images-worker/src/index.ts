/**
 * Worker `moviespk-img` (plan §11.3.2, P1-19): posters from a private R2 bucket.
 *
 * - Methods: GET and HEAD; anything else → 405 with `Allow: GET, HEAD`, R2 untouched.
 * - Paths: only `/img/movies/<24 hex>/poster-<8 hex>-w(185|342|780).webp`, matched on the
 *   raw (still percent-encoded) path, so `..`, encoded slashes and uppercase hex never
 *   match; anything else → 404, R2 untouched. The key is the path without `/img/`.
 * - Query strings: any non-empty query → 404, R2 untouched (the cache key includes the
 *   query, so this stops cache-busting from reaching R2).
 * - R2: `get` (GET) or `head` (HEAD); missing object → 404; an R2 exception → 503
 *   `no-store`. The body streams straight from R2.
 * - Headers: 200 → `image/webp`, one-year `immutable` cache, the R2 ETag, length,
 *   `nosniff`; 404 → cacheable for 60 s so a missing key cannot hammer R2. Never cookies.
 * - No logging of IPs or Referers; no Referer/Origin check (plan Q9, OD11).
 */

export interface Env {
  /** The private images bucket (`moviespk-prod`, or `moviespk-dev` with `--env dev`). */
  IMAGES: R2Bucket;
}

export const POSTER_PATH = /^\/img\/movies\/[a-f0-9]{24}\/poster-[a-f0-9]{8}-w(185|342|780)\.webp$/;
const PREFIX = "/img/";

const NOSNIFF = { "X-Content-Type-Options": "nosniff" } as const;

function plain(status: number, text: string, headers: Record<string, string>): Response {
  return new Response(`${text}\n`, {
    status,
    headers: { "Content-Type": "text/plain; charset=utf-8", ...NOSNIFF, ...headers },
  });
}

const notFound = (): Response => plain(404, "Not found", { "Cache-Control": "public, max-age=60" });

const methodNotAllowed = (): Response =>
  plain(405, "Method not allowed", { Allow: "GET, HEAD", "Cache-Control": "no-store" });

const unavailable = (): Response =>
  plain(503, "Service unavailable", { "Cache-Control": "no-store" });

function posterHeaders(object: R2Object): Headers {
  return new Headers({
    "Content-Type": "image/webp",
    "Cache-Control": "public, max-age=31536000, immutable",
    ETag: object.httpEtag,
    "Content-Length": String(object.size),
    ...NOSNIFF,
  });
}

export async function handle(request: Request, env: Env): Promise<Response> {
  if (request.method !== "GET" && request.method !== "HEAD") return methodNotAllowed();

  const url = new URL(request.url);
  if (url.search !== "" || !POSTER_PATH.test(url.pathname)) return notFound();
  const key = url.pathname.slice(PREFIX.length);

  try {
    if (request.method === "HEAD") {
      const head = await env.IMAGES.head(key);
      return head === null
        ? notFound()
        : new Response(null, { status: 200, headers: posterHeaders(head) });
    }
    const object = await env.IMAGES.get(key);
    return object === null
      ? notFound()
      : new Response(object.body, { status: 200, headers: posterHeaders(object) });
  } catch {
    return unavailable();
  }
}

export default {
  fetch: (request, env) => handle(request, env),
} satisfies ExportedHandler<Env>;
