# Offline fixtures

One directory per cinema and capture date: `<cinema-id>/<YYYY-MM-DD>/`, holding
`manifest.json` (URL → status, headers, body file) and the bodies. Format:
`scraper/src/moviespk_scraper/core/offline.py`. Replay with
`python -m moviespk_scraper run --job full --cinema <id> --dry-run --offline <dir>`.

## Capture or refresh (plan P1-05)

```powershell
$env:SCRAPER_USER_AGENT = "MoviesPKBot/1.0 (+https://github.com/discortx/moviesPK; <contact email>)"
scraper\.venv\Scripts\python scripts\capture_fixture.py --cinema <cinema-id>
```

- It fetches through the real client: robots.txt is enforced and requests are throttled.
- It keeps only `content-type`, `etag` and `last-modified` headers (never cookies),
  replaces credential-like JSON values and hidden HTML form tokens with `REDACTED`, and
  refuses URLs with token-like query parameters. **Review the diff before committing.**
- A refresh adds a new dated directory. Keep older directories that tests still use;
  delete the rest in the same PR.
- The paths captured per adapter are in `CAPTURE_PATHS` in `scripts/capture_fixture.py`
  (override with `--path`).

## Current fixtures

| Cinema | Date | Notes |
|---|---|---|
| `cinepax-packages-mall` | 2026-11-25 | First cinema (P1-06): 8 movies, 19 shows |
| `cinepax-world-trade-center` | 2026-11-25 | 4 movies, 12 shows |
| `cinepax-ocean-mall` | 2026-11-25 | 9 movies, 33 shows; **after-midnight case**: *Resident Evil* at `2026-11-28T00:15`, `businessDate` 2026-11-27, `calendarDate` 2026-11-28, `lateNight: true` |

These are copies of public listings, kept only as test input (no posters or images).
