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

No measurements yet.

## 3. Worker cache and header test (P1-21)

_Target: `Cf-Cache-Status` MISS then HIT; immutable `Cache-Control`; 404/405 behaviour._

No measurements yet.

## 4. Worker load probe (P1-22)

_Target: per §11.3.2 / §7.4.2 forecast; no Error 1027._

No measurements yet.

## 5. Lighthouse LCP and JS size (P3-13)

_Target: LCP under 2.5 s (mobile, simulated 4G); landing JS under 200 KB gzipped._

No measurements yet.

## 6. Load test p95 hit/miss (P4-03)

_Target: as §3.2; quota projection inside Hobby and Workers Free limits._

No measurements yet.
