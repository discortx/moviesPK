# MoviesPK

A **personal, non-commercial** website that shows which movies are playing at cinemas
near you in Pakistan: showtimes (PKT) and, where a cinema publishes it cheaply and
allows it, a seat-status category. Data is collected automatically from cinema
websites twice a day.

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

## No secrets in git

Secrets live only in GitHub environments and Vercel project settings. `.env*` files are
ignored except `.env.example`, which lists names only. `pre-commit` runs gitleaks on every
commit, and GitHub push protection is enabled on the repository.

## Licence

Code: MIT (see [`LICENSE`](LICENSE)). **Scraped data, TMDB data and poster images are not
covered by this licence**; they belong to their respective owners.
