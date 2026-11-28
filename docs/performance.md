# Performance evidence

The single place for performance measurements (plan §3.2 targets). One section per
measurement. Each entry records: **date**, **environment** (dev / preview / prod),
**method or command**, **raw numbers**, **target** and **verdict** (Pass / Fail / Risk).

## 1. API cold start (P1-14)

_Target: cache-miss p95 under 1,500 ms including a cold function start._

### 2026-11-26 15:21 UTC: prod (`https://moviespk-api.vercel.app`), function region `bom1`, Atlas Mumbai

- **Method:** no requests for 21 minutes after the last one, then `GET /api/v1/health`
  (`no-store`, so never cached; it opens the MongoDB connection and pings) from a home
  connection in Pakistan, then 5 more requests 1 s apart. `curl -w` timings.
- **Raw numbers (ms):**

  | Request | Total | TCP connect | TLS done | First byte |
  |---|---|---|---|---|
  | cold | **1,803** | 162 | 289 | 1,789 |
  | warm 1 | 282 | 57 | 177 | 281 |
  | warm 2 | 339 | 55 | 215 | 339 |
  | warm 3 | 275 | 54 | 173 | 275 |
  | warm 4 | 334 | 52 | 216 | 333 |
  | warm 5 | 302 | 73 | 195 | 301 |

- **Reading:** about 290 ms of the cold request is the client's own DNS/TCP/TLS setup;
  the server side (function start + new TLS-authenticated Atlas connection + ping) is
  about 1,500 ms. Warm requests are 275-339 ms end to end.
- **Verdict: Risk.** One cold sample is just over the 1,500 ms target. Mitigating factors:
  the data endpoints (P1-15) are edge-cached for 5-60 min, so a visitor rarely meets a
  cold function on a cache miss; `/health` is the worst case (never cached, always pings).
  Re-measure with more samples on a data endpoint in P1-16 (edge HIT vs MISS) and P4-03.
  If misses stay over target, options in order: keep TTLs/SWR long (already planned),
  trim cold-start imports, then revisit the target with the owner (no paid option, OD4).

## 2. Edge HIT vs MISS latency through the rewrite (P1-16)

_Target: edge-cache hit p95 under 300 ms; miss p95 under 1,500 ms._

### 2026-11-26 16:45 UTC: prod, `https://moviespk-web.vercel.app/api/v1/movies` (rewrite → `moviespk-api`, `bom1`), dev data

- **Method:** 16 distinct URLs never requested before (8 cities × dates 2026-11-30 and
  2026-12-01, `GET /api/v1/movies?city=…&date=…`), each fetched once (MISS), then the same
  16 again (HIT). Client: a home connection in Pakistan, `curl -w`. Passes 1 and 2 used a
  new process (new TCP + TLS connection) per request; pass 3 fetched the 16 HIT URLs over
  one reused connection, as a browser does.
- **Raw numbers (ms, total time):**

  | Pass | `x-vercel-cache` | n | min | median | p95 | max |
  |---|---|---|---|---|---|---|
  | 1: first request, new connection each | 16 × MISS | 16 | 273 | 305 | **523** | 529 |
  | 2: repeat, new connection each | 16 × HIT | 16 | 229 | 271 | 305 | 511 |
  | 3: repeat, one reused connection (first request excluded: 327 incl. handshake) | HIT | 15 | — | **88** | **114** | 170 |

- **Reading:** caching through the cross-project rewrite works (every repeat was a HIT).
  About 200 ms of every pass-2 request is the client's own TCP/TLS handshake; with
  connection reuse a HIT is about 90 ms. The misses were served by warm functions (the
  API had just been used), so they do not cover a cold start (§1).
- **Verdict:** MISS **Pass** (p95 523 < 1,500). HIT **Pass** for browser-like traffic
  (p95 114 < 300); the per-request-handshake p95 (305) is at the target and is dominated
  by the client's connection setup, not by the edge. Re-measure under load in P4-03.
- **Preview check (owner, 2026-11-26 16:43 UTC):** the `moviespk-web` preview of this PR
  (`moviespk-web-git-feat-p1-16-web-shell-….vercel.app`, Vercel Authentication on for
  previews) rendered the city list, and its `/api/v1/cities` returned the JSON list, not a
  Deployment Protection page: the rewrite to the API's production domain works from
  previews too.

## 3. Worker cache and header test (P1-21)

_Target: `Cf-Cache-Status` MISS then HIT; immutable `Cache-Control`; 404/405 behaviour._

### 2026-11-28 11:52 UTC: dev, `https://moviespk-img-dev.moviespk.workers.dev`, real TMDB poster

- **Method:** `scripts/check_image_cache.sh <worker-url> movies/6b08dedc90bcf1349ae4a3ee/poster-2e3986cd-w342.webp`
  (poster uploaded by scrape-full #11). The same poster's very first request, a few
  minutes earlier, returned `MISS` and the next one `HIT`, both with ETag
  `"c57262ed3f17bac62ebe4936645b1ed1"`.
- **Result:**

  | Request | Status | Content-Type | Cf-Cache-Status | Cache-Control | ETag | Verdict |
  |---|---|---|---|---|---|---|
  | poster, 1st | 200 | image/webp | HIT | public, max-age=31536000, immutable | "c57262ed3f17bac62ebe4936645b1ed1" | ok |
  | poster, 2nd | 200 | image/webp | HIT | public, max-age=31536000, immutable | "c57262ed3f17bac62ebe4936645b1ed1" | ok |
  | missing key, 1st | 404 | text/plain; charset=utf-8 | HIT | public, max-age=60 | - | ok |
  | missing key, 2nd | 404 | text/plain; charset=utf-8 | HIT | public, max-age=60 | - | ok |
  | rejected path | 404 | text/plain; charset=utf-8 | HIT | public, max-age=60 | - | ok |
  | query string | 404 | text/plain; charset=utf-8 | HIT | public, max-age=60 | - | ok |
  | POST | 405 | text/plain; charset=utf-8 | - | no-store | - | ok |

- **Also seen:** a cached 404 reported `EXPIRED` once its 60 s had passed, then `HIT`
  again: 404s are cached for exactly their `max-age` (U-CF7).
- **Redeploy with no code change (`cross_version_cache`):** deploy-images-worker run #2
  (`workflow_dispatch`, 2026-11-28; dev live 11:56:22 UTC). The first requests afterwards
  were still `HIT` with `Age: 412`-`422` s, i.e. cached before the redeploy: the cache
  survives deploys.
- **Verdict: Pass** (all P1-21 expectations met).

## 4. Worker load probe (P1-22)

_Target: per §11.3.2 / §7.4.2 forecast; no Error 1027._

### 2026-11-28 11:58:07-12:00:30 UTC: dev, `moviespk-img-dev`, 5 real posters (w342)

- **Method:** one client, sequential, 300 requests round-robin over 5 poster URLs. Paced
  at one request per 200 ms but the Windows loop ran slower: 300 requests in 143 s
  (about 2.1 req/s instead of the planned 5 req/s).
- **Raw numbers:** status 300 × `200`; `Cf-Cache-Status` 300 × `HIT` (100%); latency p50
  63 ms, p95 219 ms, max 339 ms; no 429, no Error 1027.
- **Planned peak for comparison (§7.4.2):** 27,500 requests/day on a peak day, about
  0.32 req/s on average; the probe ran at about 6.5 times that rate.
- **Dashboard (U-CF6: do HITs count as Worker requests? U-CF4: R2 Class B in the
  window):** _pending owner reading of the Cloudflare dashboard._
- **Verdict so far:** no throttling, hit ratio 100% (target 95%).

## 5. Lighthouse LCP and JS size (P3-13)

_Target: LCP under 2.5 s (mobile, simulated 4G); landing JS under 200 KB gzipped._

No measurements yet.

## 6. Load test p95 hit/miss (P4-03)

_Target: as §3.2; quota projection inside Hobby and Workers Free limits._

No measurements yet.
