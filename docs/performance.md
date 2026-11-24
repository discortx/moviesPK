# Performance evidence

The single place for performance measurements (plan §3.2 targets). One section per
measurement. Each entry records: **date**, **environment** (dev / preview / prod),
**method or command**, **raw numbers**, **target** and **verdict** (Pass / Fail / Risk).

## 1. API cold start (P1-14)

_Target: cache-miss p95 under 1,500 ms including a cold function start._

No measurements yet.

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
