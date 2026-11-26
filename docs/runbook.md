# MoviesPK runbook

Operating procedures and live observations (plan §18). Never paste secrets, URIs or tokens
here.

## Scrape workflows

### `scrape-full` (plan §10.5, P1-13)

- **Schedule:** `7 2,14 * * *` UTC (07:07 and 19:07 PKT). GitHub may start scheduled runs
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
3. Dispatch one manual run; check `/api/v1/...` on the site afterwards.

## Live observations (P1-13 acceptance)

| Date (UTC) | Check | Run | Result |
|---|---|---|---|
| _pending_ | Manual dispatch writes to dev (`scrape_runs` ok, showtimes in `moviespk_dev`) | | |
| _pending_ | A scheduled run fired on its own (note the delay after 02:07 / 14:07 UTC) | | |
| _pending_ | Forced adapter failure: red run, one `[alert]` issue, GitHub failure email | | |
| _pending_ | Recovery: next ok run closes the issue | | |
