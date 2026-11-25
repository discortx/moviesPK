# ADR-0007: Run v1 without a custom domain (API edge cache and image delivery)

- **Status:** **Superseded** by ADR-0009 (images: private R2 + Worker with Workers Caching) and ADR-0008 (API on Vercel; G0), owner approval 2026-11-25. Part A (no custom domain) lives on as OD2.
- **Date:** 2026-11-22
- **Would supersede (in part):** architecture ADR-09 (Cloudflare in front of the API), ADR-12 (Cloudflare CDN short TTLs), ADR-13 (R2 on a custom domain behind Cloudflare CDN). `architecture.md` is not edited; see `plan.md` section 15.
- **Numbering note:** repo ADR series (`docs/adr/NNNN-*`), separate from the architecture's ADR-NN.

## Context

**Part A: owner decision (final, 2026-11-22).** The product name is **MoviesPK** ("CineNear" is dropped). The owner has **no custom domain and does not plan to buy one for now**. v1 must not assume a domain anywhere.

The architecture used a domain for three things: `cdn.<domain>` for R2 images, `api.<domain>` proxied by Cloudflare (cache rules, rate limit, purge), and the production web address. Cloudflare cache rules, rate limiting and purge need a Cloudflare zone, which needs a domain. The database stores image **keys only** (architecture §6.4), so adding a domain later is a configuration change.

**Findings from a documentation search on 2026-11-22 (summary only; must be re-verified in P0-09/P0-18 and recorded in `docs/free-tier-verification.md`; not assumed from memory):**

| Topic | Finding | Source |
|---|---|---|
| Cloudflare Workers Free | 100,000 requests/day, resets 00:00 UTC; over the limit returns error 1027; 10 ms CPU per request; R2 calls via a binding count as subrequests. Not found: how `workers.dev` addresses are treated, and R2 free-tier quotas. | developers.cloudflare.com/workers/platform/limits/ |
| R2 `r2.dev` URL | For development only; variable rate limit with 429 and possible bandwidth throttling; **no caching, WAF or bot management**; caching needs a custom domain. A bucket stays public on `r2.dev` unless that access is disabled. | developers.cloudflare.com/r2/buckets/public-buckets/ |
| Vercel external rewrites | Rewrites to an external origin **honor upstream `Cache-Control`, `CDN-Cache-Control` and `Vercel-CDN-Cache-Control`**, on by default for projects created on or after 2026-04-06 (older projects: a setting or the `x-vercel-enable-rewrite-caching` header). With `Cache-Control` alone Vercel consumes `s-maxage` (it is not sent to the browser); `CDN-Cache-Control` is the recommended way to control CDN caching. Not found: Hobby bandwidth/transfer limits, log retention of query strings, client-IP header behavior. | vercel.com/docs/routing/rewrites |
| Render free web service | Spins down after 15 min without traffic; restart takes about 1 min; 750 free instance hours per month; a paid instance removes both. Other hosts (Fly, Railway) not yet checked. | render.com/docs |
| TMDB images | API free for non-commercial use with attribution; commercial use needs a separate license; **no statement found about hotlinking `image.tmdb.org`**; caching rules unclear. | developer.themoviedb.org FAQ, API Terms |

## Part B: API edge caching and CORS without Cloudflare (proposed)

**Proposal: proxy the API through the Next.js site.** In `web/next.config.js` add a rewrite `/api/:path*` → `API_ORIGIN/api/:path*` (new server-side env var, the API host URL). Browsers call the same origin (`/api/v1/...` on the `*.vercel.app` site), so **CORS is not needed for browser calls**; Vercel's CDN can cache responses using the API's cache headers (use `CDN-Cache-Control` or `Vercel-CDN-Cache-Control` for the edge TTL so the `s-maxage` behavior above does not surprise us). `express-rate-limit` is the only rate limiter. The CORS allow-list stays for direct calls to the API host (and preview origins). A purge is replaced by short TTLs (`s-maxage` 120 s plus `stale-while-revalidate` 600 s) and, if verified in P0-18, Vercel's cache purge by tag.

| | Pros | Cons / risks |
|---|---|---|
| Rewrite proxy through Next.js | No domain, no new tech; same-origin removes CORS for the browser; edge cache on Vercel; hides cold starts like Cloudflare did | The API host sees **Vercel's IPs**, so `express-rate-limit` must key on the forwarded client IP (trust-proxy setup, to verify); the public API host URL can still be called directly; **query strings (rounded coordinates) pass through Vercel and may appear in Vercel logs** (privacy rule, risk N12); proxied traffic counts against Vercel Hobby limits (to verify); Hobby non-commercial terms still apply (N9); older Vercel projects need the rewrite-caching setting |
| Alternative: browser calls the API host directly with CORS, no edge cache | Simplest; no Vercel in the data path | No shared cache, so every cold start and miss hits the free API host (Render free spin-down is about 1 min); the architecture's performance targets are at risk |

**Recommendation:** the rewrite proxy, with the direct-call alternative as fallback. Measure in P1-23 (cache HIT, rate-limit IP attribution, log content) before relying on it.

## Part C: image delivery without `cdn.<domain>` (options for approval)

| Option | Description | Pros | Cons / risks |
|---|---|---|---|
| **(a) Cloudflare Worker on a free `workers.dev` address serving from R2** | Worker with an R2 binding serves `GET /<key>` with `Cache-Control: public, max-age=31536000, immutable`; bucket can stay **private** (binding only) | Keeps the architecture (R2 holds images, DB holds keys, URL = base + key); immutable hashed keys cache in browsers; changing to a domain later is `CDN_BASE_URL` only; no public bucket | **New technology (Workers, Wrangler) → section 14.2**; free plan cap 100,000 requests/day (error 1027 beyond it) — each image fetch is a Worker request, so a traffic spike could break images; no CDN cache in front without a zone (the Worker can use the Cache API; effect to verify); deploy token needed in CI |
| (b) TMDB's image servers directly for TMDB posters; R2 only for fallback images | Store the TMDB image path for matched movies; build URLs to `image.tmdb.org` | No Worker, no R2 traffic for most posters, TMDB's CDN | **Breaks "keys only, one image base URL"** and pipeline step 7 for TMDB art; TMDB terms are non-commercial unless licensed (and the project's commercial status is open, see N9); hotlinking policy not found; images can change or disappear; the project statement says R2 stores images |
| (c) `r2.dev` URL on `moviespk-prod`, documented risk | Enable public access on the bucket's `r2.dev` address | Zero new technology; one switch | Cloudflare says dev only, **rate-limited (429), no caching**, can be throttled; bucket is public; contradicts architecture ADR-13 (accepted as a documented risk) |

**Recommendation:** **(a)**, because it preserves the architecture and the "config-only domain change later", keeps the bucket private, and is the only option with immutable caching headers under our control. Treat the 100,000/day Worker limit as the key risk: measure real image counts per page in P0-18, keep posters small (w185/w342 variants), and use the upgrade path (Workers paid plan, or a custom domain later). Use (c) only for the dev bucket, and consider (b) as a later optimization, not a v1 dependency. **Open: owner approves (a), (b) or (c); the plan assumes (a) as a working baseline until then.**

## Decision requested

1. Approve Part B (rewrite proxy through Next.js) or choose the direct-call alternative.
2. Approve one of (a), (b), (c) for images.
3. Approve the new technology (Cloudflare Worker + Wrangler) if (a) is chosen (`plan.md` section 14.2).

## Consequences (if approved as recommended)

- No custom domain, DNS zone, cache rules, WAF/rate-limit rule or purge in v1. `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ZONE_ID` are removed from the env list (a Workers deploy token is added only if option (a) is approved).
- Public addresses: the web site on `*.vercel.app`, the API behind `/api` on the same address, images on the approved delivery URL. User-Agent contact: the GitHub repo URL and a project email address. `/takedown`: the same email.
- New env vars: `API_ORIGIN` (server), `NEXT_PUBLIC_SITE_URL` (canonical URLs). `NEXT_PUBLIC_API_BASE_URL` becomes a relative `/api/v1`.
- Adding a domain later is configuration plus a redirect step (`plan.md` section 9.1).
- Performance targets (architecture §2.2) were based on Cloudflare cache hits; they are re-baselined in P1-23 and P4-07.
- This is not legal advice and not a substitute for the verification tasks.
