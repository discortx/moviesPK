# MoviesPK

A **personal, non-commercial** website that shows which movies are playing at cinemas
near you in Pakistan: showtimes (PKT) and, where a cinema publishes it cheaply and
allows it, a seat-status category. Data is collected automatically from cinema
websites every 3 hours.

- No ads, affiliate links, paid features or revenue of any kind (plan OD5).
- The scraper respects each site's `robots.txt` (ADR-0001).
- Movie metadata and posters come from TMDB. *This product uses the TMDB API but is
  not endorsed or certified by TMDB.*

## Repository layout

| Folder | Contents |
|---|---|
| `scraper/` | Python 3.12+ scraper (GitHub Actions) |
| `api/` | Read-only Express REST API (Vercel Function) |
| `web/` | Next.js website (Vercel) |
| `images-worker/` | Cloudflare Worker serving posters from a private R2 bucket |
| `shared/` | JSON Schemas, constants and contract fixtures shared by every package |
| `scripts/` | Operational scripts (indexes, seed, constants generation, evidence) |
| `docs/` | Plan evidence, ADRs, runbooks |

Design documents: [`plan.md`](plan.md) (source of truth), [`architecture.md`](architecture.md),
[`project_statement.md`](project_statement.md). Local setup: [`docs/dev-setup.md`](docs/dev-setup.md).

## Quickstart: the whole stack on your machine

Runs the real pipeline locally: a scrape of the first cinema → local MongoDB → API →
website. Prerequisites, tests and tooling details: [`docs/dev-setup.md`](docs/dev-setup.md).
Commands are for PowerShell; on macOS/Linux use `export NAME=value` and `/` paths.

**1. Install** (once)

```powershell
cd scraper; python -m venv .venv; .venv\Scripts\pip install -e ".[dev]"; cd ..
cd api; npm ci; cd ..
cd web; npm ci; cd ..
npm ci --prefix scripts
```

**2. Start a local MongoDB** (terminal 1; keep it open). Without Docker:

```powershell
cd api; npm run mongo:dev        # in-memory MongoDB 7 on 127.0.0.1:27017; data is lost on stop
```

With Docker instead: `docker compose up mongo`.

**3. Fill the database** (terminal 2)

```powershell
$env:MONGODB_URI_SCRAPER = "mongodb://127.0.0.1:27017"; $env:MONGODB_DB = "moviespk_dev"
$env:SCRAPER_USER_AGENT = "MoviesPKBot/1.0 (+https://github.com/discortx/moviesPK; <your email>)"
node scripts/create_indexes.js
scraper\.venv\Scripts\python -m moviespk_scraper run --job full --cinema cinepax-packages-mall
```

This makes one real, robots-checked request to Cinepax. To stay offline, run
`scraper\.venv\Scripts\python scripts\seed_dev.py` instead (sample data). Add
`$env:TMDB_API_KEY = "..."` before the scrape to match movies against TMDB; without it,
movies stay unmatched. `--dry-run --offline scraper	estsixtures\<cinema>\<date>`
replays a saved capture and writes nothing.

**4. Start the API** (terminal 3)

```powershell
cd api; $env:MONGODB_URI_API = "mongodb://127.0.0.1:27017"; $env:MONGODB_DB = "moviespk_dev"; npm run dev
```

Try <http://localhost:4000/api/v1/health> (`"db":"ok"`) and
`http://localhost:4000/api/v1/movies?city=lahore&date=<tomorrow, YYYY-MM-DD>`.

**5. Start the website** (terminal 4)

```powershell
cd web; $env:API_ORIGIN = "http://localhost:4000"; npm run dev
```

Open <http://localhost:3000>: the home page lists the cities from the API, and
<http://localhost:3000/api/v1/health> goes through the same `/api/*` rewrite as production.

The poster Worker (`wrangler dev`) joins this list with P1-18. Operating the production
workflows: [`docs/runbook.md`](docs/runbook.md).

## No secrets in git

Secrets live only in GitHub environments and Vercel project settings. `.env*` files are
ignored except `.env.example`, which lists names only. `pre-commit` runs gitleaks on every
commit, and GitHub push protection is enabled on the repository.

## Licence

Code: MIT (see [`LICENSE`](LICENSE)). **Scraped data, TMDB data and poster images are not
covered by this licence**; they belong to their respective owners.
