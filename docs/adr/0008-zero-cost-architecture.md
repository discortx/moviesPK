# ADR-0008: Zero-cost architecture and gate G0

- **Status:** **Accepted** (G0 passed 2026-11-25; the owner records it by merging this ADR).
- **Date:** 2026-11-25
- **Decided by:** the owner (`plan.md` §3.3, decisions OD4–OD11).
- **Related:**
  - ADR-0001 (robots.txt respected) stays in force.
  - ADR-0007 (no custom domain; image-delivery options) is **Superseded** by ADR-0009 and this ADR (owner approval 2026-11-25, Q7).
  - ADR-0009 covers image storage and delivery (R2 + Worker + Workers Caching); this ADR does not repeat it.
- **Numbering note:** repository ADR series (`docs/adr/NNNN-*`), separate from the `architecture.md` ADR-NN log.
- **This is not legal advice and is not a legal clearance** (OD8).

## Context

`project_statement.md` and `architecture.md` v1.0 assumed a small monthly budget ($0–10), a custom domain behind Cloudflare, a separately hosted API, Nominatim geocoding, a map, chat-webhook alerting and R2 backups. The owner set a **$0 budget for everything except Cloudflare R2** and confirmed the project is **personal and non-commercial**. Every component therefore has to fit a free plan that needs no payment method, with R2 as the single, owner-approved exception.

## Decision

| ID | Decision |
|---|---|
| OD4 | **$0 budget for everything except Cloudflare R2.** R2 is expected to stay inside its free allowance but has no hard spend cap (evidence R2-8). No paid fallback for any other service. |
| OD5 | **Personal, non-commercial project:** no ads, affiliate fees, paid features or revenue. Vercel Hobby and the free non-commercial TMDB API (with attribution). A change of purpose is a re-plan gate (R14). |
| OD6 | *(Dropping R2; superseded by OD9/OD10.)* |
| OD7 | **Express API on Vercel Hobby** as its own project (zero-config Express), separate from the Next.js web project. |
| OD8 | **No formal legal assessment** for implementation or launch. Operational safeguards stay mandatory: robots.txt compliance (OD3), per-cinema kill switch, contact and removal process on `/about`. |
| OD9 | **R2 reinstated for images**; the Cloudflare account carries a payment method for **R2 only**. Vercel stays Hobby, Atlas Free, GitHub a public repo, TMDB the free API. |
| OD10 | **Posters served by a Worker on `*.workers.dev`** with Workers Caching, reading a private bucket through an R2 binding. Workers stays on Free. No zone, no custom domain, no `r2.dev`. Details in ADR-0009. |
| OD11 | **R2 free allowances accepted; keep it simple.** Basic monitoring and write protection; no extra providers to avoid limits not expected to be reached; no claim of guaranteed $0. |

### Platforms

| Concern | Platform | Plan | Payment method |
|---|---|---|---|
| Web (Next.js) | Vercel project `moviespk-web` | Hobby | none |
| API (Express) | Vercel project `moviespk-api` | Hobby | none |
| Database | MongoDB Atlas | Free (M0) | none |
| Scraper, schedules, alerts, backups | GitHub Actions + Issues + artifacts (public repo) | Free | none |
| Movie metadata | TMDB API | Free, non-commercial | none |
| Images | Cloudflare R2 + Worker (`workers.dev`) | R2 pay-as-you-go (free allowance) + Workers Free | **yes, R2 only** |

### Deviations from the source documents

The full table with reasons is `plan.md` §4.2 (D1–D18). In short:

| # | Change |
|---|---|
| D1, D4, D15 | R2 private bucket + Worker on `workers.dev` instead of R2 on a custom domain behind the Cloudflare CDN |
| D2, D3 | API on Vercel Hobby with the Vercel edge cache and one Firewall rate-limit rule, instead of Render/Railway/Fly behind Cloudflare |
| D5 | Hand-entered, map-checked coordinates instead of Nominatim |
| D6 | No map in v1; external "Directions" link |
| D7 | GitHub Issues alerts, Actions health check and `/status` instead of chat webhooks, Sentry and UptimeRobot |
| D8 | YAML source of truth + weekly `mongoexport` artifact instead of `mongodump` to R2 |
| D9 | Distance computed client-side; `/cinemas/nearby` kept with snapped input |
| D10 | $0 expected and targeted; no domain |
| D11 | robots.txt respected (ADR-0001) |
| D12 | No legal steps; contact and removal on `/about` |
| D13, D18 | Seat status optional per cinema; four values (`available`, `filling`, `sold_out`, `unknown`) |
| D14 | Name MoviesPK |
| D16 | API p95 on a cache miss under 1,500 ms including a cold start |
| D17 | A blocked cinema is dropped, never routed through a proxy or VPS |

## Consequences

- No monthly bill is expected, but **$0 is not guaranteed**: R2 usage above the free allowance would be billed (R20). Controls: scoped tokens, upload caps, monthly usage check in `docs/capacity.md`.
- Free-plan limits are hard limits. Exceeding the Workers Free daily limit shows placeholder posters for the rest of the UTC day; nothing is billed (R21).
- Coverage depends on cinemas that publish showtimes without login and allow access in robots.txt. A cinema that blocks runners or changes its robots.txt is dropped.
- Scaling past these limits requires a new ADR; there is no pre-approved paid option.

## Gate G0 (plan §14)

Evidence date: 2026-11-25 unless stated.

| Criterion | Status | Evidence |
|---|---|---|
| ≥ 5 viable cinemas (Allowed, Go, coordinates) | **Met: 5** (target 10+) | `docs/cinema-investigation/` |
| ≥ 5 reachable from a GitHub Actions runner (P0-09) | **Met: 5 of 5** | `docs/cinema-investigation/README.md` |
| P0-05 finished, no blocker: rewrite caching `x-vercel-cache: HIT`; Atlas sign-up with no card | **Rewrite caching met** (HIT through `moviespk-web` → `moviespk-api`, 2026-11-25); Atlas no-card: **met**; items 2–7: **no blocker** (2 and 5 are accepted Risks) | `docs/free-tier-verification.md` §8 |
| Cloudflare: account, R2 only, Workers Free, `workers.dev` subdomain, private buckets, scoped tokens, budget alert (or monthly check) | **Met** (owner-checked 2026-11-25: `moviespk.workers.dev`; alert includes R2; dev token denied on prod; P0-11 quotes re-verified) | `docs/infrastructure.md` |
| Usage forecast under 25% of free allowances | **Met (forecast)**: Worker 9.2% of daily limit; R2 storage 1.0%, Class A 0.1%, Class B 0.7% | `plan.md` §7.4.2; `docs/capacity.md` |
| Payment method only on Cloudflare (R2 only); none on GitHub, Atlas, Vercel, TMDB | **Met** (owner-checked 2026-11-25) | `docs/infrastructure.md` |
| Non-commercial status confirmed (OD5) | **Met** 2026-11-23 | `plan.md` §3.3 |
| CI green on the skeleton | **Met** | required checks on `main` |
| Push protection blocks a fake secret | **Met** (owner test, 2026-11-25) | `docs/infrastructure.md` |

### Phase 0 notes

- **P0-01:** `pre-commit` is not installed on the owner's Windows machine, so `pre-commit run --all-files` was not run locally. The same checks (gitleaks, ruff, eslint, prettier) run in CI on every PR and are required checks on `main`.
- **P0-02:** Docker is not installed on the owner's machine, so `docker compose up mongo` was not demonstrated locally. MongoDB 7 is exercised by the `mongo:7` service container in `ci-scraper` and locally by `mongodb-memory-server` (`docs/dev-setup.md`).
- **P0-05 item 1** was run on the real `moviespk-web` → `moviespk-api` pair instead of two throwaway projects; same topology (see `docs/free-tier-verification.md` §8).
- **API region:** the API functions run in `bom1` (Mumbai), the Atlas region.

### Owner decisions recorded here

- **Q1, launch scope:** **minimum launch (≥ 5 cinemas)**, owner decision 2026-11-25. More cinemas are added as P2-01 rows (target 10+).
- **Q7, ADR-0007 status:** **Superseded**, approved by the owner 2026-11-25.

### G0 decision

**GO**, 2026-11-25. Scope: **minimum launch (≥ 5 cinemas)**; target 10+ through P2-01 rows.

Every G0 criterion in the table above is met. Accepted risks carried into Phase 1:
- R2 has no hard spend cap (R20); monthly check in `docs/capacity.md`.
- Workers Caching has no GA/beta label (U-CF1, R22); behaviour tested in P1-21.
- Vercel runtime logs keep query strings for 1 h on Hobby (P5-2).
- GitHub's "repository activity" for the 60-day schedule rule is undefined (P5-5); keepalive in P2-06.

Next: Phase 1, starting with P1-01 (HTTP client).
