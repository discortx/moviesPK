# MoviesPK — Free-tier and platform verification

- **Purpose:** the evidence file named in `plan.md` P0-05 and P0-11. This first version records the **Cloudflare** facts behind owner decisions OD9 and OD10 (R2 reinstated; images served by a Worker on `*.workers.dev` with Workers Caching). The Vercel, Atlas, GitHub and TMDB facts verified on 2026-11-23 are in `architecture.md` §10.7 and `docs/infrastructure-and-legal-audit.md`. They are not repeated here. P0-05 adds its remaining items to this file.
- **Date checked:** 2026-11-23 for every row unless stated otherwise.
- **Sources:** official Cloudflare documentation (`developers.cloudflare.com`) and the official Cloudflare blog (marked BLOG). Community threads are never used as evidence for a [V] row.
- **Evidence key** (same as `plan.md` §4.1):
  - **[V]:** verified against the provider's official documentation on the date checked.
  - **[I]:** our technical inference from verified facts.
  - **[U]:** unverified. Every [U] row names the task that resolves it.
- **Quotation note:** the quotes were collected with an automated fetch tool. Quotes marked "~" may be lightly paraphrased. P0-11 re-copies them word for word from the page before they are cited anywhere else.
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
| R2-11 | Failed payment | If a payment fails, R2 buckets become inaccessible and requests return errors. | [V] ~ | https://developers.cloudflare.com/billing/understand/billing-policy/ |
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
| C-2 | GA or beta | **No page labels it beta, open beta or GA.** | [U] → P0-11 (re-check); risk R22 | — |
| C-3 | How to enable | TOML: a `[cache]` table with `enabled = true`. JSONC: `"cache": { "enabled": true }`. The allowed keys are `enabled` (required) and `cross_version_cache` (optional). **Minimum Wrangler 4.69.0**: "Check that your wrangler version is 4.69.0 or above, and that wrangler.toml or wrangler.jsonc has cache.enabled = true". | [V] | https://developers.cloudflare.com/workers/cache/configuration/ ; https://developers.cloudflare.com/workers/cache/debugging/ |
| C-4 | `cross_version_cache` | `true` removes the Worker version from the cache key, so entries are shared across deployments until they expire or are purged. "The cross_version_cache option requires Wrangler 4.107.0 or above." Per-entrypoint settings (an `exports` map) also need 4.107.0 or above. | [V] | https://developers.cloudflare.com/workers/cache/configuration/ |
| C-5 | Version in the cache key by default | Yes. A new deployment starts with a cold cache unless `cross_version_cache = true` (~ "cache hit rate resets on every deployment"). | [V] ~ | same ; https://developers.cloudflare.com/workers/cache/cache-keys/ |
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
| C-16 | Local tests | A local Vitest run does not exercise Workers Caching. The cache must be tested on the deployed Worker (P1-21). | [V] ~ | https://developers.cloudflare.com/workers/cache/debugging/ |
| C-17 | Turning caching off | Disabling the cache does not purge entries already cached. | [V] ~ | https://developers.cloudflare.com/workers/cache/configuration/ |

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
| D-5 | Zone features | Rules and settings of the account's own zones do not apply to `workers.dev`. Browser Integrity Check always applies on `workers.dev` and cannot be turned off. WAF and Cache Rules on `workers.dev` are not addressed. MoviesPK uses none of them (OD10). | [V] ~ | same |

## 6. Deployment from CI

| # | Item | Finding | Tag | Source |
|---|---|---|---|---|
| CI-1 | Deploy token | Use the **"Edit Cloudflare Workers"** token template, then scope it down: "We recommend scoping these down as much as possible". The template grants Workers Scripts Write, KV Storage Write, R2 Storage Write and Tail Read at account level, plus Workers Routes Write at zone level. **MoviesPK's token:** one account, Workers Scripts **Write** only, no zone resources, **no R2 permission** (the Worker reads R2 through its binding, not the token). | [V] (template; scope down) / [U] (that a deploy works without zone or R2 permissions) → P1-20 | https://developers.cloudflare.com/workers/ci-cd/external-cicd/github-actions/ ; https://developers.cloudflare.com/fundamentals/api/reference/template/ |
| CI-2 | Wrangler environments | "a Worker project named `my-worker` with an environment `dev` would deploy as a Worker named `my-worker-dev`." So `moviespk-img` with `--env dev` deploys as `moviespk-img-dev`. | [V] | https://developers.cloudflare.com/workers/wrangler/environments/ |

---

## 7. Open [U] items and the tasks that resolve them

| ID | Item | Resolved by |
|---|---|---|
| U-CF1 | Workers Caching: GA or beta status (C-2) | P0-11 (re-check); P1-21 (behaviour); risk R22 |
| U-CF2 | Workers Free needs no payment method; adding a payment method for R2 does **not** subscribe the account to Workers Paid (W-6, W-7) | P0-12 (screenshots of the billing and Workers plan pages) |
| U-CF3 | A budget alert is available on the account and includes R2 spend (R2-9) | P0-12. If it is unavailable or excludes R2, the monthly usage record (`plan.md` §7.4.3 item 6, §18.2) is the only spend signal. This is recorded and accepted by the owner (OD11). |
| U-CF4 | Binding `get()`/`head()` are billed as Class B (B-5) | P1-22 |
| U-CF5 | How the account `workers.dev` subdomain is first created (D-1) | P0-12 |
| U-CF6 | Workers Caching HITs count toward the Free 100,000/day limit (C-13) | P1-22 |
| U-CF7 | A 404 with `Cache-Control: public, max-age=60` is cached by Workers Caching for 60 s | P1-21 |
| U-CF8 | A deploy token with Workers Scripts Write only (no zone, no R2) can deploy a `workers.dev` Worker with an R2 binding (CI-1) | P1-20 |
| U-CF9 | R2 free allowance permanence (R2-2) | Z5 quarterly re-check |
| U-CF10 | Exact Cache API wording for `workers.dev` (CA-1) | Not needed: the Cache API is not used |
