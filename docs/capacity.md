# Capacity and usage log

The usage log for plan §7.4.3 item 6, §18.2 (monthly check) and P4-03. One row per observation. The forecast column comes from plan §7.3 and §7.4.2 (planning estimates at 50,000 page views/month); actual values start in P4-03.

**Rule:** any resource above **50%** of its limit (planning average) triggers the follow-up in plan §7.3 (Vercel) or §7.4.2 (Worker/R2) before launch.

| Date | Period | Resource | Limit | Forecast | Actual | % of limit | Source | Observations | Follow-up (owner) |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-25 | month | R2 storage | 10 GB-month | ≈ 0.1 GB | | 1.0% (forecast) | plan §7.4.2 | 300 movies × 200 KB + 50% orphans + dev | |
| 2026-11-25 | month | R2 Class A (writes) | 1,000,000 | ≤ 1,000 | | 0.1% (forecast) | plan §7.4.2 | Only the scraper token can write | |
| 2026-11-25 | month | R2 Class B (reads) | 10,000,000 | ≈ 70,000 (worst 901,000; hard bound 3.1M) | | 0.7% (forecast) | plan §7.4.2 | Bounded by the Workers Free daily limit | |
| 2026-11-25 | peak day | Worker requests | 100,000/day | 9,167 average; 27,500 peak | | 9.2% avg / 27.5% peak (forecast) | plan §7.4.2 | Over the limit → placeholders, no bill | |
| 2026-11-25 | month | Vercel function invocations | 1,000,000 | ≥ 75,000 | | 7.5% (forecast) | plan §7.3 | Rises with edge-cache misses; measure in P4-03 | |
| 2026-11-25 | month | Vercel other Hobby quotas (Active CPU, Fast Data Transfer, CDN requests, ISR) | per Hobby plan | not forecast | | | plan §7.3 | Record from the Usage page in P4-03 | |
| 2026-11-25 | peak | Atlas operations | 100 ops/s | < 20 ops/s during `full` | | < 20% (forecast) | plan §7.3 | Bulk writes | |
| 2026-11-25 | total | Atlas storage | 512 MB | < 30 MB | | < 6% (forecast) | plan §7.3 | `scrape_runs` 30-day TTL | |
| 2026-11-25 | month | Actions minutes | free for public repos | 1,500–3,000 min | | n/a | plan §7.3 | | |
