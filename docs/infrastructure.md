# Infrastructure record

Non-secret facts about every account and environment (plan P0-04, P0-12, Z1). **Never put
secret values here.** Update the "checked" date whenever a fact is re-verified (monthly
check, plan §18.2; P4-01 audit).

## Accounts

| Service | Account / project | Region | Payment method | Checked |
|---|---|---|---|---|
| GitHub | `<owner>/moviespk` (public) | — | none | _pending_ |
| MongoDB Atlas | project `moviespk`, free cluster | _pending (nearest to PK offered free)_ | none | _pending_ |
| Vercel Hobby | `moviespk-web` (root `web/`), `moviespk-api` (root `api/`, Express) | — | none | _pending_ |
| TMDB | API key (non-commercial) | — | none | _pending_ |
| Cloudflare | account (no zone, no domain) | — | **yes, R2 only** (OD9) | _pending (P0-12)_ |

Project contact email (Q6): _pending_.

## GitHub repository settings (P0-01, P0-03)

- [ ] Secret scanning and **push protection** enabled; a fake token pushed to a scratch
      branch is blocked (evidence link: _pending_).
- [ ] Default `GITHUB_TOKEN` permission: **read-only**.
- [ ] `main` protected: PR required; required checks `scraper-test`, `api-test`, `web-test`, `gitleaks`
      (plus `scraper-changes`, `api-changes`, `web-changes`).
      Jobs skipped by the `changes` gate report as passing, so path
      filtering does not block unrelated PRs.
- [ ] Dependabot alerts and version updates enabled.

## GitHub environments

| Environment | Secrets (names only) | Variables | Protection |
|---|---|---|---|
| `production` | `MONGODB_URI_SCRAPER`, `TMDB_API_KEY`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `CF_WORKERS_DEPLOY_TOKEN` | `MONGODB_DB=moviespk`, `R2_ACCOUNT_ID`, `R2_BUCKET=moviespk-prod` | _pending_ |
| `dev` | `MONGODB_URI_SCRAPER`, `TMDB_API_KEY`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | `MONGODB_DB=moviespk_dev`, `R2_ACCOUNT_ID`, `R2_BUCKET=moviespk-dev` | _pending_ |
| `images-approval` | **none** | **none** | required reviewer = owner; branches: `main` only |

Repository variable: `SCRAPER_USER_AGENT` = `MoviesPKBot/1.0 (+<repo URL>; <project email>)`.

## MongoDB users (plan §12.2)

| User | Role | Used by |
|---|---|---|
| scraper | readWrite on `moviespk` and `moviespk_dev` | GitHub Actions |
| api | read on `moviespk` | Vercel `moviespk-api` |

Network access `0.0.0.0/0` (dynamic runner and Vercel IPs); long random passwords.
Verify with `python scripts/check_db_access.py` (prints OK/FAIL only).

## Vercel

| Project | Env vars (names) | Production URL |
|---|---|---|
| `moviespk-api` | `MONGODB_URI_API`, `MONGODB_DB`, `CORS_ALLOWED_ORIGINS`, `LOG_LEVEL` | `https://moviespk-api.vercel.app` (_pending_) |
| `moviespk-web` | `API_ORIGIN`, `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_IMAGE_BASE`, `NEXT_PUBLIC_IMAGES_ENABLED` | _pending_ |

## Cloudflare (P0-12)

To be filled in P0-12: `workers.dev` subdomain, bucket names and privacy, budget alert,
token scopes, screenshots of Billing → Subscriptions and Workers & Pages → Plans.
