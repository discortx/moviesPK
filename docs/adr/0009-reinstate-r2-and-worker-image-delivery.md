# ADR-0009: Reinstate Cloudflare R2 and serve posters from a Worker on `workers.dev` with Workers Caching

- **Status:** **Accepted** by owner decisions **OD9** and **OD10**, 2026-11-23 (`plan.md` §3.3). Confirmed by **OD11** (owner clarification, 2026-11-23): the owner approves proceeding with this design, subject to the remaining verification items, and accepts the free allowances and the residual spend risk.
- **Date:** 2026-11-23
- **Supersedes:**
  - OD6 ("Drop Cloudflare R2"; plan v2.0);
  - the plan v2.0 §7.2 row "Cloudflare Workers / `r2.dev` … Rejected", which rested on R2 billing;
  - every statement in plan v2.0 or architecture v1.1 that Workers are not used;
  - the R2 parts of architecture ADR-13 (recorded there as ADR-18).
- **Does not supersede:** ADR-0001 (robots.txt respected). ADR-0007 stays **Superseded**: this ADR adopts the substance of its option (a), but uses **Workers Caching** instead of the Cache API, and makes no change to API delivery.
- **Numbering note:** this is the repository ADR series (`docs/adr/NNNN-*`). Architecture ADR-18 records the same decision in the `architecture.md` log. ADR-0008 (`docs/adr/0008-zero-cost-architecture.md`) is planned under P0-10 and has not been written yet.
- **Evidence:** `docs/free-tier-verification.md` (checked 2026-11-23). Row IDs such as R2-8 refer to that file.
- **This is not legal advice and is not a legal clearance.**

## Context

Plan v2.0 dropped R2 because R2 needs a payment method (R2-7) and bills usage above its free allowance with no hard cap (R2-8). That broke the absolute $0 rule. Posters were hotlinked from TMDB's image CDN instead. Hotlinking `image.tmdb.org` is not specifically addressed in TMDB's terms (architecture §10.7). It also left the project statement's "Cloudflare R2 stores image assets" unmet.

On 2026-11-23 the owner decided:
- **OD9:** a payment method may be added to the Cloudflare account, for **R2 only**. No other paid service, plan or product. The project stays personal and non-commercial (OD5). No custom domain (OD2).
- **OD10:** posters are served by a small Cloudflare Worker on its free `*.workers.dev` URL. The Worker reads a private bucket through an R2 binding and is fronted by Workers Caching. There is no zone and no public bucket. The Worker stays on Workers Free.

## Decision

1. **Storage.** One private bucket per environment: `moviespk-prod` and `moviespk-dev`. Neither has public access of any kind (no `r2.dev`, no custom domain). Objects are `movies/{movieId}/poster-{hash8}-w{185|342|780}.webp`. `hash8` is the first 8 hex characters of the SHA-256 of the processed w780 WebP bytes, shared by the three variants. Names are immutable. Cinema-supplied images are not copied (open decision; default no). Backups are not stored in R2; they stay a GitHub Actions artifact (`plan.md` §19).
2. **Delivery.** The Worker `moviespk-img` (folder `images-worker/`) has **one** R2 binding, `IMAGES`, to the images bucket of its environment. It never binds any other bucket. It:
   - accepts only GET and HEAD, and returns 405 for anything else;
   - accepts only paths matching `^/img/movies/[a-f0-9]{24}/poster-[a-f0-9]{8}-w(185|342|780)\.webp$`;
   - returns 404 **without touching R2** for any other path, or for any request with a query string;
   - returns `Content-Type: image/webp`, `Cache-Control: public, max-age=31536000, immutable` and the R2 ETag;
   - returns 404 with `Cache-Control: public, max-age=60` when the object is missing;
   - holds no secrets and handles no user data.
3. **Caching.** Workers Caching is turned on in the Wrangler configuration with `cache.enabled = true` and `cross_version_cache = true` (Wrangler ≥ 4.107.0; C-3, C-4). Cache hits are the normal path and do not run the Worker (C-11). R2 is read only on a miss. The old Cache API is not used (CA-2).
4. **Database and site.** The database stores keys only: `poster {key, width, height}`, where `key` is the stem `movies/{movieId}/poster-{hash8}`. The site builds `NEXT_PUBLIC_IMAGE_BASE + "/" + key + "-w{size}.webp"`. `NEXT_PUBLIC_IMAGE_BASE` is the only place that holds the host. `NEXT_PUBLIC_IMAGES_ENABLED=false` is the kill switch.
5. **Source.** TMDB posters only. The scraper downloads, resizes, converts and uploads them. TMDB's 6-month cache limit is enforced with a refresh every 7 days while a movie is showing, and a purge N = 90 days after its last showtime (`plan.md` §11.3.5).
6. **Plans.** Cloudflare R2 (payment method, R2 only) plus **Workers Free**. Every other Cloudflare product is Forbidden: Workers Paid, Images, Stream, zone plans, paid WAF, Argo, Cache Reserve, and anything else.

## Alternatives considered

| Option | Why not chosen |
|---|---|
| **(1) Public `r2.dev` URL on the bucket** | Cloudflare says `r2.dev` is "rate-limited and should only be used for development purposes", with no cache (R2-16). It needs a public bucket. It is kept only as escape hatch (b), on a dedicated images-only bucket. |
| **(2) Vercel rewrite to a public bucket** | It still needs a public bucket (`r2.dev`) with the same development-only status. It also moves every image byte into Vercel Hobby's Fast Data Transfer and CDN-request quotas, where a quota pause takes down the **whole site** (R7). A Vercel rewrite **to the Worker** is kept as escape hatch (a). |
| **(3) Custom domain (`cdn.<domain>` on a Cloudflare zone)** | Forbidden by OD2: no domain, no zone, no DNS, CDN, WAF or cache rules. |
| **(4) No R2 (plan v2.0: TMDB hotlinking)** | It relies on an unaddressed TMDB stance on hotlinking. It sends every user's browser to a third party with no kill switch except placeholders. It does not meet the statement's R2 requirement. The owner chose OD9 instead. |
| **Chosen: private bucket + Worker on `workers.dev` + Workers Caching** | The bucket stays private. Cache headers are under our control. Hits do not run the Worker or touch R2. There is no domain. Moving to another delivery path later needs no data migration (keys only). Because the Worker Free plan fails at its limit rather than billing (W-1–W-3), the Worker also **caps R2 reads**: at most 100,000 requests/day × 31 days = 3.1 M Class B per month, which is below the 10 M free allowance. |

## Consequences

**Billing exposure and controls.**
- R2 has **no hard spend cap** (R2-8). A cost above $0 is possible, but it is not expected.
- Exposure from the Worker is bounded by Workers Free (see above). The remaining exposure is **writes and storage**, which only the scraper's R2 token can create.
- Controls (`plan.md` §7.4):
  - the token is scoped to one bucket;
  - an upload size cap of 1 MB per object, and at most 200 uploads per run;
  - a usage record: uploads per run, bucket size daily (one alert above 1 GB, with no automatic stop), and storage, Class A and Class B monthly from the dashboard;
  - a budget alert at $1 if the account offers one that includes R2 [U-CF3];
  - a monthly manual usage check;
  - a kill procedure.
- If a payment fails, buckets become inaccessible (R2-11). The site then shows placeholders.

**Worker Free daily limit.**
- At 100,000 requests/day the Worker returns Error 1027 until 00:00 UTC (W-1, W-2). Every image request is assumed to count, including cache hits (C-12, C-13).
- When that happens, images fail, `onError` shows the local placeholder, the site keeps working and **nothing is billed**.
- The forecast (planning estimate) is 9.2% of the limit on an average day and 27.5% on a 3× peak day (`plan.md` §7.4).

**Extra component to maintain.**
- One small TypeScript Worker with its own CI (`ci-images-worker.yml`) and deploy workflow (`deploy-images-worker.yml`).
- A Cloudflare deploy token and an R2 token. Both are stored only in GitHub environments, and the Vercel projects receive no Cloudflare credentials.
- A Cloudflare account that must be audited monthly: only R2 subscribed, Workers on Free.
- Workers Caching has no published GA label (C-2), and Cloudflare recommends a route or custom domain for production Workers (D-4). Both are accepted as risks R22 and R23, with the kill switch and two escape hatches.

**Owner clarification (OD11, 2026-11-23).**

Three things are kept apart:

| Category | Content |
|---|---|
| Technical platform limits [V] | R2 free allowances and prices; no hard spend cap; Workers Free 100,000 requests/day, which fails with Error 1027 rather than billing |
| Expected MoviesPK usage (planning estimate) | About 1% of the R2 allowances; 9.2% of the Worker daily limit on an average day (`plan.md` §7.4.2); replaced by measured values in the monthly usage log |
| Owner-accepted residual risk | Usage above the R2 allowance would be billed. The owner accepts this for a personal project. **$0 is expected, not guaranteed.** |

Consequences of OD11:
- Controls stay basic: scoped tokens, no credentials in frontend code, upload caps (1 MB per object, 200 per run), the usage record and the kill procedure. The automatic 2 GB upload stop proposed earlier is dropped.
- **No Referer-based hotlink protection.**
- No additional provider, database, storage tier or paid service to avoid a limit that is not expected to be reached.
- A paid plan or another provider is considered only if measured usage or a concrete technical requirement justifies it, through a new owner decision.
- The image base URL (one variable), the Worker bucket binding and the scraper's S3-compatible storage module stay configurable, so delivery or storage can change without a data migration.

**What is explicitly NOT changed.**
- Vercel stays on Hobby, Atlas on Free, GitHub on a public repo, and TMDB on the free non-commercial API.
- No monetization (OD5). robots.txt is respected (OD3, ADR-0001). No legal steps are added (OD8), and no legal clearance is claimed.
- No custom domain and no subdomain of a domain the owner owns (OD2).
- No Cloudflare DNS, CDN, WAF or cache rules for any zone.
- No Vercel rewrite or function for images in v1. No public bucket. No Cache API. No Workers Paid.
- The API, its caching through the cross-project rewrite, the cinema list and the scraping etiquette are unchanged.

## Verified facts relied on (2026-11-23; details and quotes in `docs/free-tier-verification.md`)

| Fact | Row | Tag |
|---|---|---|
| R2 free each month: 10 GB-month, 1 M Class A, 10 M Class B; Standard only; egress free; usage rounded up | R2-1, R2-3–R2-5 | [V] |
| R2 needs a subscription and a primary payment method | R2-7 | [V] |
| No hard spend cap for R2; spending limits exclude R2 | R2-8 | [V] |
| Budget alerts: email only, account-wide, informational; R2 coverage unclear | R2-9 | [V] / [U] |
| Tokens can be scoped to Object Read & Write on chosen buckets | R2-13 | [V] |
| Binding `get()` returns null for a missing key; body is a ReadableStream; `writeHttpMetadata`, `httpEtag` | B-2–B-4 | [V] |
| Workers Caching: `cache.enabled` (Wrangler ≥ 4.69.0); `cross_version_cache` (≥ 4.107.0); version in the key by default; works on `workers.dev`; key excludes the host and includes the query | C-3–C-7 | [V] |
| Hits do not run the Worker and use no CPU, but count as requests | C-11, C-12 | [V] |
| Hits count toward the Free 100,000/day limit | C-13 | [I] / [U] |
| GA or beta label | C-2 | [U] |
| Workers Free: 100,000 requests/day, reset 00:00 UTC; Error 1027; 10 ms CPU | W-1, W-2, W-4 | [V] |
| A payment method does not move the account to Workers Paid | W-7 | [U] |
| `workers.dev` URL format; `workers_dev = false` disables the route; production on a route or custom domain recommended | D-2–D-4 | [V] |
