# MoviesPK: Infrastructure, Cinema Viability and Legal Readiness Audit

- **Audit date:** 2026-11-23. All external sources were fetched on this date unless stated otherwise.
- **Scope:** six areas: Vercel Hobby, MongoDB Atlas Free, GitHub Actions, TMDB, Pakistani cinema viability, and legal and scraping compliance.
- **Inputs read:** `architecture.md` (v1.0), `project_statement.md`, `plan.md` (v2.0), `docs/adr/0001-respect-robots-txt.md`, `docs/adr/0007-no-custom-domain-v1-delivery.md`. **There is no `README.md`, and no implementation or configuration code in the workspace**, so implementation findings are limited to design rules.
- **Legend:**
  - **Source type:** OFF = official documentation; CIN = official cinema website; 3P = third-party evidence; LEG = legal reference (primary or secondary as stated); COM = community forum (never treated as official policy).
  - **Confidence:** H = high, M = medium, L = low.
  - **Interpretation** marks our own reading, not a provider statement.
  - **UNRESOLVED** means it could not be verified from an official source.
- **This report is not legal advice and is not a legal clearance.**
- **Revision (2026-11-23, owner clarification).**
  - The owner confirmed that MoviesPK is a **PERSONAL / NON-COMMERCIAL** project.
  - A formal legal assessment is therefore **not** a prerequisite for implementation or launch, and not a project task. None has been carried out.
  - R1 is recorded proportionately as an acknowledged operational and policy risk.
  - GO/NO-GO depends only on technical and practical viability.
  - The legal references in §7 are kept as background information only.
  - All technical safeguards (robots.txt, kill switch, and so on) remain mandatory.

---

## 1. Executive summary

| Area | Result |
|---|---|
| Vercel Hobby | Fit for purpose, with constraints. Verified:<br>- 1M function invocations per month;<br>- 300 s maximum duration;<br>- WAF on Hobby with 3 custom rules, one of which can be a rate-limit rule;<br>- cross-project external rewrites cache by default for projects created on or after 2026-04-06;<br>- Instant Rollback only to the immediately previous deployment.<br>Over-quota means a **pause**, never a bill. Hobby is "personal or non-commercial use" only, and **"commercial" is not defined** on current official pages. The Fair Use Guidelines list **"Scrapers" as never fair use**, so scraping must stay off Vercel. It already is: the scraper runs on GitHub Actions. |
| MongoDB Atlas Free | 500 connections; 512 MB; 100 ops/s (excess queued); 10 GB in and 10 GB out per rolling 7 days; one free cluster per project; paused after 30 days with zero connections. No card is required to provision. A card is required to upgrade. There is no code yet, so the connection rules are set as design requirements (one cached client, `maxPoolSize: 5`, separate read-only and read/write users). |
| GitHub Actions | Public-repo minutes are free. Artifact retention is 1–90 days (default 90). The 60-day disable rule is verified. **"Repository activity" is UNRESOLVED**: GitHub does not define it. The bot-commit keepalive is replaced by a layered approach: monthly human maintenance, a REST re-enable call, health checks and freshness alerts. |
| TMDB | About 40 requests/s upper limit; respect 429. Direct `image.tmdb.org` URLs are the documented pattern. **Hotlinking is not specifically addressed.** Attribution is mandatory (logo plus §3 notice). Use is non-commercial only. Caching is limited to 6 months. |
| Cinema viability | **21 VERIFIED VIABLE venues** across 3 independent adapters; 5 conditional, 3 excluded, 6 needing manual review. **GO** (minimum of 5, not lowered). |
| Legal and policy | Project is **personal / non-commercial** (owner-confirmed 2026-11-23). R1 is an **acknowledged operational and policy risk (Low / Medium), accepted by the owner**. No formal legal assessment is required or claimed. robots.txt compliance, the kill switch, throttling, no-bypass rules, the takedown contact and TMDB attribution are mandatory. Background references (PECA 2016, Copyright Ordinance 1962) are recorded for information. |
| **Final decision** | **GO (conditional)**: see §10. |

---

## 2. Vercel verification

| # | Question | Finding | Source URL | Type | Verified | Conf. |
|---|---|---|---|---|---|---|
| 1 | Monthly function invocations | **1,000,000** ("First 1,000,000"). The older 100,000 figure is obsolete. Also: Active CPU 4 CPU-hrs; provisioned memory 360 GB-hrs; Fast Data Transfer 100 GB; Fast Origin Transfer 10 GB; CDN requests 1,000,000. | https://vercel.com/docs/plans/hobby ; https://vercel.com/docs/limits/fair-use-guidelines | OFF | 2026-11-23 | H |
| 1b | ISR reads / writes | 1M / 200k per month included | https://vercel.com/pricing | OFF | 2026-11-23 | H |
| 2 | Function duration and size | "300s (5 minutes) default and max"; 2 GB / 1 vCPU, fixed | https://vercel.com/docs/functions/configuring-functions/duration ; https://vercel.com/docs/limits | OFF | 2026-11-23 | H |
| 2b | Over the limit | "Hobby plans will be paused when they exceed the included free tier usage"; "wait until 30 days have passed" | https://vercel.com/docs/plans ; https://vercel.com/docs/plans/hobby | OFF | 2026-11-23 | H |
| 3 | Firewall on Hobby | "Vercel WAF is available on all plans"; DDoS mitigation on all plans | https://vercel.com/docs/vercel-firewall | OFF | 2026-11-23 | H |
| 4 | Rate-limit rules | **1 per project**: "Hobby projects can have one WAF Rate Limiting rule within their total of 3 custom firewall rules." Fixed window of 10 s–10 min; keyed by IP or JA4. | https://vercel.com/docs/vercel-firewall/vercel-waf/rate-limiting | OFF | 2026-11-23 | H |
| 5 | Custom firewall rules | **Up to 3** (IP blocks: up to 10) | https://vercel.com/docs/vercel-firewall/vercel-waf | OFF | 2026-11-23 | H |
| 6 | Included rate-limit requests / charges | 1,000,000 allowed requests per month. No per-request charge on Hobby; "$0.50 per 1M" applies to Pro. Behaviour above the allowance is assumed to follow the general Hobby pause rule; the rate-limit page does not state it. | rate-limiting URL above ; https://vercel.com/pricing | OFF | 2026-11-23 | H (allowance) / M (behaviour above it) |
| 7 | External rewrite to another Vercel project | **Yes.** "An external origin is any API or website outside your Vercel project"; combining Vercel apps is a listed use case. Target the **production domain**, because Standard Deployment Protection "protects all domains except production domains". The proxy timeout is 120 s. | https://vercel.com/docs/routing/rewrites ; https://vercel.com/docs/deployment-protection | OFF | 2026-11-23 | H / M (protection caveat) |
| 8 | Caching of rewritten external responses | **Yes.** "Vercel honors `cache-control`, `CDN-Cache-Control`, and `Vercel-CDN-Cache-Control` headers from upstream servers on external rewrites" | https://vercel.com/docs/routing/rewrites | OFF | 2026-11-23 | H |
| 9 | Required headers | Priority: `Vercel-CDN-Cache-Control` > `CDN-Cache-Control` > `Cache-Control`. "If only `Cache-Control` is used, Vercel strips the `s-maxage` directive" before the browser. `private` prevents CDN caching. | https://vercel.com/docs/caching/cache-control-headers | OFF | 2026-11-23 | H |
| 10 | Existing projects must enable rewrite caching? | Only projects created **before 2026-04-06**: "enabled by default for projects created on or after April 6, 2026", otherwise via the dashboard setting or `x-vercel-enable-rewrite-caching: 1` | https://vercel.com/docs/routing/rewrites | OFF | 2026-11-23 | H |
| 11 | Instant Rollback on Hobby | **Yes** | https://vercel.com/docs/instant-rollback ; https://vercel.com/pricing | OFF | 2026-11-23 | H |
| 12 | Limited to the previous deployment? | **Yes.** "Hobby users can roll back to the immediately previous deployment." Production domain auto-assignment stays off until a deployment is promoted. | https://vercel.com/docs/instant-rollback | OFF | 2026-11-23 | H |
| 13 | Firewall configuration rollback | **A separate feature** (Firewall → audit log → restore): changes "can be instantly rolled back to prior configurations". No plan restriction is stated, and the WAF is on all plans, but no page explicitly says "Hobby". | https://vercel.com/docs/vercel-firewall/vercel-waf | OFF | 2026-11-23 | M |
| 14 | Non-commercial restriction | "You shall only use the Services under a Hobby plan for your personal or non-commercial use." Vercel may shut down Hobby projects "for any reason or no reason". **A definition of "commercial" is UNRESOLVED.** It does not appear on current official pages; a definition is quoted only on community forums, which are not used. | https://vercel.com/legal/terms | OFF | 2026-11-23 | H (quote); UNRESOLVED (definition) |
| 15 | Fair use | "Functions that query DBs or APIs" is fair use. **"Scrapers"** and "Proxies and VPNs" are **never fair use**. | https://vercel.com/docs/limits/fair-use-guidelines | OFF | 2026-11-23 | H |
| 16 | Other limits | 200 projects; 100 deployments/day; cache purge (including by tag) available on all plans | https://vercel.com/docs/limits ; https://vercel.com/docs/caching/cdn-cache/purge | OFF | 2026-11-23 | H |

**Does MoviesPK qualify for Hobby? (Interpretation, confidence L–M.)**
- A free, ad-free, unmonetised site run by an individual, with no client and no paid developer, matches "personal or non-commercial use" on its plain wording.
- A student project does **not** qualify automatically. It qualifies only while all of the following stay true: no ads, no affiliate or ticket-referral fees, no sponsorship, no paid features, no donations solicited in a way that funds the service, and no development for a company or client.
- Hobby status is also at Vercel's discretion ("any reason or no reason"). This is risk R14 in the architecture.
- **The owner confirmed this on 2026-11-23** (`plan.md` OD5): MoviesPK is personal and non-commercial, and Vercel Hobby is the intended starting plan.

**Important restrictions:**
- An over-quota pause takes the site down, and nothing can be bought to avoid it.
- A rewrite miss consumes CDN requests and transfer on `moviespk-web` **and** an invocation plus Active CPU on `moviespk-api`.
- Only one rate-limit rule is allowed.
- Rollback goes back one deployment only.
- Scraping must never run on Vercel.

**Recommended configuration (adopted in `architecture.md` §10.7):**
- **API cache headers:** `Vercel-CDN-Cache-Control: max-age=300, stale-while-revalidate=600` and `Cache-Control: public, max-age=60` on GET routes; `no-store` on `/api/v1/health`.
- **Web rewrite:** `/api/:path*` → `https://moviespk-api.vercel.app/api/:path*`, with header `x-vercel-enable-rewrite-caching: 1`. The header is harmless for new projects and protects older ones.
- **WAF:** one rate-limit rule on `moviespk-api` covering `/api/*`, keyed by IP, about 300 requests per 60 s, returning 429. Up to two further custom deny or challenge rules.
- **Test (P0-05 / P1-16):** `x-vercel-cache` goes from MISS to HIT on a repeat request.

**Architectural changes required:** none to the stack.
- The ADR-09, ADR-12 and ADR-13 rows and §10 now reflect owner decisions OD2, OD6 and OD7 and the verified limits.
- `plan.md` §11.2 already proposed the WAF rule as "if available". It is available, so the rule is now **required**.

---

## 3. MongoDB verification

| # | Question | Finding | Source URL | Type | Verified | Conf. |
|---|---|---|---|---|---|---|
| 1 | Concurrent connections | "Free clusters can only have a maximum of **500** connections." ("Free clusters were formerly known as `M0` clusters.") | https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/ | OFF | 2026-11-23 | H |
| 2 | Storage | 0.5 GB (512 MB); 100 databases; 500 collections | same ; https://www.mongodb.com/pricing | OFF | 2026-11-23 | H |
| 3 | Throughput | 100 operations/s. Excess operations are queued, with "a one second cooldown period" per connection. Data transfer is capped at 10 GB in and 10 GB out per rolling 7 days, and the network is throttled above that. | free-shared-limitations | OFF | 2026-11-23 | H |
| 4 | Free clusters per project | "at most _one_ Free cluster per Atlas project" (more only under a sales contract). Per organization: not stated (UNRESOLVED). | same | OFF | 2026-11-23 | H |
| 5 | Card required to register? | Not required by any official page. Sign-up is "using your GitHub account, your Google account or your email address". There is **no explicit statement**. | https://www.mongodb.com/docs/atlas/tutorial/create-atlas-account/ | OFF (silent) | 2026-11-23 | M |
| 6 | Card required to provision Free? | **No.** "No credit cards are required to provision a cluster". The Vercel integration docs say: "Free plan $0: No credit card is required." | https://www.mongodb.com/resources/basics/databases/cloud-databases/free-cloud-database ; https://www.mongodb.com/docs/atlas/reference/partner-integrations/vercel/ | OFF (marketing page + docs) | 2026-11-23 | M–H |
| 7 | Payment info on upgrade | **Yes.** "Atlas prompts you to enter payment information before applying your changes". Upgrading "starts billing". Upgrading from Free to dedicated "permanently deletes the current cluster and all associated backup snapshots". | https://www.mongodb.com/docs/atlas/scale-cluster/ | OFF | 2026-11-23 | H |
| 8 | Inactivity pause | 30 days with zero connections, reduced from 60 days (changelog, 2025-11-19). Warning email 7 days before. | https://www.mongodb.com/docs/atlas/release-notes/changelog/ ; https://www.mongodb.com/docs/atlas/pause-terminate-cluster/ | OFF | 2026-11-23 | H |
| 9 | Backups | Private preview only (daily snapshot, 4 retained) | free-shared-limitations | OFF | 2026-11-23 | H |
| 10 | Network access | No peering and no private endpoints on Free. The Vercel integration requires `0.0.0.0/0`. | free-shared-limitations ; Vercel integration URL | OFF | 2026-11-23 | H |
| 11 | Serverless connection guidance | Define the client "outside the … handler"; "Create the client object once"; reuse it across invocations; `maxIdleTimeMS` = 60000. **No recommended `maxPoolSize`** is given. | https://www.mongodb.com/docs/atlas/manage-connections-aws-lambda/ | OFF | 2026-11-23 | H |
| 12 | Driver default pool size | Node.js 100 and PyMongo 100. "For each process, create a client and reuse it." | https://www.mongodb.com/docs/drivers/node/current/connect/connection-options/connection-pools/ ; https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/connection-options/connection-pools/ | OFF | 2026-11-23 | H |

**Implementation inspection (requested).** The workspace has no `api/` or `scraper/` code. Multiple clients, per-request connections, pool sizing and separate credentials therefore **could not be inspected**. Status: NOT APPLICABLE YET. The design documents say:
- `plan.md` A13: a cached `MongoClient` with `maxPoolSize: 5`.
- `plan.md` §12.2: separate `moviespk_scraper` (readWrite) and `moviespk_api` (read) users.
- `plan.md` §6.3: separate secrets, `MONGODB_URI_SCRAPER` and `MONGODB_URI_API`.

These are consistent with the official guidance.

**Recommended connection strategy** (now `architecture.md` §10.6.1):
- **API:** one module-scope `MongoClient` with a memoized connect promise. Never connect per request. `maxPoolSize: 5`, `minPoolSize: 0`, `maxIdleTimeMS: 60000`, `serverSelectionTimeoutMS: ~5000`.
- **Scraper:** one client per process with `maxPoolSize: 5`, bulk writes, closed at exit.
- **Credentials:** separate users and separate secret stores.
- **Monitoring:** alert above 300 connections (60% of 500).
- Pool size 5 is our choice (Interpretation), sized to leave headroom under the 500-connection cap when several function instances run at once. Code review in P1 must check for a single client per process.

---

## 4. GitHub verification

| # | Question | Finding | Source URL | Type | Verified | Conf. |
|---|---|---|---|---|---|---|
| 1 | Max artifact retention, public repo | "For public repositories: … anywhere between 1 day or **90 days**." | https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository | OFF | 2026-11-23 | H |
| 2 | Default retention | 90 days | same | OFF | 2026-11-23 | H |
| 3 | Per-artifact retention | `retention-days` "cannot exceed the retention limit set by the repository, organization, or enterprise" | https://docs.github.com/en/actions/tutorials/store-and-share-data | OFF | 2026-11-23 | H |
| 4 | 60-day rule | "In a public repository, scheduled workflows are automatically disabled when no repository activity has occurred in 60 days." Forks of public repos start with schedules disabled. | https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows ; https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/disabling-and-enabling-a-workflow | OFF | 2026-11-23 | H |
| 5 | What counts as repository activity | **UNRESOLVED.** GitHub does not define the term on any official page checked. | — | — | 2026-11-23 | H (that it is undefined) |
| 6 | Does a workflow run alone reset inactivity? | **UNRESOLVED.** No official statement. | — | — | 2026-11-23 | — |
| 7 | Bot commit as keepalive | **Not documented as reliable.** "events triggered by the `GITHUB_TOKEN` will not create a new workflow run". The Actions terms prohibit activity "unrelated to the production, testing, deployment, or publication of the software project". | https://docs.github.com/en/actions/concepts/security/github_token ; https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features | OFF | 2026-11-23 | H (quotes); UNRESOLVED (keepalive status) |
| 8 | Public-repo minutes | "free for standard GitHub-hosted runners in public repositories" | https://docs.github.com/en/actions/administering-github-actions/usage-limits-billing-and-administration | OFF | 2026-11-23 | H |
| 8b | Run limits | 6 h per job; 35 days per workflow run; 20 concurrent jobs (Free); `GITHUB_TOKEN` 1,000 API requests per hour per repo | https://docs.github.com/en/actions/reference/limits | OFF | 2026-11-23 | H |
| 9 | Scheduled workflow limitations | Default branch only. Shortest interval 5 min. "can be delayed during periods of high loads"; "High load times include the start of every hour"; "some queued jobs may be dropped". Notifications go "to the user who last modified the cron syntax". | events URL above | OFF | 2026-11-23 | H |
| 9b | Re-enable | `PUT /repos/{owner}/{repo}/actions/workflows/{workflow_id}/enable` ("Enables a workflow and sets the state of the workflow to active"), or `gh workflow enable` | https://docs.github.com/en/rest/actions/workflows | OFF | 2026-11-23 | H |
| 9c | Warning email before disable | **UNRESOLVED.** Not documented. | disable/enable URL | OFF (silent) | 2026-11-23 | M |

**Recommended approach** (Interpretation; now `architecture.md` §10.5 and §11.4):
1. **Monthly maintenance activity (primary).** On the first weekend of each month, a human commits: Dependabot merges, a fixture refresh, or the monthly maintenance-log line. This is genuine project activity, consistent with GitHub's terms, and does not depend on the undefined definition.
2. **`keepalive.yml`** (monthly cron plus `workflow_dispatch`, `permissions: actions: write, issues: write`):
   - calls the documented **enable** endpoint for each scheduled workflow (idempotent);
   - opens the monthly maintenance issue assigned to the owner, which also serves as the reminder for step 1.
   It does **not** commit as a bot.
3. **Workflow health monitoring:**
   - `healthcheck.yml` runs hourly;
   - the canary checks that the last `scrape-full` run is newer than 18 h;
   - the owner is the last editor of the cron lines, so GitHub's failure notifications reach them.
4. **Scraper freshness alerts:**
   - full data older than 18 h, or seats older than 6 h, opens a GitHub issue;
   - `/status` shows "last updated" per cinema.
   Note that if *all* schedules are disabled, the canary is disabled too. The external signal is then `/status` staleness and the missing monthly issue. The owner checks `/status` weekly (`plan.md` §18.2).
5. **Recovery instructions** (`architecture.md` §11.4):
   1. `gh workflow list --all`
   2. `gh workflow enable <file>` for each scheduled workflow
   3. `gh workflow run scrape-full.yml`
   4. verify that `scrape_runs` and `/status` update
   5. push a maintenance commit

---

## 5. TMDB verification

| # | Question | Finding | Source URL | Type | Verified | Conf. |
|---|---|---|---|---|---|---|
| 1 | Rate limits | "As of December 16, 2019, we have disabled the original API rate limiting (40 requests every 10 seconds.)" Upper limits "sit somewhere in the 40 requests per second range. This limit could change at any time" | https://developer.themoviedb.org/docs/rate-limiting | OFF | 2026-11-23 | H |
| 1b | Per-IP and connection limits | A staff member, relayed on the forum: about 50 requests/s and 20 connections per IP via the CDN provider; image.tmdb.org limits only simultaneous connections (20); "There is no daily maximum". **Not official policy.** | https://www.themoviedb.org/talk/67c4e964c7caba424c91dba0 ; https://themoviedb.org/talk/6422345a6a34480112ba52fd | COM | 2026-11-23 | M |
| 2 | HTTP 429 | "respect the `429` if you receive one." No `Retry-After` behaviour is documented. | rate-limiting URL | OFF | 2026-11-23 | H |
| 3 | Recommended throttling | No algorithm is published. The terms prohibit "an excessive amount of bandwidth". **Interpretation:** the scraper throttles to 5 requests/s or fewer (lower than the 20/s in `plan.md` §10.4), uses exponential backoff on 429, and makes about one search per unique title thanks to the alias cache. | https://www.themoviedb.org/api-terms-of-use | OFF + Interp. | 2026-11-23 | M |
| 4 | Image URL construction | "you'll need 3 pieces of data … a `base_url`, a `file_size` and a `file_path`. The first two pieces can be retrieved by calling the /configuration API". `secure_base_url` is `https://image.tmdb.org/t/p/`. Poster sizes: w92, w154, w185, w342, w500, w780, original. | https://developer.themoviedb.org/docs/image-basics ; https://developer.themoviedb.org/reference/configuration-details | OFF | 2026-11-23 | H |
| 5 | Direct CDN URLs documented? | **Yes.** The docs show full `https://image.tmdb.org/t/p/w500/…jpg` examples. Forum (staff, 2018): sizes from `/configuration` are "officially supported. Everything else isn't." | image-basics ; https://www.themoviedb.org/talk/5accf23b0e0a267f9a00fc6d | OFF / COM | 2026-11-23 | H / M |
| 6 | Hotlinking | **Not specifically addressed** in the official terms. Prohibited: using TMDB "as an image hosting service for banner advertisements, graphics, etc." The site Terms' ban on "linking to, this Site" applies to the website, not the API or CDN (Interpretation). | api-terms-of-use ; https://www.themoviedb.org/terms-of-use | OFF + Interp. | 2026-11-23 | M |
| 7 | Attribution | "You must use the TMDB logo to identify Your use of TMDB". It must be "less prominent than the logos or marks that primarily describe or identify Your Application". Required notice: "[Your Application] uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB." The logo must not be altered. | api-terms-of-use §3 ; https://developer.themoviedb.org/docs/faq ; https://www.themoviedb.org/about/logos-attribution | OFF | 2026-11-23 | H |
| 8 | Commercial vs non-commercial | The licence "does not permit any commercial use" without a "separate written agreement". Commercial use includes "driving traffic or generating revenue for a website … (including from advertising …)". "TMDB reserves the right to, in its sole discretion, determine whether Your use is commercial". FAQ: "free to use for non-commercial purposes as long as you attribute TMDB". | api-terms-of-use §2.A ; FAQ | OFF | 2026-11-23 | H |
| 9 | Downloading and caching | Do not "Cache, for longer than 6 months, any information obtained through or from TMDB". On termination, "purge all TMDB Content, including any cached content". TMDB "do[es] not claim ownership of any of the images". | api-terms-of-use §1.C–D ; FAQ | OFF | 2026-11-23 | H |
| 10 | Termination | "TMDB may terminate the license at any time for any reason." | api-terms-of-use §1.D | OFF | 2026-11-23 | H |

**Image strategy** (Interpretation; consistent with `plan.md` §11.3 and `architecture.md` ADR-13):
1. **URLs.** Build image URLs from `secure_base_url` + a size listed in `/configuration` + `poster_path`:
   - w185 or w342 in lists, w500 or w780 on detail pages;
   - refresh `/configuration` weekly, falling back to `https://image.tmdb.org/t/p/`.
2. **Storage.** Store only `tmdbId` and `poster_path`. No image files, no Vercel Image Optimization. Refresh matched metadata at least every 7 days, which is far inside the 6-month limit.
3. **Loading.** `loading="lazy"`, explicit `width`/`height`, and `srcset` limited to the listed sizes.
4. **Fallback.** Show a placeholder on null or 404. `NEXT_PUBLIC_POSTERS_ENABLED=false` switches all posters to placeholders if TMDB objects.
5. **No decorative use.** Never use TMDB images in banners, ads or decorative graphics.
6. **Attribution.** Footer and `/about`: the TMDB logo, smaller than the MoviesPK mark, plus the §3 notice worded for MoviesPK.
7. **Stay non-commercial.** Any revenue idea, including donations, is a re-plan gate. Ask TMDB first.

---

## 6. Cinema viability results

Full evidence and per-question answers are in `docs/cinema-viability-audit.md` (source type CIN, verified 2026-11-23).

| Measure | Result |
|---|---|
| Venues evaluated individually | 29, plus 6 names with no official site |
| **VERIFIED VIABLE** | **21**: Cinepax 9, Universal 2, CineStar 4, The Arena 3, CineGold Plex 3 |
| CONDITIONALLY VIABLE | 5: Cinepax Kings Mall (city not stated), Nueplex DHA and Askari IV (address not on the official site), Cue Gulberg (ambiguous terms clause), JFC (undated showtimes) |
| EXCLUDED | 3: Atrium (domain now a casino), Capri (empty site), Centaurus (no online showtimes) |
| NEEDS MANUAL REVIEW | Super Cinema, Prince, Lyric, Nishat, Mall of Lahore, Mega Multiplex |
| Independent adapters for the verified venues | 3: Cinepax JSON, Vista HTML, Arena/CineGold platform |
| Showtime window observed | Mostly 2–5 days (Cue 7). Assumption A4 (3–7 days) is **only partly true**. |
| robots.txt | No verified venue's needed paths are disallowed:<br>- several sites have no robots.txt (404);<br>- Universal and CineStar redirect robots.txt to an HTML error page with no rules;<br>- The Arena has `Allow: /`.<br>Treating POST endpoints as covered by path rules is an interpretation. |
| Recommended first five | Cinepax Packages Mall (Lahore), Cinepax WTC (Islamabad), Cinepax Ocean Mall (Karachi; confirm address), Universal Emporium (Lahore), CineStar Township (Lahore) |

**Confidence:**
- H for Cinepax, Universal, CineStar and Arena (independently re-checked).
- M for the others (single fetch).

**Not yet tested:** reachability from GitHub runners (P0-09). Each venue is promoted only after that probe passes.

---

## 7. Legal risk assessment

> **Background information only. No legal conclusion is drawn, and no legal clearance is claimed.**
> - MoviesPK is a personal, non-commercial project (owner-confirmed 2026-11-23). The owner proceeds on that basis.
> - A formal legal assessment is **not** a prerequisite for implementation or launch, and **not** a project task (`plan.md` OD8).
> - R1 is an acknowledged operational and policy risk, managed through the technical safeguards below.
> - The references are kept so that a future change of purpose (for example monetization) can be reassessed quickly.

Source note:
- pakistancode.gov.pk and na.gov.pk could not be fetched automatically (TLS errors).
- PECA text is quoted from the Sindh Judicial Academy consolidated compilation "upto date 2025". It has not been checked against the official Pakistan Code text.
- Copyright Ordinance text is from WIPO Lex.

| Topic | Finding (quoted or summarised; no conclusion) | Source URL | Type | Verified | Conf. |
|---|---|---|---|---|---|
| PECA 2016: "authorization" | "…where an information system or data is available for open access by the general public, access to or transmission of such information system or data shall be deemed to be authorized for the purposes of this Act" (s.2) | https://www.sja.gos.pk/assets/Updated_Laws/The%20Prevention%20of%20Electronic%20Crimes%20Act%2C%20Rules%20Final%20Index%20(%20Upto%20date%202025).pdf ; official listing https://pakistancode.gov.pk (not fetchable) | LEG (primary text via official compilation) | 2026-11-23 | H (text); clause numbering to be confirmed |
| PECA: "unauthorized access" | "access to an information system or data which is not available for access by general public, without authorization or in violation of the terms and conditions of the authorization" | same | LEG | 2026-11-23 | H |
| PECA ss.3–5 | s.3 unauthorized access (up to 3 months or Rs 50,000); s.4 unauthorized copying or transmission of data (up to 6 months or Rs 100,000); s.5 interference (up to 2 years or Rs 500,000). **All require "dishonest intention".** ss.6–8 are the critical-infrastructure equivalents. | same | LEG | 2026-11-23 | H |
| PECA (Amendment) Act 2025 | Act II of 2025: SMPRA created; "Authority" redefined; s.26A (false information); NCCIA replaces FIA (s.29). **No amendment to ss.3–8 or the access definitions was found.** Challenges are pending in high courts (NCHR, Feb 2026). | https://na.gov.pk/uploads/documents/6791f889296d0_770.pdf (not fetchable) ; SJA PDF ; https://nchr.gov.pk/wp-content/uploads/2026/02/NCHR-Report-on-PECA-and-the-2025-Amendments-Act.pdf | LEG (primary + statutory-body report) | 2026-11-23 | H (ss.3–8 unchanged) / M (full list) |
| Blocking and takedown | s.37 removal or blocking power now sits with the "Authority", i.e. SMPRA; review within 30 days, then appeal to the High Court. The 2021 Removal and Blocking Rules apply, but their status under SMPRA is unclear. | SJA PDF ; https://www.dawn.com/news/1651977 | LEG / 3P | 2026-11-23 | M |
| Copyright: facts vs compilations | s.2(p): "literary work" includes "compilations of data". s.3(3): compilation copyright "shall not extend to data or other material itself". There is no sui generis database right. **No Pakistani case on factual compilations found.** | https://www.wipo.int/wipolex/en/text/129350 | LEG (primary via WIPO Lex) | 2026-11-23 | H (text) / L (case law: none found) |
| Copyright: posters | Posters are likely "artistic works" (s.2(c)) owned by studios or distributors. TMDB claims no ownership. Fair dealing (s.57) covers review and reporting; its application is a question for counsel. | WIPO Lex ; TMDB FAQ | LEG + OFF | 2026-11-23 | M |
| Terms of service | The Contract Act 1872 and the Electronic Transactions Ordinance 2002 apply. **No Pakistani browsewrap decision found.** Cinema terms found contain no explicit scraping ban, except Cue's ambiguous clause (treated as Unclear). | https://pkcert.gov.pk/wp-content/uploads/2023/07/Electronic-Transaction-Ordinance-2002.pdf ; `docs/cinema-viability-audit.md` | LEG / CIN | 2026-11-23 | M |
| Personal data | No comprehensive data-protection law is enacted. The Personal Data Protection Bill has been in draft since 2018 (2023 cabinet draft). PECA s.16 (identity information) is in force. MoviesPK collects none. | https://moitt.gov.pk/SiteImage/Misc/files/Final%20Draft%20Personal%20Data%20Protection%20Bill%20May%202023.pdf ; https://www.dawn.com/news/2021159/pakistans-privacy-debate | LEG (draft) / 3P | 2026-11-23 | H (not enacted as of Aug 2026) |
| Pakistani scraping case law or enforcement | **None found** (Pakistani law reports are not freely searchable) | — | — | 2026-11-23 | M |
| International (persuasive only, not Pakistani law) | hiQ v. LinkedIn (9th Cir. 2022): public-data scraping is likely not CFAA "without authorization", but the contract claim survived. Van Buren (2021): the "gates-up-or-down" test. Feist (1991): facts are not copyrightable. EU Directive 96/9/EC: database right; Ryanair (C-30/14): contract terms can restrict access. | https://cdn.ca9.uscourts.gov/datastore/opinions/2022/04/18/17-16783.pdf ; https://www.supremecourt.gov/opinions/20pdf/19-783_k53l.pdf ; https://supreme.justia.com/cases/federal/us/499/340/ ; https://eur-lex.europa.eu/eli/dir/1996/9/oj | LEG (international) | 2026-11-23 | H |
| TMDB licensing | Non-commercial only; attribution; 6-month cache limit; termination at will (§5 above) | api-terms-of-use | OFF | 2026-11-23 | H |
| Vercel scraping | "Scrapers" are never fair use on Vercel. The scraper runs on GitHub Actions only. | fair-use-guidelines | OFF | 2026-11-23 | H |

**Risk areas and current treatment (technical; not a legal assessment):**

| Risk area | Exposure | Treatment |
|---|---|---|
| Electronic access (PECA) | Automated access to public pages; the possible relevance of website terms | Only public, robots-allowed URLs; no login, CAPTCHA or paywall bypass; no block evasion; low rate (concurrency 1 per cinema, 1.5 s+ delays, `Retry-After`) |
| Terms of service | Some terms are ambiguous (Cue) or absent | Terms recorded per cinema; ambiguous → Unclear → excluded until reviewed or permitted; daily terms-hash re-check |
| Copyright | Compilation structure; posters | Facts re-presented in our own structure; no cinema text or artwork copied; posters only via TMDB's documented URLs; takedown response |
| Personal data | Accidental collection | Adapters parse only showtime fields; fixtures trimmed; no user data stored |
| Takedown or complaints | A notice from a cinema or regulator | `/takedown` contact page; kill switch → purge → confirm → reply within 1 working day; logged in a closed `removal` issue |
| Public repository | Visible targets and methods | No secrets; trimmed fixtures; debug artifacts kept 7 days; nothing from disallowed paths |

**Open interpretive questions (reference only; not a project task or a launch condition).** These are recorded for completeness. They would become relevant only if the project's purpose changed or a formal notice were received.
1. Does the s.2 proviso ("available for open access by the general public … deemed to be authorized") cover automated access to public showtime pages, including when terms or robots.txt restrict automated access?
2. Can website terms be "terms and conditions of the authorization" in the definition of unauthorized access?
3. Could a free, non-commercial aggregator meet "dishonest intention" or "wrongful gain"? Would donations change that?
4. Could automated request volume amount to "interference" (s.5 / s.2), and what conduct standard reduces that risk?
5. Is a showtime listing a protected compilation under ss.2(p) and 3(3), and does extracting facts infringe it?
6. Are there other causes of action: passing off, unfair competition, or Competition Act 2010 s.10?
7. What is the exposure from displaying studio posters via the TMDB API (ss.56/66), and does fair dealing (s.57) apply?
8. Are browsewrap terms enforceable against a non-clicking scraper under the Contract Act and the ETO 2002?
9. After 2025, who holds s.37 blocking power (SMPRA or PTA), and what review route and timelines apply?
10. Could MoviesPK be a "social media platform" (SMPRA duties) or a "service provider" (s.38)?
11. Could wrong showtimes ever engage s.26A, and what disclaimers or correction process are advisable?
12. Does a public scraper repository create exposure under s.13 or for abetment, including for contributors abroad (s.1(4))?
13. What obligations would arise from accidental personal data (PECA s.16, Constitution Art. 14), and what changes if the PDP Bill is enacted?

---

## 8. Architecture changes made

All changes are in `architecture.md`, now Draft v1.1.

| # | Location | Change |
|---|---|---|
| 1 | Header | v1.1 note listing the amendments; product name MoviesPK (OD1); a precedence note for sections not yet rewritten (§4, §6.4, §7.5, §8, parts of §11) |
| 2 | ADR-11 | **Corrected** to: respect robots.txt (ADR-0001); disable the adapter if a required path is disallowed unless written authorization is recorded; `ignore` rejected; kill switch kept |
| 3 | ADR-09, ADR-12, ADR-13 | Marked superseded in part: Vercel for web and API, Vercel CDN, TMDB posters (OD2, OD6, OD7, with reasons). The 7-day TTL retention is unchanged. |
| 4 | §5.3 | 60-day rule restated with the official wording; "activity" UNRESOLVED |
| 5 | §5.4 | Rewritten as "Access Policy and Politeness Controls": robots.txt mandatory, no silent override, kill switch, concurrency 1 per cinema, backoff and `Retry-After`, no login, CAPTCHA or paywall bypass, no personal data, no paid proxy |
| 6 | §5.6 | TMDB attribution, non-commercial, 6-month and throttle rules |
| 7 | §6.3 | Verified Atlas limits; the backup now goes to an Actions artifact |
| 8 | §10.1 | Hosting table revised, with the reasons for each change |
| 9 | §10.5 | `keepalive` redefined (REST enable plus maintenance issue, no bot commit); `healthcheck` added |
| 10 | §10.6 / new §10.6.1 | Superseded environment variables; MongoDB connection strategy |
| 11 | New §10.7 | Verified third-party limits (Vercel, Atlas, GitHub, TMDB) with sources and the recommended configuration |
| 12 | §11.4 | Recovery steps for disabled workflows; a row for delayed or dropped schedules |
| 13 | §12.3 | Rewritten: robots.txt respected, per-cinema evidence, legal risk areas (PECA, terms, copyright, personal data, unauthorized access, takedown, public repo, TMDB), mandatory safeguards, corrected TMDB notice; not legal advice |
| 14 | §16 | **R1 updated** (revised after the owner's clarification): third-party website policy / terms exposure, an acknowledged operational and policy risk, Low / Medium, ACCEPTED by the owner on a non-commercial basis. No formal legal assessment required or claimed. R8 updated; R13 (cinema count) and R14 (Vercel pause) added. |
| 15 | §17 Phase 4 | Legal-review step removed. Launch keeps the `/takedown` contact, TMDB attribution, and "no clearance claimed" wording. |
| 15b | §1 header, §2.2, §12.3, §18.2 | Commercial status recorded as **PERSONAL / NON-COMMERCIAL** (owner, 2026-11-23); legal review removed from open items |
| 16 | §18 | A3 resolved, A11 resolved; §18.2 items resolved or struck through; new UNRESOLVED items 10–14 |

**Preserved:**
- ADR-01–08 (apart from noting OD4 cost);
- ADR-10, where the plan's removal of Nominatim is already documented in `plan.md`;
- ADR-14–17;
- the data model, API design, the five-cinema minimum, and the per-cinema kill switch.

**Stack:** not changed. MERN plus a Python scraper. Only hosting moved, per owner decisions recorded on 2026-11-22.

**Related document:** `plan.md` OD5 (non-commercial, re-confirmed 2026-11-23), OD8 (no formal legal assessment required) and R1 have been aligned with this report. The G0 gate is technical only.

---

## 9. Outstanding questions

| # | Item | Status | Owner action |
|---|---|---|---|
| Q1 | ~~Formal legal review~~ | **Removed** (owner clarification, 2026-11-23) | Not required for implementation or launch; not a project task |
| Q2 | ~~`plan.md` OD8 vs R1~~ | **Resolved** | OD8 stands (no formal legal assessment); R1 aligned |
| Q3 | Vercel "commercial" definition | Definition UNRESOLVED on official pages; **status confirmed: personal / non-commercial** (owner, 2026-11-23) | None. Reassess only if the purpose changes. |
| Q4 | GitHub "repository activity" definition | UNRESOLVED | Adopt the layered keepalive; watch for the first 60-day cycle |
| Q5 | Firewall config rollback on Hobby; Atlas card at registration | UNRESOLVED (medium confidence) | Confirm in the dashboard or sign-up at P0-04/P0-05 |
| Q6 | TMDB hotlinking | Not addressed by TMDB | Keep the poster flag and placeholder; optionally email TMDB to confirm |
| Q7 | Cross-project rewrite cache HIT | To test | P0-05 throwaway projects / P1-16 |
| Q8 | Runner reachability for each viable venue | To test | P0-09 probe before enabling each venue |
| Q9 | Conditional venues (Kings Mall, Nueplex ×2, Cue, JFC) | Pending | Confirm addresses; Cue: request permission or review the terms clause; JFC: decide whether undated weekday times are acceptable (recommend not) |
| Q10 | Short showtime windows (2–5 days) | Product impact | Accept; the UI shows only the dates published; update A4 |
| Q11 | `README.md` absent; not a git repository | Process | Initialise the repository or copy these docs into the GitHub repo on an audit branch (see the final note) |

---

## 10. Final GO/NO-GO decision

**GO, conditional.**

| Criterion | Status |
|---|---|
| ≥ 5 VERIFIED VIABLE venues | **Met: 21** (the minimum of 5 is not lowered) |
| Infrastructure verified from official sources | Met: Vercel, Atlas, GitHub and TMDB. UNRESOLVED items are listed and none blocks the build. |
| robots.txt compliance throughout the architecture | Met: ADR-11, §5.4 and §12.3 |
| Per-cinema kill switch | Kept: §5.4, §12.3, `plan.md` §12.5 and §18.4 |
| Commercial status | **Personal / non-commercial** (owner-confirmed 2026-11-23). Vercel Hobby and TMDB non-commercial use with attribution remain the intended options. |
| R1 | Acknowledged operational and policy risk, **accepted** on a non-commercial basis. Formal legal assessment is **not** a GO/NO-GO or launch condition, and no legal clearance is claimed. |

The GO/NO-GO decision depends only on technical and practical viability. Conditions before Phase 1 (gate G0, `plan.md` §14):
1. **Cinemas:** the GitHub runner reachability probe passes for at least 5 VERIFIED VIABLE venues. This is the main criterion: fewer than 5 means NO-GO.
2. **Extraction:** reliable showtime extraction is shown on fixtures for the first adapters (Cinepax JSON, Vista HTML).
3. **Caching:** a cache HIT through the cross-project rewrite is demonstrated, or the documented fallback (direct calls with CORS) is accepted.
4. **Hosting and database:** projected load stays within the Vercel Hobby and Atlas Free limits (§2, §3). Accounts are created with no payment method.
5. **Scheduling:** the layered keepalive and freshness alerts are in place (§4).

Before public announcement, as operational items only:
- the `/takedown` contact page is live and the removal drill is done;
- TMDB attribution is shown.
