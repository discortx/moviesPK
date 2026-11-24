# Change report: R2 reinstated with Worker image delivery (OD9, OD10)

- **Date:** 2026-11-23
- **Scope:** `plan.md` v2.0 → **v2.1**; `architecture.md` v1.1 → **v1.2**. New files:
  - `docs/free-tier-verification.md`
  - `docs/adr/0009-reinstate-r2-and-worker-image-delivery.md`
  - `docs/archive/plan-v2.0.md` (a byte-identical copy of plan v2.0)
  - this report
- **Not edited:** `project_statement.md` (a proposal is in §8), `docs/adr/0001-*`, `docs/adr/0007-*`, `docs/cinema-viability-audit.md`, `docs/infrastructure-and-legal-audit.md`.
- **Input files that do not exist:**
  - `docs/adr/0002`–`0006`: never created.
  - `docs/adr/0008-zero-cost-architecture.md`: planned under P0-10 and not yet written.
  - `docs/free-tier-verification.md`: did not exist before this change; it has now been created.
- **Not legal advice; no legal clearance is claimed anywhere.**

---

## 1. Open decisions (each has a default; work proceeds on the default)

| # | Decision | Recommendation | Consequence of each option |
|---|---|---|---|
| 1 | `cross_version_cache` true or false (plan Q8) | **true** | **true:** a redeploy keeps the warm cache, because names are immutable and a cached 200 can never go stale. But a deploy that changes headers does not affect entries already cached (200 responses effectively permanent; 404s for at most 60 s); fixing them would need `ctx.cache.purge` or new keys. Needs Wrangler ≥ 4.107.0. **false:** every deploy starts cold [V C-5], so each poster is re-read from R2 (Class B, still far under the allowance) and the hit ratio drops briefly. Header changes take effect at once. |
| 2 | Referer hotlink check (Q9) | **DECIDED by OD11: not built** | **Skip:** simplest; hotlinked requests count toward 100,000/day but cannot bill (R25). **Include:** ineffective, because a cache HIT never runs the Worker [V C-11]. It would only run on misses, unless the cache is varied by Referer, which lowers the hit ratio. It also breaks no-referrer clients and privacy browsers. |
| 3 | Copy cinema-supplied images to R2 (Q12) | **no**: TMDB posters only, placeholder for unmatched movies | **No:** no copying of cinema artwork (R1 stays lower); unmatched and provisional movies show a placeholder. **Yes:** better coverage for local films, but cinema artwork would be copied; it needs a `cinemas/` key pattern, a second Worker allow-list pattern, `cinemas.image` restored and a new ADR. |
| 4 | Backups: private R2 bucket or GitHub Actions artifact (Q11) | **artifact** | **Artifact:** no second bucket or token and no Class A writes; 60-day retention keeps exported TMDB data under 6 months old; the data is public anyway. **R2 bucket:** needs a separate private bucket that is never bound to the Worker, another token scope and more writes. No recovery benefit, because the data is re-derivable. |
| 5 | Billing-alert threshold and recipient; purge threshold N (Q13) | **$1** to the owner's Cloudflare account email; **N = 90 days** | **Alert:** budget alerts are account-wide, email-only and informational [V R2-9]. A low threshold catches any spend early. If the alert is unavailable or excludes R2 [U-CF3], the monthly check and the daily size guard carry the load. **N:** a smaller N (for example 30) purges sooner, so pages of recently ended films lose posters. A larger N (≤ 150) keeps them longer. At N = 150 the worst-case age is 7 + 150 + 1 = 158 days, so a 60-day export artifact would reach 218 days, over the 6-month limit. **At N > 112 the export retention must shrink** (it must satisfy 8 + N + retention ≤ 180). The plan's config validation therefore rejects N > 112 while the export retention is 60 days. |
| 6 | Worker name and `workers.dev` account subdomain (Q14) | Worker `moviespk-img` (dev `moviespk-img-dev`); a neutral subdomain such as `moviespk` | The URL is `<worker>.<subdomain>.workers.dev` [V D-2]. The subdomain is public and should not contain a personal name. Changing either later means changing `NEXT_PUBLIC_IMAGE_BASE` and redeploying the web; there is no data migration (keys only). |

---

## 2. Sections changed

### 2.1 `plan.md` (v2.1)

| Section | What changed | Why |
|---|---|---|
| Header, revision history | v2.1, 2026-11-23, supersedes v2.0; references architecture **v1.2** (not v1.0), ADR-0009 and the verification file | OD9/OD10; stale item 1 |
| §1 | Design paragraph (R2 + Worker); "Cost: $0 expected; R2 is the only service with a payment method; target spend $0"; Workers Free caps R2 reads; new effort and weeks; verdict conditions updated (the P0-05 remainder; Cloudflare condition added; non-commercial kept) | OD9/OD10; stale item 2 |
| §2.1 | O2 and O6 now say poster from the Worker and WebP with immutable caching | OD10 |
| §3.1 | F7 rewritten | OD10 |
| §3.2 | Cost row; scale row mentions the Workers Free limit; availability row mentions placeholders | OD9 |
| §3.3 | OD2 extended (no owned-domain subdomain; images on `*.workers.dev`); **OD4 revised**; OD6 marked superseded; OD8 says "contact and data removal on `/about`"; **OD9, OD10 added** | Brief A; stale item 7 |
| §4.1 | A1 resolution; A4, A5, A13, A14, A15 updated with verified facts and the new mechanisms; A12 confirmed; A16, A17, A18, A22 updated | Stale items 2, 3, 8 |
| §4.2 | D1, D3, D4, D10, D15 rewritten | OD9/OD10 |
| §4.3 | Architecture edits marked done (v1.2); statement edit reduced to a proposal; ADR-0007 → superseded by ADR-0009 | Brief: architecture rewrite |
| §5.1–§5.4 | Diagram (Worker, Workers Caching, R2, deploy workflow; health check includes a poster); component table (scraper + Pillow/boto3, image storage, image delivery); flows; failure rows (Worker limit, R2, policy change, image upload failure) | Brief C |
| §6.1 | Inventory: R2 (Required, payment method yes, R2 only); Workers Free; "Not used / Forbidden" list replaces the v2.0 "Removed" list | Brief D |
| §6.2 | Pillow and boto3 restored; images-worker tooling (`wrangler` ≥ 4.107.0, Vitest Workers pool) | Brief D |
| §6.3 | R2 and deploy variables restored and scoped; `NEXT_PUBLIC_IMAGE_BASE`, `NEXT_PUBLIC_IMAGES_ENABLED`; `API_ORIGIN` = production domain; "Not used" list corrected | Brief D; stale item 4 |
| §7 (renamed) | **Z1–Z3 rewritten**; §7.2 table with verified values and the Cloudflare rows; cost line; **new §7.4**: what can bill, forecast with arithmetic, controls, kill procedure, forbidden products | Brief A, B, C7; stale item 2 |
| §8.1–§8.4 | `movies.poster {key, width, height}`; `lastShowingAt`, `tmdbRefreshedAt`; `showtimes.movie.posterKey`; image counts in `scrape_runs`; new index; image write rule | Brief C4 |
| §9.1–§9.3 | `Vercel-CDN-Cache-Control` column; API returns keys; **`maxIdleTimeMS: 60000`**; cache headers with `x-vercel-enable-rewrite-caching: 1`; `/about` and `/privacy` text; images bullet points to §11.3 | Stale items 5, 8 |
| §10.3 | **Step 5a (images)** | Brief D |
| §10.4 | **TMDB ≤ 5 req/s with backoff** (was 20/s); 7-day refresh for now-showing movies | Stale item 6; TMDB rule |
| §10.5 | Canary scope (purge, image GC); health check includes a poster; export retention; keepalive schedule; **`deploy-images-worker.yml`**; **queued-`seats` rule** | Brief D; stale items 3, 9 |
| §11 | §11.1 layers; §11.2 Firewall now verified; **§11.3 rewritten** (storage, Worker spec, caching, data model and frontend with the **single per-page budget**, TMDB rule, failure behaviour, escape hatch, security); §11.4 note on poster keys | Brief C |
| §12 | Cloudflare credentials, `images-approval` environment, CSP with the Worker host, Worker controls, privacy disclosure, no images in the repo | Brief C8 |
| §13 | Image unit tests, image integration, Worker unit and live rows, frontend image tests, P3-14 e2e, coverage and path filter for `images-worker/` | Brief tasks |
| §14 | Phase sums; **G0** Cloudflare condition and the new payment rule; P0-05 scope noted as reduced; G0 Cloudflare fail path; G1 poster HIT; G2 purge; G3 image e2e | Brief A |
| §15 | New tasks P0-11, P0-12, P1-18…P1-24, P2-10, P3-14. Changed: P0-01–P0-06, P0-08, P0-10, P1-04, P1-09, P1-10, P1-13, P1-14, P1-16, P1-17, P2-02, P2-03, P2-05, P2-06, P2-08, P2-09, P3-02–P3-04, P3-06, P3-07, P3-11, P3-12, P4-01–P4-06 | Brief tasks; stale items 2–6, 8 |
| §16 | Critical path, diagram, category table, task sums, calendar A–D, milestones (with arithmetic) | Brief re-estimate |
| §17 | Images column; **preview uses the API production domain** (Deployment Protection); Worker deploy and rollback rows; rollback scope "previous deployment only" | Stale items 2, 4 |
| §18 | §18.1 image, R2 and Worker signals (**100,000/day** and 1027 meaning); §18.2 weekly Worker graph, monthly Z1 + R2 check; §18.3 rotation and images-down procedures; **§18.4 image delivery emergency** | Brief D |
| §19 | Backup decision (artifact, 60-day retention); poster row | Brief D; open decision 4 |
| §20 | R1 (posters in R2; `/takedown` removed); R6, R7, R8, R9, R10, R15, R17 wording; **R12 reworded; R13 rewritten; R20–R25 added** | Brief D; stale item 7 |
| §21 | Cost checklist (new Z1 rule, billing alert, under 25%); purge test; **Images** block; real phone; secrets incl. Cloudflare | Brief D |
| §22 | Q8–Q14 added (Seat threshold renumbered Q15); §22.2 new [U] items, resolved items removed; §22.3 sources updated | Brief D |
| Appendix A | **A.1 v2.0 → v2.1 mapping**; A.2 kept, with notes where v1.2 scope returns | Brief |

### 2.2 `architecture.md` (v1.2)

| Section | What changed | Why |
|---|---|---|
| Header / amendments block | v1.2; OD9/OD10; what is superseded again; the "sections not yet rewritten" sentence removed | Brief |
| §1, §2 | Summary, goals, principles, F7, non-functional (cost, performance aligned with plan §3.2, privacy), constraints | Contradictions ($0 vs R2) |
| §3 | Decision log: one "Current status" column with short history notes, replacing the strike-throughs; ADR-08, -09, -10, -12, -13, -14, -15, -16, -17 updated; **ADR-18 added** | Brief |
| §4 | Diagram and component table rewritten (Worker + Workers Caching → R2 binding; Actions → Atlas and R2; Vercel web/API with rewrite; TMDB; GitHub Issues). No Cloudflare CDN/DNS/WAF, Render/Railway/Fly, Telegram/Discord or Nominatim | Brief (P0-10 scope) |
| §5 | Images line, CLI, config sample (`location`, evidence, no `location_override`), jobs table, image step, sequence diagram (GitHub Issues, R2), error table (robots row; Nominatim row removed) | Brief |
| §6 | Collections (poster keys; `locationSource` and `image` removed; `movieKey` IDs; `posterKey`), indexes, geo note (client-side distance), retention (60-day export), **§6.4 rewritten** | Brief |
| §7 | Structure (no Dockerfile, no rate-limit middleware); §7.3 endpoints per plan §9.1; §7.4 samples (snapped coordinates, keys); **§7.5** (Vercel Firewall, `Vercel-CDN-Cache-Control`, no purge, no pinger) | Brief |
| §8 | No map; Directions link; client-side nearest city and haversine; **§8.6** Worker + browser caching and the per-page budget; `/takedown` removed | Brief |
| §9 | Rewritten: client-side distance; `$geoNear` for API consumers; coordinates from YAML; no Nominatim | Brief |
| §10.1–§10.7 | Hosting table (image storage and delivery rows); deployment diagram; environments; containerization; CI table (Worker CI and deploy; export instead of backup to R2); env vars and superseded note; §10.7: corrected header config, TMDB image rules, **R2 and Workers Free / Workers Caching tables** | Brief |
| §11 | GitHub Issues alerts table (images down / 1027, R2 storage, budget alert); UptimeRobot, Telegram/Discord and Sentry-as-required removed; failure table (blocked → drop; Worker limit; R2; policy change; token leak) | Brief |
| §12 | Cloudflare credentials, Worker controls, privacy disclosure, posters via TMDB → R2, "Contact and data removal" instead of `/takedown`, artifact retention 60 days | Brief; stale item 7 |
| §13–§18 | Testing rows; folder tree (`images-worker/`); scalability without a paid path; risks R3, R6, R7, R9, R10, R12 updated and **R15–R20 added**; roadmap aligned with plan phases; open questions resolved or updated | Brief |

---

## 3. Removed because it became unnecessary

- **TMDB hotlinking:**
  - `NEXT_PUBLIC_TMDB_IMAGE_BASE`;
  - the `image.tmdb.org` CSP origin;
  - `poster {source: "tmdb", path}` and `showtimes.movie.posterPath`;
  - the "TMDB image CDN" service row;
  - the hotlink risk wording in R12;
  - the hotlink [U] items (plan §22, architecture §18.2 item 13).
- **`NEXT_PUBLIC_POSTERS_ENABLED`**, renamed to `NEXT_PUBLIC_IMAGES_ENABLED`.
- **Statements that R2 or Workers are dropped:**
  - OD6 (kept only as a struck-through history row);
  - the v2.0 §7.2 rows "Cloudflare R2 … Rejected" and "Cloudflare Workers / `r2.dev` … Rejected";
  - "Removed from v1.2: Cloudflare (R2, Workers …)";
  - "Removed: Pillow, boto3";
  - "Removed: all `R2_*`".
- **Keepalive option (a), the scheduled bot commit:** removed from P0-05 and P2-06. The mechanism is fixed: REST enable, maintenance issue and human commit.
- **The keepalive and Vercel/Atlas/GitHub items already verified on 2026-11-23:** removed from P0-05 and §22.2.
- **`/takedown`** references in plan R1 and in the architecture (§8.2, §12.3, §16 R1, §17).
- **Architecture v1.0 leftovers:**
  - Cloudflare CDN/DNS/WAF, the purge API and `cdn.<domain>`;
  - Render/Railway/Fly and the API Dockerfile and `deploy-api`;
  - UptimeRobot and the uptime pinger; the Telegram/Discord webhook; Sentry as required;
  - Nominatim, `locationSource`, `location_override`; MapLibre/Leaflet and the map;
  - `express-rate-limit`; MinIO; the `backup` workflow to R2; the `R2_BACKUP_BUCKET` and `backups/` prefix; `cinemas.image`; `movies.backdrop`;
  - client-rounded coordinates sent to the API; the "Upgrade to M10 / $5 plan" growth path.
- **No v2.0 task was deleted.** The hotlink and flag logic lived inside task details and was rewritten in place (Appendix A.1).

## 4. Deliberately kept

- Every owner decision not touched by OD9/OD10: OD1, OD3, OD5, OD7, OD8. OD2 is kept and extended to owned-domain subdomains.
- Vercel Hobby (two projects, rewrite, Firewall), Atlas Free, the public GitHub repo, the free TMDB API, and GitHub Issues alerts.
- The data model fields unrelated to images; the cinema list and the viability-audit results; the robots.txt policy and scraping etiquette (§10.2, architecture §5.4); the per-cinema kill switch.
- The test strategy, except for the added image tests.
- Backups as an Actions artifact (now with an explicit 60-day retention).
- The 7-day showtime TTL (A20); the 5-cinema minimum and the NO-GO rule.
- All stable IDs (tasks, ODs, A/D findings, risks R1–R19, Q1–Q7). The seat-threshold question moved from Q9 to Q15 to make room for the image questions in order. No task was renumbered.
- The v1.2 → v2.0 mapping (Appendix A.2).
- **Small fix outside the brief, recorded here:** plan §9.3 JSON-LD said "escape `<` as `<`" (a rendering loss). It now says `<`.

---

## 5. Effort and calendar (arithmetic)

**Changed estimates:**

| Task | Change |
|---|---|
| P0-05 | 1.0 → 0.5 |
| P0-08 | 3.0 → 1.5 |
| P4-05 | 1.0 → 1.5 |
| P0-11 (new) | 0.5 |
| P0-12 (new) | 0.5 |
| P1-18 … P1-24 (new) | 0.5 + 1.5 + 0.5 + 0.5 + 0.5 + 2.0 + 0.5 = 6.0 |
| P2-10 (new) | 1.0 |
| P3-14 (new) | 0.5 |

Every other touched task was re-estimated, and its estimate is unchanged.

**Phase sums:**

| Phase | v2.0 | Delta | v2.1 |
|---|---|---|---|
| P0 | 11.0 | −0.5 −1.5 +0.5 +0.5 | **10.0** |
| P1 | 20.0 | +6.0 | **26.0** |
| P2 | 25.5 | +1.0 | **26.5** |
| P3 | 17.0 | +0.5 | **17.5** |
| P4 | 5.0 | +0.5 | **5.5** |
| **Total** | **78.5** | **+7.0** | **85.5** |

**Contingency (20%):**
- Total: 85.5 × 0.2 = 17.1, so the total with contingency is 85.5 + 17.1 = **102.6 d**.
- Per phase: 2.0, 5.2, 5.3, 3.5, 1.1, giving 12.0, 31.2, 31.8, 21.0 and 6.6 d.

**Calendar days** (effort with contingency × 7 ÷ 4, rounded up):

| Phase | Arithmetic | Days |
|---|---|---|
| P0 | 12.0 × 7 ÷ 4 = 21.0 | 21 |
| P1 | 31.2 × 7 ÷ 4 = 54.6 | 55 |
| P2 | 31.8 × 7 ÷ 4 = 55.65 | 56 |
| P3 | 21.0 × 7 ÷ 4 = 36.75 | 37 |
| P4 | 6.6 × 7 ÷ 4 = 11.55 | 12 |
| Watch week | — | 7 |
| P2, 5-cinema scope | 18.5 × 1.2 = 22.2; 22.2 × 7 ÷ 4 = 38.85 | 39 |

**Scenarios** (start 2026-11-30, which is day 334 of 2026):

| Scenario | Days | Weeks | Finish |
|---|---|---|---|
| A: one developer, full scope | 21+55+56+37+12+7 = **188** | 26.9 | 334+188 = 522 → day 157 of 2027 = **2027-06-06** |
| B: two developers, full scope | 21+55+56+12+7 = **151** | 21.6 | **2027-04-30** |
| C: one developer, 5 cinemas | 21+55+39+37+12+7 = **171** | 24.4 | **2027-05-20** |
| D: two developers, 5 cinemas | 21+55+39+12+7 = **134** | 19.1 | **2027-04-13** |

**Milestones** (scenario A; scenario B in brackets):

| Milestone | Day | Date |
|---|---|---|
| M0 | 21 | 2026-12-21 |
| M1 | 76 | 2027-02-14 |
| M2 | 132 | 2027-04-11 |
| M3 | 169 | 2027-05-18 [B: day 113, 2027-03-23] |
| M4 | 181 | 2027-05-30 [B: day 144, 2027-04-23] |
| M5 | 188 | 2027-06-06 [B: day 151, 2027-04-30] |

**Usage forecast** (planning estimates, plan §7.4.2):
- **Worker requests:** 50,000 × 11 × 0.5 ÷ 30 = 9,167/day = **9.2%** of 100,000. Peak day (3×): 27.5%. Worst-case average: 30%.
- **R2 storage:** 300 movies × 200 KB × 1.5 + 10 MB ≈ 0.1 GB = **1.0%**.
- **R2 Class A:** ≤ 1,000/month = **0.1%**.
- **R2 Class B:** 275,000 × 25% + 1,000 ≈ 70,000/month = **0.7%**. Hard bound from the Worker limit: 3.1M = 31%.

---

## 6. Remaining [U] items (with resolving task)

**Cloudflare** (`docs/free-tier-verification.md` §7):

| ID | Item | Resolving task |
|---|---|---|
| U-CF1 | Workers Caching GA/beta label | P0-11 |
| U-CF2 | Workers Free needs no card; a card added for R2 does not switch the account to Workers Paid | P0-12 |
| U-CF3 | Budget alert is available and covers R2 | P0-12 |
| U-CF4 | Binding reads are billed as Class B | P1-22 |
| U-CF5 | How the `workers.dev` subdomain is first created | P0-12 |
| U-CF6 | HITs count toward the Free 100,000/day limit (assumed yes) | P1-22 |
| U-CF7 | A 404 with `max-age=60` is cached | P1-21 |
| U-CF8 | A deploy token without zone or R2 permissions works | P1-20 |
| U-CF9 | R2 free allowance permanence | Z5 |
| U-CF10 | Exact Cache API wording on `workers.dev` | Not needed |
| — | Any automated signal near the Workers Free daily limit | P0-12 |
| — | Workers Caching may be per Cloudflare location (affects the miss ratio only) | P1-22, P4-03 |

**Other:**
- Rewrite cache HIT, and whether `x-vercel-enable-rewrite-caching` is read upstream (P0-05, P1-16).
- Vercel log query strings (P0-05).
- Atlas card at registration (P0-04).
- GitHub: "repository activity", required reviewers on public-repo environments, pending-run replacement (P0-05).
- Firewall configuration rollback (P0-05).
- Sentry and Docker Desktop licence (P0-05).
- Cinema runner reachability (P0-09).

**Brief claims that did not verify as stated:**
- **The Cache API sentence was not found.** The brief said the docs state the Cache API "has no effect on `*.workers.dev`". The current page only says that custom domains get functional `cache` operations. The decision not to use the Cache API stands either way (CA-1, CA-2).
- **No published GA/beta label for Workers Caching.** No page labels it GA or beta.
- **Spending limits exist but do not help.** They now exist for Workers (changelog 2026-11-13) but **exclude R2**.
- **The "Usage Based Billing" notification is unusable.** It needs a Pro zone plan, which is Forbidden.
- **Free-plan size limits differ from the old figures.** They are 64 MiB uncompressed and 128 MB of memory. Neither matters for this Worker.

---

## 7. Final consistency check (run 2026-11-23)

Method: `grep` over `plan.md`, `architecture.md` and the ADR for every term in the brief, plus scripted checks of task references and environment variables. Three defects were found and fixed:
- **N maximum:** the plan allowed N up to 150, which with the 60-day export retention would let TMDB data reach 218 days. The plan now limits N to 112 while the retention is 60 days.
- **§16.3 note:** it said "+11.0 d" of new tasks; the itemised sum is 9.0 d. Corrected.
- **`PURGE_AFTER_DAYS`:** it looked like an unlisted variable. It is now stated to be a code constant, not an environment variable.

| Check | Result |
|---|---|
| R2, r2.dev, Cloudflare, Worker(s), Cache API, `caches.default`, `cdn.`, `CDN_BASE_URL`, `TMDB_IMAGE_BASE`, `POSTERS_ENABLED`, `IMAGES_ENABLED`, custom domain, Nominatim, Telegram, Discord, UptimeRobot, Render, Railway, Fly, map, MapLibre, Leaflet, takedown, "$0", "no payment", "payment method", Z1, OD4, OD6 | **Pass.** Every hit is either the current design (OD9/OD10) or an explicit negation, history note or "Not used / Forbidden" entry. No `cdn.<domain>` remains. "takedown" appears only in history rows (A19, D12, the v1.2 mapping) and as a generic word in the ADR-11 rationale; there is no `/takedown` page reference in the current design. |
| No bucket described as public; the Worker binds only the images bucket | **Pass.** Every bucket mention is private. Each environment has exactly one `IMAGES` binding. Backups are explicitly never bound. |
| No document says R2/Workers are both dropped and used | **Pass.** "Dropped" appears only in superseded or history context (OD6 struck through, A1 "v2.0: … superseded", ADR-13 history). |
| Every referenced task exists (dependencies, critical path, flow diagram, milestones, Appendix A) | **Pass.** 66 tasks defined (P0-01…P0-12, P1-01…P1-24, P2-01…P2-10, P3-01…P3-14, P4-01…P4-06). The only IDs not defined are v1.2 IDs cited as such (A8: v1.2 P0-16, P4-10) and the retired IDs in Appendix A.2. |
| Effort sums, totals, contingency, calendar days and dates add up | **Pass.** See §5. Category rows sum to the task sums; per-phase contingency sums to 17.1; the dates were recomputed from day 334. |
| Every §6.3 variable is used by a component, and every component's variables are listed | **Pass.** All 15 non-built-in names appear in their components' tasks and sections. Wrangler's `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` are documented as step-local exports of listed secrets. The Worker uses no variables. Vercel holds no Cloudflare credentials. |
| Per-page image budget stated once and reused | **Pass.** Defined only in plan §11.3.4. §7.4.2 (forecast), §12.3/P4-02 (CSP), P3-06, P3-14 (tests) and architecture §8.6 refer to it. |
| 100,000/day Worker limit and its failure mode in §7, §11, §18, §20 | **Pass:** §7.2, §7.4.2; §11.3.6; §18.1, §18.2, §18.3; §20 R21. |
| Launch checklist and G0 match the new rules | **Pass.** Both require a payment method only on Cloudflare, only R2, Workers Free, a billing alert or the recorded manual check, and under 25%. |

---

## 8. Proposal for `project_statement.md` (owner's document; not edited)

- Replace "CineNear" with "MoviesPK" in §1 ("CineNear is a web-based…") and §10 ("CineNear brings…").
- Optional: change §6 item 4 "Seat availability status" to "Seat availability status where the cinema publishes it" (ADR-0001).
- **No R2 edit is needed.** The statement already says Cloudflare R2 stores images, which now matches OD9.

---

## 9. Owner clarification OD11 (2026-11-23)

The owner reviewed the R2 allowances and the projected usage, accepts the free allowances, and accepts the residual spend risk. **This is the owner's approval to proceed with R2 + Worker, subject to the remaining verification items (§6).** No unrelated decision changed, and no paid service was started.

**How the three categories are now kept apart:**

| Category | Recorded in |
|---|---|
| Technical platform limits (provider facts; unchanged) | `docs/free-tier-verification.md` §1–§6 |
| Expected MoviesPK usage (planning estimates, owner-accepted assumptions) | `docs/free-tier-verification.md` §0; `plan.md` §7.4.2; the usage log in `docs/capacity.md` once measured |
| Owner-accepted residual financial risk (no hard cap; $0 expected, not guaranteed) | `plan.md` OD11, §7.4 intro, R20; `architecture.md` header, §6.4, R7, R15; ADR-0009 "Owner clarification" |

**Changes made:**

| File | Section | Change |
|---|---|---|
| `plan.md` | Revision history | New "2.1 (owner clarification)" row |
| `plan.md` | §1 | Cost line says $0 is not guaranteed; owner approval paragraph added under the verdict |
| `plan.md` | §3.2, §7.2 | Cost wording: expected, not guaranteed (OD11) |
| `plan.md` | §3.3 | **OD11** added |
| `plan.md` | §7.4 | Retitled; three-category table added. Controls marked basic by design. Item 6 is now a **usage record** (writes per run, bucket size daily with one 1 GB alert, monthly storage, Class A and Class B from the dashboard into `docs/capacity.md`). **The automatic 2 GB upload stop is removed.** New item 9 (no credentials in frontend code). New closing rule: Z3 first; paid plan or provider only on measured need and a new owner decision. |
| `plan.md` | §10.3 step 5a | Reference to the bucket-size stop removed |
| `plan.md` | §11.3.2 | Referer check: "Not built (OD11; Q9 decided)" |
| `plan.md` | **§11.3.9 (new)** | Configurability: one image-base variable, one bucket binding per environment, one S3-compatible storage module, key layout in `shared/constants` |
| `plan.md` | P0-06 | Key pattern added to the shared constants |
| `plan.md` | P2-03, P2-10 | "Size guard" → "usage record". No stop flag. Acceptance test changed. Estimate re-checked and unchanged (1.0 d). |
| `plan.md` | §18.1, §18.2 | Bucket-size row is alert-only; monthly "R2 usage record" into `docs/capacity.md` |
| `plan.md` | §20 R20 | Contingency: residual risk accepted by the owner; no paid plan or provider unless measured usage justifies it |
| `plan.md` | §21 | New must-item: usage log started |
| `plan.md` | §22.1 Q9 | Decided: not built |
| `plan.md` | Appendix A.1 | P2-10 description |
| `architecture.md` | Header | OD11 bullet |
| `architecture.md` | §2.2, §3 ADR-18 | Not guaranteed $0; status confirmed by OD11 |
| `architecture.md` | §6.4 | Billing split into the three categories; configurability bullet |
| `architecture.md` | §11.2, §16 R7, R15 | Size alert only; residual risk accepted |
| `architecture.md` | §18.2 item 16 | Referer check decided |
| ADR-0009 | Status, Consequences | Confirmed by OD11; usage record replaces the 2 GB stop; new "Owner clarification" block |
| `docs/free-tier-verification.md` | New §0; U-CF3 | Category table and accepted usage assumptions vs verified limits; the U-CF3 fallback is the monthly usage record |

**Deliberately kept:**
- All accurate warnings about Cloudflare billing: no hard cap, rounding up, failed payment makes buckets inaccessible, and the budget alert is informational and may exclude R2.
- Scoped tokens and private buckets.
- Upload caps (1 MB per object, 5 MB download cap, 200 per run), which prevent accidental bulk uploads.
- The kill procedure, the Workers Free failure mode, and the escape hatch (documented only, not built).
- The forecast and the G0 "under 25%" condition, now labelled as expected usage.

**Effort and calendar:** unchanged at 85.5 d / 102.6 d, with scenario A finishing 2027-06-06. Dropping the stop flag is too small to change the 1.0 d estimate for P2-10.

**Consistency re-check after OD11:**
- No "2 GB stop" or "stop flag" text remains in any document.
- No document claims a guaranteed $0.
- The Referer check is "not built" everywhere.
- No new provider, database or paid service was introduced.
- The [U] list (§6) is unchanged; those items remain the conditions of the owner's approval.

