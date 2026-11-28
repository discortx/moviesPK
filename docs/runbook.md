# MoviesPK runbook

Operating procedures and live observations (plan §18). Never paste secrets, URIs or tokens
here.

## Scrape workflows

### `scrape-full` (plan §10.5, P1-13)

- **Schedule:** `7 * * * *` UTC (hourly at :07; twice a day until 2026-11-26, every 3 hours until 2026-11-28). Between 2026-11-26 16:20 and 2026-11-28 10:38 UTC GitHub delivered only 4 of about 13 three-hourly slots (all 4 runs succeeded). GitHub may start scheduled runs
  late or, rarely, skip them when Actions is busy.
- **Manual run:** Actions → scrape-full → Run workflow. Inputs: `cinema` (one cinema id,
  optional) and `dry_run` (fetch and check only; nothing written, no issues posted).
- **Environment:** repository variable `SCRAPE_ENVIRONMENT` = `dev` (default) or
  `production`. It selects the GitHub environment, so the run uses that environment's
  `MONGODB_URI_SCRAPER`, `MONGODB_DB` and `TMDB_API_KEY`.
- **Concurrency:** group `scrape`, shared with `scrape-seats`; runs queue, never overlap.
- **Exit code:** 1 when any cinema is `failed`, `blocked` or `drift` → the run is red and
  GitHub emails the user who last edited the cron line.
- **Alerts:** issues `[alert] <cinema>: <type>`; closed automatically by the next `ok` run. The canary adds its own alert types and a daily digest (below).
- **Debug:** on failure, the `debug-<run id>` artifact holds the cleaned raw payloads
  (7 days).

### `scrape-canary` (plan §10.5, P2-03)

- **Schedule:** `23 4 * * *` UTC (09:23 PKT), daily. Manual: Actions → scrape-canary → Run
  workflow (`dry_run` checks everything, writes nothing, posts no issues). Same
  `SCRAPE_ENVIRONMENT`, environment secrets and `scrape` concurrency group as `scrape-full`.
- **Local dry run:** `python -m moviespk_scraper run --job canary --dry-run` (reads the
  database only when `MONGODB_URI_SCRAPER` and `MONGODB_DB` are set).
- **Exit code:** 1 only when a check could not run (database unreachable, a maintenance
  hook crashed). Findings are issues, not red runs.
- **Run record:** one `scrape_runs` document with `job: canary`, `cinemaId: canary`,
  findings in `errors` and the Atlas size in `storageBytes`.

| Issue | Meaning | What to do | Closes |
|---|---|---|---|
| `[alert] <cinema>: robots` | robots.txt now disallows an evidence path that was Allowed. The scraper already refuses it. | Re-run `scripts/snapshot_evidence.py` for the cinema. Disallowed → set `enabled: false` (or obtain written permission); otherwise update the `evidence` block. | automatically, once robots allows the paths again |
| `[alert] <cinema>: terms-changed` | The terms page text changed since `checked_at`. Scraping continues. | Read the new terms. Fine → re-run `snapshot_evidence.py` and update `terms_sha256` and `checked_at`. Not fine → `enabled: false`. | automatically, once the hash in `cinemas.yml` matches |
| `[alert] adapter-<id>: probe` | The adapter's known page no longer parses (site redesign or hijacked domain). | As for `drift`: look at the `canary-debug-<run>` artifact, fix the adapter and its fixtures. | on the next clean probe |
| `[alert] <cinema>: low-results` | The latest `ok` full run found under 50% of the median of the 7 `ok` runs before it (needs 8 runs). | Compare with the cinema's website; an off-season dip is fine, a half-parsed page is drift. | when the count recovers |
| `[alert] <cinema>: stale` / `stale-seats` | No successful `full` run in 18 h (`seats`: 6 h). | Check the `scrape-full` runs: missed schedules, failures, blocked. | after the next success |
| `[alert] atlas: storage` | Data + indexes above 70% of 512 MB. | Check `showtimes` TTL and `scrape_runs` TTL indexes; see `docs/capacity.md`. | below 70% |
| `[digest] unmatched titles <date>` | Provisional and unmatched titles created in the last 24 h. | [Alias review](#alias-review-weekly-p2-04). | after 7 days |

robots and terms alerts are posted once per change and never repeated: an open one means
an unreviewed change. A robots.txt change that alters no verdict is only logged.

### `keepalive` and `export` (plan §10.5, P2-05, P2-06)

- **keepalive:** `53 5 1 * *` UTC (the 1st of each month) or Actions → keepalive → Run
  workflow. Re-enables every scheduled workflow (`scrape-full`, `scrape-canary`, `export`, `healthcheck`,
  `keepalive`) and opens `[maintenance] YYYY-MM` for the owner, with the monthly checklist
  (plan §18.2) and a table of the enable results. A second run in the same month comments
  on that issue. Red only when a workflow could not be enabled.
- **Monthly:** work through the issue, make the **human maintenance commit** (a merged
  Dependabot PR, a fixture refresh, or a line in the maintenance log below), close the
  issue. Never automate the commit.
- **export:** see [Restore from export](#restore-from-export-p2-05-plan-173-19).

### `healthcheck` (plan §10.5, §18.1, P2-08)

- **Schedule:** `17 * * * *` UTC (hourly) or Actions → healthcheck → Run workflow.
- **Checks:** the site home page and `/api/v1/health` (database `ok`) → issue
  `[alert] site: down`; one current poster (the first `poster.key` in today's Lahore list,
  `<image base>/img/<key>-w342.webp`, expects `200 image/webp`) → `[alert] images: down`.
  No poster in today's list → skipped. Error 1027 is named in the issue: the Workers Free
  daily limit (100,000 requests), which resets 00:00 UTC; nothing is billed.
- **Two failures:** a failing check is retried after 2 minutes in the same run; only a
  second failure alerts (and makes the run red). A passing check closes its issue.
- **Image base** follows `SCRAPE_ENVIRONMENT`: `moviespk-img-dev` while the API reads the
  dev database, `moviespk-img` after the switch to production.
- **Test dispatch:** `site_url` = `https://moviespk-web.vercel.app/nonexistent` or
  `image_base` = `https://moviespk-img-dev.moviespk.workers.dev/nonexistent` opens the
  matching issue; a normal dispatch afterwards closes it.

### Switching from dev to production

1. Two clean dev runs recorded below (one manual, one scheduled).
2. Settings → Secrets and variables → Actions → Variables → `SCRAPE_ENVIRONMENT` = `production`.
3. Dispatch one manual run.
4. Vercel → `moviespk-api` → Environment Variables → `MONGODB_DB` = `moviespk` (it is
   `moviespk_dev` while the scraper writes to dev), then **Redeploy**. The API reads
   whichever database this names: with the wrong one, every list is empty (seen on
   2026-11-26). A redeploy also discards edge-cached responses of the old deployment.
5. Check `/api/v1/cinemas` and `/api/v1/movies?city=lahore` on the site.

## Alias review (weekly, P2-04)

Titles the matcher could not settle: TMDB suggestions with a score of 70-89 (`pending`)
and `unmatched` movies that still have upcoming shows. The daily `[digest]` issue lists the
new ones; review weekly, or sooner when a digest names a film that is clearly mis-shown.

1. With the environment's database URI and a TMDB key in the shell (never in a file):
   `python scripts/review_aliases.py` from the repository root, with the scraper's virtual
   environment active (`--list` only lists). It reads
   `MONGODB_URI_SCRAPER`, `MONGODB_DB` and `TMDB_API_KEY`, and writes nothing but
   `scraper/config/aliases.yml`.
2. For each title: type the number of the right TMDB candidate, `t <id>` for a TMDB id you
   looked up, `l <localKey>` to join it to a movie already on the site (the slug in its
   URL; e.g. the same film listed with and without a year), `s` to skip, `q` to stop.
   Without `TMDB_API_KEY` there are no candidates; `t` and `l` still work.
3. The tool validates the file (as every run does) and leaves it untouched on any problem.
   Check `git diff scraper/config/aliases.yml`, then open a PR.
4. After merge the next `full` run uses the alias: the movie gains its TMDB data and the
   existing showtimes move to the new ids (no duplicates; `relinked` in the `upsert.done`
   log line). Posters follow in the same run.

One alias without the database: `python scripts/review_aliases.py --add "<alias>"
--tmdb-id <id> --note "<why>"` (or `--local-key`, optional `--cinema-id`). The alias is the
normalized title as the digest shows it: lowercase, punctuation as spaces.

A wrong alias: point the entry at the right film (or local movie) and merge; the next run
re-links again. Deleting the entry does not undo a TMDB match (a matched movie is never
downgraded), so correct it rather than delete it. An alias never moves showtimes away from
a `matched` movie.

## Restore from export (P2-05, plan §17.3, §19)

The `export` workflow (Sundays 03:41 UTC, or Actions → export → Run workflow) keeps
`movies`, `movie_aliases` and `cinemas` as an artifact `export-<db>-<run id>` for 60 days:
three `*.json.gz` files and `manifest.json` (counts, checksums, schema version). Showtimes
are not exported: one `full` run brings them back. Everything human-curated is in git
anyway (cinemas, coordinates, aliases); the export saves the TMDB matches, slugs and
`movie_aliases` history, so URLs stay the same after a restore.

1. Actions → export → the latest green run → download the artifact and unzip it into a
   new, empty directory (e.g. `restore/`).
2. With the target cluster's URI in the shell only (`MONGODB_URI_SCRAPER`) and the
   scraper's virtual environment active, from the repository root:

   ```
   python scripts/restore_export.py --input restore --target-db moviespk_restore_test
   ```

   For the production database after a loss (§17.3) the same command with
   `--target-db moviespk --force`; without `--force` it is refused.
3. The script first validates the whole export (manifest and schema version, all three
   files, gzip, JSON, checksums, counts). Any problem: exit 1, a message, and nothing
   written. Then it replaces the three collections, prints the counts and runs
   `scripts/create_indexes.js` (or prints that command when Node.js is missing). It never
   prints the connection string.
4. Dispatch `scrape-full` against the restored database (showtimes), then check
   `/api/v1/movies?city=lahore`.

Drill log (repeat quarterly and in P4-05):

| Date (UTC) | Export run | Target | Counts (movies / aliases / cinemas) | Result |
|---|---|---|---|---|
| 2026-11-28 15:00 | dev export of 14:57 (artifact) | local MongoDB 7, `moviespk_restore_test` | 28 / 24 / 5 (= manifest) | OK. Validated, restored, indexes created; `--target-db moviespk` without `--force` refused. One live `full` run into it (no TMDB key): 5 cinemas `ok`, 155 showtimes, still 28 movies (no duplicates; 54 of 60 listings matched through the restored aliases alone), no orphan showtimes. Local API on it: `/health` ok, 5 cinemas, Lahore 14 / Karachi 5 / Islamabad 2 films today; `sanjog-2026` same slug and poster as before. |

## Blocked site (P2-07, plan §2.3, R3)

A `[alert] <cinema>: blocked` issue means robots.txt refuses a path we need, robots.txt is
unreachable, or the site answers 403/429 repeatedly. **Never** a proxy, VPS, IP rotation or
browser spoofing, and a robots refusal is never routed around (D17).

1. Read the alert: a robots refusal → re-run `scripts/snapshot_evidence.py`; if the path is
   now Disallowed, go straight to step 4.
2. Polite changes, one PR: a larger `min_delay_ms` in `cinemas.yml`; another endpoint that
   robots allows (with new evidence); fewer requests per run.
3. Watch the next runs. After 3 blocked runs in a row the alert gains a comment ending in
   "Blocked 3 runs in a row" (state `...:drop`).
4. Still blocked after 3 runs: drop it. `enabled: false` in `cinemas.yml` with a comment
   giving the reason and date; record it in the cinema's investigation document and in
   `docs/cinema-investigation/README.md` (Scope column: Dropped); merge. Its showtimes
   stop being refreshed and are cancelled or expire within 7 days; to remove them at once,
   purge (below).

## Purge one cinema's data (P2-07a, plan §12.5, §17.3, §18.4)

```
python scripts/purge_cinema.py --cinema <id> (--showtimes | --all) [--dry-run] [--yes]
```

From the repository root, the scraper's virtual environment active, `MONGODB_URI_SCRAPER`
and `MONGODB_DB` in the shell only (never printed).

- `--showtimes`: only the cinema's showtimes. Rollback of bad data (§17.3):
  `git revert`, then `python scripts/purge_cinema.py --cinema <id> --showtimes`, then
  dispatch `scrape-full` with `cinema: <id>`.
- `--all`: also the cinema document, its `scrape_runs` and its cinema-specific `auto` and
  `pending` aliases. Removal request (§18.4): first merge `enabled: false`, then
  `python scripts/purge_cinema.py --cinema <id> --all`. Refused while `cinemas.yml` still
  says `enabled: true`.
- Never touched: `movies`, `manual` aliases, R2 objects, other cinemas.
- Every run prints the counts it would delete; `--dry-run` stops there. Otherwise re-type
  the cinema id (or pass `--yes`); anything else aborts with nothing deleted. Exit codes:
  0 done, 1 aborted, 2 invalid or refused. Record the run in the related issue.

## Maintenance log (monthly human commit, P2-06)

| Month | By | What |
|---|---|---|
| 2026-11 | owner | P2-06 evidence and this log (closes #73) |

## Live observations (P1-13 acceptance)

| Date (UTC) | Check | Run | Result |
|---|---|---|---|
| _pending_ | Manual dispatch writes to dev (`scrape_runs` ok, showtimes in `moviespk_dev`) | | |
| 2026-11-26 10:43 | A scheduled run fired on its own (note the delay after 02:07 / 14:07 UTC) | scrape-full #6 (event `schedule`, `main` 2d2aac4), 46 s | **OK, late**: green; created 10:43:52 UTC, i.e. the 02:07 slot delivered **8 h 36 min late** (after the workflow was disabled and re-enabled at about 08:20). The 14:07 slot had not fired by 14:44 UTC. GitHub's scheduler is unreliable here; the canary staleness alert (full over 18 h, P2) is the safety net. |
| 2026-11-26 14:07 | Scheduled slot | — | **Not run**: no run by 16:08 UTC (second slot in a row not run on time). |
| 2026-11-26 08:25 | Forced adapter failure: red run, one `[alert]` issue, GitHub failure email | scrape-full #3 (branch `test/forced-failure`: Packages Mall pointed at the non-existent branch `0000000099`) | **OK**: `[failed] … zero result: no valid showtimes`, exit code 1 (red), issue #34 `[alert] cinepax-packages-mall: failed` created, GitHub failure email received. |
| 2026-11-26 08:33 | Recovery: next ok run closes the issue | scrape-full #5 (`main` 2d2aac4), 45 s | **OK**: green; issue #34 closed (completed) with "Recovered: `cinepax-packages-mall` ran `ok` at 2026-11-26T08:33:12Z". (Run #4 also failed because the test branch had been merged into `main` by mistake, PR #33; reverted before #5.) |

### Forcing a failure safely

Use a throwaway branch and **dispatch the workflow on that branch** (Run workflow → "Use
workflow from"). Never open a pull request for it: GitHub offers "Compare & pull request"
after the push, and merging it breaks the scheduled runs on `main` (happened once, PR #33,
reverted). Delete the branch afterwards.

## End-to-end demo (P1-17)

| Date (UTC) | Check | Result |
|---|---|---|
| 2026-11-26 16:08 | A real first-cinema showtime through the production API | **OK**: `https://moviespk-api.vercel.app/api/v1/movies/belkis-2026/showtimes?city=lahore&date=2026-11-27` → Cinepax Packages Mall, 27 Nov 23:00 PKT, Screen 4, booking link (dev data). |
| 2026-11-26 17:03 | README quickstart run end to end on Windows | **OK**: `npm run mongo:dev` → indexes → real scrape of Packages Mall (1 ok) → local API (`db: ok`, 4 movies tomorrow) → local web lists the cities and its `/api` rewrite reaches the local API. |
| 2026-11-28 12:29 | A real showtime and its poster in a browser | **OK** (owner): `https://moviespk-api.vercel.app/api/v1/movies/hexed-2026/showtimes?city=lahore&date=2026-11-29` → Hexed at Cinepax Packages Mall 29 Nov 13:15 and 15:00 PKT, `posterKey` `movies/6b08dedf90bcf1349ae4a3f0/poster-84b7da34`; `https://moviespk-img-dev.moviespk.workers.dev/img/movies/6b08dedf90bcf1349ae4a3f0/poster-84b7da34-w342.webp` shows the poster. (Dev data: the scraper still writes to `moviespk_dev`/`moviespk-dev`, so the dev Worker serves the posters until the production switch.) |

## Gate G1 review (plan §14)

| Criterion | Status | Evidence |
|---|---|---|
| `scrape-full` schedule ran unattended at least twice | **Met** | 5 scheduled runs, all success (#6-#10, 2026-11-26 10:43 → 2026-11-28 03:11 UTC); delivery by GitHub is irregular (see the schedule note above) |
| Idempotency test green | **Met** | `scraper/tests/integration/test_upsert.py::test_running_the_fixture_pipeline_twice_is_identical`, in `ci-scraper` |
| A forced zero-result opens exactly one issue and changes no data | **Met** | scrape-full #3 (2026-11-26) → issue #34, closed by #5; a failed run writes only `scrape_runs` (`test_reconcile.py` proves no showtime changes) |
| A forced failure opens exactly one issue and changes no data | **Met** (2026-11-28) | scrape-full #12 on throwaway branch `test/forced-blocked` (Packages Mall pointed at `https://web.cinepax.invalid`): robots.txt `ConnectError` → `disallow_all` → `[blocked]`, 0 rows, exit 1, issue #61 `[alert] cinepax-packages-mall: blocked` (labels `alert`, `alert:blocked`); the 13 visible showtimes were identical before (12:38) and after (12:45); recovery #13 on `main` closed #61 with "Recovered" at 12:46:39 UTC. Branch deleted. |
| `/api/v1/movies/:slug/showtimes` via `https://moviespk-web.vercel.app/api/v1/...`: correct PKT day, edge HIT on the second request | **Met** (2026-11-28 12:37 UTC) | `hexed-2026`, `date=2026-11-29`: MISS then HIT; both shows (13:15, 15:00 PKT) on 2026-11-29 |
| A first-cinema poster loads from the Worker URL with `Cf-Cache-Status: HIT` on the second request | **Met** | P1-21, `docs/performance.md` §3 |

**G1 decision: PASSED, 2026-11-28.** Every criterion is met on the dev database and the
dev bucket. Carried forward: GitHub's scheduler delivers only part of the hourly slots
(the canary staleness alert in P2 is the safety net); the API cold start is a recorded
risk (`docs/performance.md` §1); production switch-over steps are in "Switching from dev
to production" above.

