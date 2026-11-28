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
- **Alerts:** issues `[alert] <cinema>: <type>`; closed automatically by the next `ok` run.
- **Debug:** on failure, the `debug-<run id>` artifact holds the cleaned raw payloads
  (7 days).

### Switching from dev to production

1. Two clean dev runs recorded below (one manual, one scheduled).
2. Settings → Secrets and variables → Actions → Variables → `SCRAPE_ENVIRONMENT` = `production`.
3. Dispatch one manual run.
4. Vercel → `moviespk-api` → Environment Variables → `MONGODB_DB` = `moviespk` (it is
   `moviespk_dev` while the scraper writes to dev), then **Redeploy**. The API reads
   whichever database this names: with the wrong one, every list is empty (seen on
   2026-11-26). A redeploy also discards edge-cached responses of the old deployment.
5. Check `/api/v1/cinemas` and `/api/v1/movies?city=lahore` on the site.

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
| _pending (P1-21/P1-23)_ | That movie's poster loads from the Worker URL in a browser | |
