# MoviesPK — Free-tier and platform verification

- **Purpose:** the evidence file named in `plan.md` P0-05 and P0-11. This first version records the **Cloudflare** facts behind owner decisions OD9 and OD10 (R2 reinstated; images served by a Worker on `*.workers.dev` with Workers Caching). The Vercel, Atlas, GitHub and TMDB facts verified on 2026-11-23 are in `architecture.md` §10.7 and `docs/infrastructure-and-legal-audit.md`. They are not repeated here. P0-05 adds its remaining items to this file.
- **Date checked:** 2026-11-23 for every row unless stated otherwise.
- **Sources:** official Cloudflare documentation (`developers.cloudflare.com`) and the official Cloudflare blog (marked BLOG). Community threads are never used as evidence for a [V] row.
- **Evidence key** (same as `plan.md` §4.1):
  - **[V]:** verified against the provider's official documentation on the date checked.
  - **[I]:** our technical inference from verified facts.
  - **[U]:** unverified. Every [U] row names the task that resolves it.
- **Quotation note:** the quotes were collected with an automated fetch tool. Quotes once marked "~" were re-copied word for word in P0-11 on 2026-11-25 (§9); no "~" quotes remain.
- **This file is not legal advice and makes no billing guarantee.** Free tiers change. Re-verify every quarter (`plan.md` Z5).

---

## 0. How to read this file: limits vs expected usage vs accepted risk

Owner clarification **OD11** (2026-11-23, `plan.md` §3.3) asks that three categories stay separate:

| Category | What it is | Where it is recorded | Status |
|---|---|---|---|
| **1. Technical platform limits** | What Cloudflare documents | §1–§6 of this file ([V]/[I]/[U] rows) | Provider facts. They do not change because of any owner decision. |
| **2. Expected MoviesPK usage** | Planning estimates with arithmetic, later replaced by measured values | `plan.md` §7.4.2 (forecast); the monthly usage log in `docs/capacity.md` (actuals) | **Not** verified facts. They are assumptions accepted by the owner. |
| **3. Owner-accepted residual financial risk** | R2 has no hard spend cap (R2-8), so usage above the free allowance (R2-1) would be billed at the prices in R2-3, rounded up (R2-4) | OD11; `plan.md` §7.4 and R20; ADR-0009 | Accepted by the owner for a personal, non-commercial project. **$0 is expected, not guaranteed.** |

Owner-accepted usage assumptions (category 2, OD11), shown against the verified limits:

| Resource | Verified limit (category 1) | Expected usage (category 2, planning estimate) | Share |
|---|---|---|---|
| R2 storage | 10 GB-month free (R2-1) | ≈ 0.1 GB | ≈ 1.0% |
| R2 Class A (writes) | 1,000,000/month free (R2-1) | ≤ 1,000/month | ≈ 0.1% |
| R2 Class B (reads) | 10,000,000/month free (R2-1) | ≈ 70,000/month; hard bound 3.1M through the Worker limit [I] | ≈ 0.7% (bound 31%) |
| Worker requests | 100,000/day on Free (W-1), Error 1027 beyond (W-2) | ≈ 9,167/day average; ≈ 27,500 on a 3× peak day | ≈ 9.2% (peak 27.5%) |

The owner judges these allowances sufficient (OD11). The warnings in §1 (no hard cap, rounding up, failed payment makes buckets inaccessible) remain accurate and are deliberately kept.

---

## 1. Cloudflare R2

| # | Item | Finding | Tag | Source (checked 2026-11-23) |
|---|---|---|---|---|
| R2-1 | Free allowance | Each month: **10 GB-month** storage, **1,000,000 Class A** operations and **10,000,000 Class B** operations. "You can use the following amount of storage and operations each month for free." The allowance applies to **Standard storage only**: "The free tier only applies to Standard storage, and does not apply to Infrequent Access storage." | [V] | https://developers.cloudflare.com/r2/pricing/ |
| R2-2 | Permanence of the free allowance | The docs say "each month". No page says "forever", and none sets a time limit. | [U] → Z5 quarterly re-check | same |
| R2-3 | Prices beyond the allowance (Standard) | Storage **$0.015 / GB-month**; Class A **$4.50 / million**; Class B **$0.36 / million**. The first 100,000 buckets are included. | [V] | same |
| R2-4 | Rounding | "Cloudflare rounds up your usage to the next billing unit." For example, 1,000,001 Class A operations are billed as 2 million. | [V] | same |
| R2-5 | Egress | "There are no charges for egress bandwidth for any storage class." This includes egress through the Workers API. | [V] | same |
| R2-6 | Operation classes | **Class A:** ListObjects, PutObject, CopyObject, CreateMultipartUpload, UploadPart, LifecycleStorageTierTransition. **Class B:** GetObject, HeadObject. **Free:** DeleteObject, DeleteBucket, AbortMultipartUpload. | [V] | same |
| R2-7 | Payment method required | Yes. "You need a Cloudflare account with an R2 subscription." / "Complete the checkout flow to add an R2 subscription to your account." / "A primary payment method is required to purchase Cloudflare products and services." | [V] (from both pages together) | https://developers.cloudflare.com/r2/get-started/ ; https://developers.cloudflare.com/billing/get-started/create-billing-profile/ |
| R2-8 | Hard spend cap | **None for R2.** The spend-management (spending limits) feature covers Workers and Durable Objects only: "A Workers limit does not include Durable Objects, Workers AI, Workers KV, R2, or other products used by your application." | [V] | https://developers.cloudflare.com/workers/platform/spend-management/ ; https://developers.cloudflare.com/billing/manage/spend-management/ |
| R2-9 | Budget alerts | Email only. Alerts are based on the **account-wide** cumulative usage-based spend for the billing period, for Pay-as-you-go accounts only. "Budget alerts are informational only. They do not pause or limit usage." The page does not say explicitly that R2 spend is included. | [V] (existence, behaviour) / [U] (R2 included; available on this account) → P0-12 | https://developers.cloudflare.com/billing/manage/budget-alerts/ |
| R2-10 | "Usage Based Billing" notification | Needs a **Professional plan or higher** (a paid zone plan) and a Pay-as-you-go account. R2 is not listed as a supported product. **Not usable:** a Professional plan is Forbidden under Z1. | [V] | https://developers.cloudflare.com/notifications/notification-available/ |
| R2-11 | Failed payment | "If your payment method fails, we may suspend your access to the usage-based billing services for which we conducted the preauthorization. In the case of R2, you will not be able to access your R2 buckets and requests will return errors, but your data will remain secure." (Re-copied 2026-11-25; the page also warns that data may be deleted if the payment method is not updated within 30 days.) | [V] | https://developers.cloudflare.com/billing/understand/billing-policy/ |
| R2-12 | HTTP metadata on upload | The S3-compatible PutObject supports `Content-Type` and `Cache-Control` as system metadata, so boto3 `ContentType=` and `CacheControl=` are stored with the object. | [V] | https://developers.cloudflare.com/r2/api/s3/api/ |
| R2-13 | API token scoping | "If you select the **Object Read and Write** or **Object Read** permissions, you can scope your token to a set of buckets." A set can contain one bucket. | [V] | https://developers.cloudflare.com/r2/api/tokens/ |
| R2-14 | Lifecycle rules | Rules can delete objects by age or on a date, filter by prefix, abort incomplete multipart uploads, and move objects to Infrequent Access. A move to Infrequent Access costs one Class A operation. **MoviesPK does not use lifecycle rules** (deletion is driven by the database; see `plan.md` §11.3.5). | [V] | https://developers.cloudflare.com/r2/buckets/object-lifecycles/ |
| R2-15 | Buckets are private by default | "By default, buckets are never publicly accessible and will always require explicit user permission to enable." | [V] | https://developers.cloudflare.com/r2/buckets/public-buckets/ |
| R2-16 | `r2.dev` | "Public access through `r2.dev` subdomains is rate-limited and should only be used for development purposes." There is no Cloudflare cache on `r2.dev`. **Not used by MoviesPK** (escape hatch only, `plan.md` §11.3.7). | [V] | same |

## 2. R2 binding in a Worker

| # | Item | Finding | Tag | Source |
|---|---|---|---|---|
| B-1 | Private bucket reachable through a binding | A Worker reads a bucket through an `r2_buckets` binding (`env.IMAGES`). No page requires public access for a binding, and buckets are private by default (R2-15). | [V] (binding API) / [I] (no public access needed) | https://developers.cloudflare.com/r2/api/workers/workers-api-reference/ |
| B-2 | Missing key | `get()` returns "null if the key does not exist". | [V] | same |
| B-3 | Streaming the body | `R2ObjectBody.body` is a `ReadableStream` ("The object's value"). It is passed straight to `new Response(object.body, …)` with no buffering. | [V] | same |
| B-4 | Headers from metadata | `writeHttpMetadata(headers)` "Retrieves the `httpMetadata` from the `R2Object` and applies their corresponding HTTP headers to the `Headers` input object." `httpEtag` is "The object's etag, in quotes so as to be returned as a header." | [V] | same |
| B-5 | Billing class of binding reads | The pricing page lists GetObject and HeadObject as Class B, but does not say explicitly that `get()`/`head()` through a binding are Class B. **Plan assumption: they are Class B** (conservative). | [U] → P1-22 (compare R2 metrics with the request count) | https://developers.cloudflare.com/r2/pricing/ |
| B-6 | R2 calls count as subrequests | "A subrequest is any request a Worker makes using the Fetch API or to Cloudflare services like R2, KV, or D1." The Free plan allows 50 subrequests per invocation and 1,000 "Subrequests to internal services". The image Worker makes **at most one** R2 call per request, so both limits are far away. | [V] | https://developers.cloudflare.com/workers/platform/limits/ |

## 3. Workers Caching ("Workers Cache")

| # | Item | Finding | Tag | Source |
|---|---|---|---|---|
| C-1 | Existence and plans | Launched 2026-07-06. "Workers Cache is available today to every Worker on any plan." The docs use both names, "Workers Cache" and "Workers Caching". | [V] | https://blog.cloudflare.com/workers-cache/ (BLOG) ; https://developers.cloudflare.com/workers/cache/ |
| C-2 | GA or beta | **No label** on the overview, configuration, debugging or limitations pages (re-checked 2026-11-25). Nearest wording: "At launch, all Workers Caching responses are subject to the Free plan size limit regardless of your account's plan. This restriction is temporary and will be lifted in a future update…" | [V] no label; risk R22 stays | https://developers.cloudflare.com/workers/cache/ |
| C-3 | How to enable | TOML: a `[cache]` table with `enabled = true`. JSONC: `"cache": { "enabled": true }`. The allowed keys are `enabled` (required) and `cross_version_cache` (optional). **Minimum Wrangler 4.69.0**: "Check that your wrangler version is 4.69.0 or above, and that wrangler.toml or wrangler.jsonc has cache.enabled = true". | [V] | https://developers.cloudflare.com/workers/cache/configuration/ ; https://developers.cloudflare.com/workers/cache/debugging/ |
| C-4 | `cross_version_cache` | `true` removes the Worker version from the cache key, so entries are shared across deployments until they expire or are purged. "The cross_version_cache option requires Wrangler 4.107.0 or above." Per-entrypoint settings (an `exports` map) also need 4.107.0 or above. | [V] | https://developers.cloudflare.com/workers/cache/configuration/ |
| C-5 | Version in the cache key by default | "By default, the **Worker version is part of the cache key**. Each deployed version has its own isolated cache, so a new deployment starts from an empty cache and never serves responses written by a previous version." "The trade-off is that **cache hit rate resets on every deployment**." `cross_version_cache = true` shares entries across versions. | [V] | https://developers.cloudflare.com/workers/cache/configuration/ |
| C-6 | Works on `*.workers.dev` | "The cache works on workers.dev." `workers.dev`, routes and custom domains of the same Worker share one cache. | [V] | https://developers.cloudflare.com/workers/cache/ ; BLOG |
| C-7 | Cache key | Entrypoint + path + **query string** + Worker version (by default) + `ctx.props`, plus a few headers that guard against cache poisoning. "The cache key does not include the host." Method, body, Cookie, User-Agent and Authorization are not part of the key. | [V] | https://developers.cloudflare.com/workers/cache/cache-keys/ |
| C-8 | TTL headers and precedence | `Cloudflare-CDN-Cache-Control` takes precedence over `CDN-Cache-Control`, which takes precedence over `Cache-Control`. `Set-Cookie`, `private` and `no-store` cause a bypass. With no cache headers, heuristic TTLs apply by status code (200 → 2 h, 301 → 20 min, 404 → 3 min): "Omitting `Cache-Control` is not the same as opting out of the cache." | [V] | https://developers.cloudflare.com/workers/cache/configuration/ |
| C-9 | Status header | `Cf-Cache-Status`. The common values are `HIT`, `MISS`, `EXPIRED`, `REVALIDATED`, `UPDATING`, `STALE` and `BYPASS` (plus `DYNAMIC`). | [V] | https://developers.cloudflare.com/workers/cache/ ; …/debugging/ |
| C-10 | Size limit | "At launch, all Workers Caching responses are subject to the Free plan size limit regardless of your account's plan." The blog gives that limit as 512 MB. MoviesPK posters are below 1 MB. | [V] | https://developers.cloudflare.com/workers/cache/limitations/ ; BLOG |
| C-11 | Does a HIT run the Worker? | No. A HIT is served without invoking the Worker and uses no CPU. | [V] | https://developers.cloudflare.com/workers/platform/pricing/ |
| C-12 | Does a HIT count as a request? | Yes: "Cache hits count as requests but do not consume CPU time." | [V] | same |
| C-13 | Do HITs count toward the **Free** 100,000/day limit? | Not stated explicitly. The Free limit is a daily request count, and C-12 says hits are requests. **Plan assumption: every image request counts, HIT or MISS** (conservative). | [I] / [U] → P1-22 (Worker request graph vs probe count) | same ; https://developers.cloudflare.com/workers/platform/limits/ |
| C-14 | Methods and ranges | "Only `GET` and `HEAD` requests are cached. Other methods always invoke your Worker." For a Range request, Cloudflare strips `Range`, caches the full 200 response and serves a 206 slice. | [V] | https://developers.cloudflare.com/workers/cache/ ; …/limitations/ |
| C-15 | Purge | From Worker code only: `ctx.cache.purge()` by tags, path prefixes or everything. Purge rate limits are always the Free-tier limits. Whether purge works on `workers.dev` is not stated. **MoviesPK never purges**: keys are immutable and a changed image gets a new key. | [V] (mechanism) / [U] (workers.dev; not needed) | https://developers.cloudflare.com/workers/cache/purge/ |
| C-16 | Local tests | "Local Vitest tests do not exercise Workers Caching. Test cache behavior on a Preview with its own cache or a deployed test Worker with caching enabled. Check for `Cf-Cache-Status: HIT` using the two-request debugging example." (Moved to the limitations page.) | [V] | https://developers.cloudflare.com/workers/cache/limitations/ |
| C-17 | Turning caching off | "Disabling caching does not purge previously cached responses — it only stops Cloudflare from consulting or populating the cache on subsequent requests. If you re-enable caching later, any entries that are still within their TTL become usable again." | [V] | https://developers.cloudflare.com/workers/cache/configuration/ |

### 3.1 The older Cache API (`caches.default`, `cache.match`, `cache.put`)

| # | Item | Finding | Tag | Source |
|---|---|---|---|---|
| CA-1 | Effect on `workers.dev` | The current page says "Workers deployed to custom domains have access to functional `cache` operations", and that the Cache API and Workers Caching are independent ("The two mechanisms are independent."). **The exact sentence "no effect on `*.workers.dev`" was not found on the current page.** The page implies it, but does not state it. | [V] (custom-domain wording) / [U] (exact workers.dev wording; not needed) | https://developers.cloudflare.com/workers/runtime-apis/cache/ |
| CA-2 | Decision | The Cache API is **not used**. This holds whatever the exact workers.dev wording is, because only Workers Caching is documented to work on `workers.dev` (C-6). | — | OD10 |

## 4. Workers Free plan

| # | Item | Finding | Tag | Source |
|---|---|---|---|---|
| W-1 | Daily requests | "Accounts on the Workers Free plan have a daily request limit of 100,000 requests, resetting at midnight UTC." | [V] | https://developers.cloudflare.com/workers/platform/limits/ |
| W-2 | Over the limit | "When a Worker exceeds this limit, Cloudflare returns Error 1027." Route-level "fail open" and "fail closed" options exist. Fail open "Bypasses the Worker", which only means something when a zone origin sits behind a route. **A `workers.dev`-only Worker has no origin, so the result is the 1027 error** [I]. | [V] / [I] | same |
| W-3 | Billing on Free | "If you exceed any one of these limits, further operations of that type will fail with an error." No overage billing on Free is described. | [V] (fails) / [I] (no charge, implied rather than stated) | https://developers.cloudflare.com/workers/platform/pricing/ |
| W-4 | CPU time | "CPU time per HTTP request: 10 ms" on Free. | [V] | https://developers.cloudflare.com/workers/platform/limits/ |
| W-5 | Memory, size | 128 MB memory per isolate; Worker size 64 MiB uncompressed (Free and Paid). | [V] | same |
| W-6 | Payment method for Workers Free | **Not stated.** Free is the default plan for every account. | [U] → P0-12 (record what the dashboard asks) | https://developers.cloudflare.com/workers/platform/pricing/ |
| W-7 | Does a payment method move the account to Workers Paid? | **No page says it does.** Workers Paid is an explicit purchase on the dashboard's Workers plans page, at a minimum of "$5 USD per month for an account". | [U] (no automatic switch: inferred from the purchase being explicit) → P0-12 (screenshot of the Workers plan after the card is added) | same ; https://developers.cloudflare.com/billing/get-started/update-billing-info/ |
| W-8 | Spending limits | Spending limits (changelog 2026-11-13) cover Workers requests and CPU beyond included usage on **Workers Paid**. They are not an exact cap, and they do not cover R2 (R2-8). Not relevant on Free, which fails at its limit. | [V] | https://developers.cloudflare.com/workers/platform/spend-management/ |
| W-9 | Static assets | "Requests to static assets are free and unlimited." **Not used**: images live in R2, not in Worker static assets (assets are deployed with the code and would put TMDB-derived images in the public repo). | [V] / decision | https://developers.cloudflare.com/workers/platform/pricing/ |

## 5. `workers.dev`

| # | Item | Finding | Tag | Source |
|---|---|---|---|---|
| D-1 | Account subdomain | "Cloudflare Workers accounts come with a `workers.dev` subdomain that is configurable in the Cloudflare dashboard." It can be changed later (Workers & Pages → Your subdomain → Change). **How it is first created is not documented** on this page. | [V] (configurable) / [U] (first creation) → P0-12 | https://developers.cloudflare.com/workers/configuration/routing/workers-dev/ |
| D-2 | URL format | `<YOUR_WORKER_NAME>.<YOUR_SUBDOMAIN>.workers.dev`; the Worker name comes from `name` in the Wrangler configuration (63 characters at most). | [V] | same |
| D-3 | Disable and re-enable | Per Worker, `workers_dev = false` disables the `workers.dev` route on the next deploy, and `true` re-enables it. A dashboard-only change is undone by the next `wrangler deploy`. Disabling it does **not** turn off Preview, Version or Deployment URLs (set `preview_urls = false` separately). | [V] | same |
| D-4 | Production use | "It's recommended to run production Workers on a Workers route or custom domain." This is a recommendation, not a prohibition. MoviesPK accepts it as risk R23 (no domain, OD2). | [V] | same |
| D-5 | Zone features | Browser Integrity Check: "All requests to a `workers.dev` hostname are evaluated by Browser Integrity Check (BIC) on the Cloudflare-managed `workers.dev` zone. This includes Preview URLs and Version URLs." "You cannot turn off this check for a `workers.dev` hostname." **Corrected 2026-11-25:** the page does not say whether the account's own zone rules, WAF or Cache Rules apply to `workers.dev`; that earlier claim is withdrawn. Irrelevant to MoviesPK: there is no zone (OD10). Consequence of BIC: health checks and scripts that fetch posters must send a normal `User-Agent`. | [V] (BIC only) | https://developers.cloudflare.com/workers/configuration/routing/workers-dev/ |

## 6. Deployment from CI

| # | Item | Finding | Tag | Source |
|---|---|---|---|---|
| CI-1 | Deploy token | Use the **"Edit Cloudflare Workers"** token template, then scope it down: "We recommend scoping these down as much as possible". The template grants Workers Scripts Write, KV Storage Write, R2 Storage Write and Tail Read at account level, plus Workers Routes Write at zone level. **MoviesPK's token:** one account, Workers Scripts **Write** only, no zone resources, **no R2 permission** (the Worker reads R2 through its binding, not the token). | [V] (template; scope down) / [U] (that a deploy works without zone or R2 permissions) → P1-20 | https://developers.cloudflare.com/workers/ci-cd/external-cicd/github-actions/ ; https://developers.cloudflare.com/fundamentals/api/reference/template/ |
| CI-2 | Wrangler environments | "a Worker project named `my-worker` with an environment `dev` would deploy as a Worker named `my-worker-dev`." So `moviespk-img` with `--env dev` deploys as `moviespk-img-dev`. | [V] | https://developers.cloudflare.com/workers/wrangler/environments/ |

---

## 7. Open [U] items and the tasks that resolve them

| ID | Item | Resolved by |
|---|---|---|
| U-CF1 | Workers Caching: GA or beta status (C-2). Re-checked 2026-11-25: still no label | P0-11 (re-check); P1-21 (behaviour); risk R22 |
| U-CF2 | ✅ resolved 2026-11-25 (only R2 subscribed, Workers Free) — Workers Free needs no payment method; adding a payment method for R2 does **not** subscribe the account to Workers Paid (W-6, W-7) | P0-12 (screenshots of the billing and Workers plan pages) |
| U-CF3 | ✅ resolved 2026-11-25 (alert set, includes R2) — A budget alert is available on the account and includes R2 spend (R2-9) | P0-12. If it is unavailable or excludes R2, the monthly usage record (`plan.md` §7.4.3 item 6, §18.2) is the only spend signal. This is recorded and accepted by the owner (OD11). |
| U-CF4 | Binding `get()`/`head()` are billed as Class B (B-5) | P1-22 |
| U-CF5 | ✅ resolved 2026-11-25 (subdomain created) — How the account `workers.dev` subdomain is first created (D-1) | P0-12 |
| U-CF6 | Workers Caching HITs count toward the Free 100,000/day limit (C-13) | P1-22 |
| U-CF7 | ✅ resolved 2026-11-28: a repeat request for a missing poster on both deployed Workers returned `CF-Cache-Status: HIT` (`Age: 1`) — A 404 with `Cache-Control: public, max-age=60` is cached by Workers Caching for 60 s | P1-21 |
| U-CF8 | ✅ resolved 2026-11-28: `CF_WORKERS_DEPLOY_TOKEN` (Workers Scripts Write only) deployed `moviespk-img-dev` and `moviespk-img`, each with its R2 binding — A deploy token with Workers Scripts Write only (no zone, no R2) can deploy a `workers.dev` Worker with an R2 binding (CI-1) | P1-20 |
| U-CF9 | R2 free allowance permanence (R2-2) | Z5 quarterly re-check |
| U-CF10 | Exact Cache API wording for `workers.dev` (CA-1) | Not needed: the Cache API is not used |

---

## 8. P0-05: remaining platform items (2026-11-25)

| # | Item | Date | Finding | Verdict | Source |
|---|---|---|---|---|---|
| P5-1 | Edge caching of `Vercel-CDN-Cache-Control` from an Express function, through a rewrite from another Vercel project to its production domain | 2026-11-25 | Tested on the real projects instead of a throwaway pair (same topology): `moviespk-web` rewrites `/api/:path*` to `https://moviespk-api.vercel.app`. `GET https://moviespk-web.vercel.app/api/v1/cities` (API sends `Vercel-CDN-Cache-Control: max-age=3600, stale-while-revalidate=86400`, `Cache-Control: public, max-age=60`, `x-vercel-enable-rewrite-caching: 1`) returned `X-Vercel-Cache: HIT` on three consecutive requests with `Age` 8 → 10 → 11; the browser sees `Cache-Control: public, max-age=60`. `/api/v1/health` (`no-store`) through the same rewrite: `MISS`, as required. Edge `bom1`, function `iad1`. **Not isolated:** whether Vercel reads `x-vercel-enable-rewrite-caching` from the upstream response, because both projects were created after 2026-04-06, when rewrite caching is on by default; the header stays as a safeguard (§9.2). | **OK** | `curl -D -` from the developer machine, 2026-11-25 |
| P5-2 | Vercel request logs: query strings and retention | 2026-11-25 | Runtime logs **do** record the query string ("Search Params" field next to Request Path). Hobby keeps runtime logs for **1 hour** (Pro: 1 day). Quote: "Search Params \| Search parameters of the request path"; "Hobby \| 1 hour of logs". Consequence: `lat`/`lng` sent to `/cinemas/nearby` would be visible in Vercel's own logs for up to 1 h, outside the app's pino rule (§9.2). The website computes distance client-side (D9), so only direct API consumers send coordinates, already snapped to 0.05°. No secrets ever go in URLs. | **Risk (accepted):** 1 h retention, snapped coordinates only | https://vercel.com/docs/logs/runtime (updated 2026-08-28) |
| P5-3 | Atlas asks for a card at registration | 2026-11-25 | No card was asked for; the free cluster runs in Mumbai. | **OK** | owner sign-up |
| P5-4a | Required reviewers on environments in a public repository | 2026-11-25 | Throwaway run `probe-g0` (branch `probe/g0-checks`): the `approval` job in environment `images-approval` succeeded. The job paused until the owner approved it: required reviewers work on this public repository. | **OK** | GitHub Actions run, 2026-11-25 |
| P5-4b | Pending-run replacement in a concurrency group | 2026-11-25 | Confirmed: "any existing `pending` job or workflow run in the same group is canceled and replaced." `cancel-in-progress: false` protects only the running job, so a group holds at most 1 running and 1 pending run. Runs in between are dropped. Matches the §10.5 design: every job is idempotent and the next scheduled run catches up. | **OK** | https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/control-the-concurrency-of-workflows-and-jobs |
| P5-5 | "Repository activity" for the 60-day schedule rule | 2026-11-25 | Still **not defined**: "In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days." Neither page lists which events count. The keepalive mechanism (P2-06) stays as decided; it must not rely on any particular definition. | **Risk (known, mitigated by P2-06)** | https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows ; https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/disabling-and-enabling-a-workflow |
| P5-6 | Firewall configuration rollback on Hobby | 2026-11-25 | Available on all plans: "it takes effect globally within 300ms and can be instantly rolled back to prior configurations"; "Vercel WAF is available on all plans". Restore from Firewall → View Audit Log. How long audit-log history is kept is not documented. | **OK** | https://vercel.com/docs/vercel-firewall/vercel-waf (updated 2026-07-29) |
| P5-7a | Sentry free plan needs a card? | 2026-11-25 | Not stated directly. Sign-up starts a 14-day Business trial "with no credit card" and then "you will be automatically assigned a free Developer plan". Sentry is optional (D7) and not planned for v1. | **OK (inferred; only relevant if Sentry is adopted)** | https://docs.sentry.io/pricing/ ; https://sentry.io/pricing/ |
| P5-7b | Docker Desktop licence fit | 2026-11-25 | Personal subscription: "Use is limited to a single, individual developer acting in a personal, non-commercial capacity to develop Open Source Software or free applications." Fits this project (OD5). Docker is optional anyway: dev setup also supports native MongoDB or mongodb-memory-server. | **OK** | https://www.docker.com/legal/docker-subscription-service-agreement/ (§3.1(b)) |

---

## 9. P0-11 re-verification (2026-11-25)

Every page above was re-opened on 2026-11-25. Results:

| Row | Status | Note |
|---|---|---|
| R2-1, R2-3, R2-4, R2-5 (allowances and prices) | unchanged | Free: "10 GB-month / month", "1 million requests / month" (Class A), "10 million requests / month" (Class B), egress "Free". Standard: "$0.015 / GB-month", "$4.50 / million requests" (Class A), "$0.36 / million requests" (Class B). https://developers.cloudflare.com/r2/pricing/ |
| R2-11 | re-copied | Exact quote now in the row; "may suspend" rather than "always" |
| W-1 (Workers Free daily limit) | unchanged | "Accounts on the Workers Free plan have a daily request limit of 100,000 requests, resetting at midnight UTC. When a Worker exceeds this limit, Cloudflare returns **Error 1027**." Routes can be set to fail open; a `workers.dev` Worker has no route, so it returns the error. Either way, **nothing is billed**. https://developers.cloudflare.com/workers/platform/limits/ |
| C-2 (status label) | unchanged | Still no beta/GA label (U-CF1 stays open; risk R22) |
| C-3, C-4 (Wrangler minimums) | unchanged | "Requires Wrangler 4.69.0 or above." / "The `cross_version_cache` option requires Wrangler 4.107.0 or above." |
| C-5, C-17 | re-copied | Exact quotes now in the rows |
| C-16 | moved | Now on the limitations page; exact quote in the row |
| D-5 | **corrected** | Only the Browser Integrity Check part is documented; the zone/WAF/Cache Rules claim is withdrawn. No effect on the design (no zone) |

**Verdict:** no change breaks plan §7.4 or §11.3. Nothing to escalate before P0-12.
