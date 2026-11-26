# MoviesPK runbook

Operating procedures and live observations (plan §18). Never paste secrets, URIs or tokens
here.

## Scrape workflows

### `scrape-full` (plan §10.5, P1-13)

- **Schedule:** `7 2,14 * * *` UTC (07:07 and 19:07 PKT). GitHub may start scheduled runs
  late or skip a slot when Actions is busy (seen on 2026-11-26: the first slot after the
  workflow was added never ran). If a slot is missing, disable and re-enable the workflow
  (Actions → scrape-full → ··· ), or dispatch a run by hand.
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
3. Dispatch one manual run; check `/api/v1/...` on the site afterwards.

## Live observations (P1-13 acceptance)

| Date (UTC) | Check | Run | Result |
|---|---|---|---|
| 2026-11-25 19:52 | Manual dispatch writes to dev (`scrape_runs` ok, showtimes in `moviespk_dev`) | scrape-full #1 (`main` 63f3afc), 28 s | **OK**: `moviespk_dev` has cinemas 5, movies 8, showtimes 19, scrape_runs 1, movie_aliases 7 (TMDB matched 7 of 8 titles). Spot check: Belkis, Screen 4, `startsAt` 2026-11-26T08:00Z (13:00 PKT), `endsAt` +85 min, `expireAt` +7 d, booking URL present. |
| 2026-11-26 02:07 | Scheduled slot (first after the workflow was added at 19:37 UTC) | — | **Skipped by GitHub**: no run created (checked 08:15 UTC via the REST API; workflow `active`). Scheduled events are best-effort and may be dropped under load. Workflow disabled and re-enabled to re-register the schedule. |
| _pending_ | A scheduled run fired on its own (note the delay after 02:07 / 14:07 UTC) | | |
| _pending_ | Forced adapter failure: red run, one `[alert]` issue, GitHub failure email | | |
| _pending_ | Recovery: next ok run closes the issue | | |
