# Infrastructure record

Non-secret facts about every account and environment (plan P0-04, P0-12, Z1). **Never put
secret values here.** Update the "checked" date whenever a fact is re-verified (monthly
check, plan §18.2; P4-01 audit).

## Accounts

| Service | Account / project | Region | Payment method | Checked |
|---|---|---|---|---|
| GitHub | `discortx/moviesPK` (public) | — | none (_owner to confirm_) | _pending_ |
| MongoDB Atlas | project `moviespk`, free cluster | Mumbai | none (no card asked at sign-up) | 2026-11-25 |
| Vercel Hobby | `moviespk-web` (root `web/`), `moviespk-api` (root `api/`, Express) | functions: set to `bom1` (Mumbai) to match Atlas | none | 2026-11-25 |
| TMDB | API key (non-commercial) | — | none | 2026-11-25 |
| Cloudflare | account (no zone, no domain) | — | **yes, R2 only** (OD9) | 2026-11-25 |

Project contact email (Q6): `kalime5891@gmail.com` (owner-approved for publication 2026-11-25).

## GitHub repository settings (P0-01, P0-03)

- [x] Secret scanning and **push protection** enabled; a fake token pushed to a scratch
      branch is blocked (owner test 2026-11-25).
- [ ] Default `GITHUB_TOKEN` permission: **read-only**.
- [x] `main` protected: PR required; required checks `scraper-test`, `api-test`, `web-test`, `gitleaks`
      (plus `scraper-changes`, `api-changes`, `web-changes`).
      Jobs skipped by the `changes` gate report as passing, so path
      filtering does not block unrelated PRs.
- [x] Dependabot alerts and version updates enabled.

## GitHub environments

| Environment | Secrets (names only) | Variables | Protection |
|---|---|---|---|
| `production` | `MONGODB_URI_SCRAPER`, `TMDB_API_KEY`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `CF_WORKERS_DEPLOY_TOKEN` | `MONGODB_DB=moviespk`, `R2_ACCOUNT_ID`, `R2_BUCKET=moviespk-prod` | _pending_ |
| `dev` | `MONGODB_URI_SCRAPER`, `TMDB_API_KEY`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | `MONGODB_DB=moviespk_dev`, `R2_ACCOUNT_ID`, `R2_BUCKET=moviespk-dev` | _pending_ |
| `images-approval` | **none** | **none** | required reviewer = owner; branches: `main` only |

Repository variable: `SCRAPER_USER_AGENT` = `MoviesPKBot/1.0 (+https://github.com/discortx/moviesPK; kalime5891@gmail.com)`.

## MongoDB users (plan §12.2)

| User | Role | Used by |
|---|---|---|
| scraper | readWrite on `moviespk` and `moviespk_dev` | GitHub Actions |
| api | read on `moviespk` | Vercel `moviespk-api` |

Network access `0.0.0.0/0` (dynamic runner and Vercel IPs); long random passwords.
Verify with `python scripts/check_db_access.py` (prints OK/FAIL only).

| Check (P0-04) | Result | Date | Evidence |
|---|---|---|---|
| scraper user can write to `moviespk_dev` from GitHub Actions | OK | 2026-11-25 | throwaway run `probe-g0`, job `db` (environment `dev`) |
| api user is read-only (write rejected) | OK | 2026-11-25 | `check_db_access.py` run locally by the owner |
| dev R2 token lists `moviespk-dev`, gets AccessDenied on `moviespk-prod` | OK | 2026-11-25 | throwaway run `probe-g0`, job `r2` (P0-12 test) |
| job in `images-approval` runs after the owner's approval | OK: the job paused until the owner approved it | 2026-11-25 | throwaway run `probe-g0`, job `approval` |

## Vercel

| Project | Env vars (names) | Production URL |
|---|---|---|
| `moviespk-api` | `MONGODB_URI_API`, `MONGODB_DB`, `CORS_ALLOWED_ORIGINS`, `LOG_LEVEL` | `https://moviespk-api.vercel.app` (checked 2026-11-25) |
| `moviespk-web` | `API_ORIGIN`, `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_IMAGE_BASE`, `NEXT_PUBLIC_IMAGES_ENABLED` | `https://moviespk-web.vercel.app` (checked 2026-11-25); `API_ORIGIN=https://moviespk-api.vercel.app` |

## Cloudflare (P0-12)

Owner-checked 2026-11-25.

| Fact | Value |
|---|---|
| Subscriptions (Billing → Subscriptions) | **R2 only** |
| Workers plan (Workers & Pages → Plans) | **Free** |
| `workers.dev` subdomain | created: `<account-subdomain>.workers.dev` (_name to record_) |
| Buckets | `moviespk-prod`, `moviespk-dev`: **private** (no `r2.dev`, no custom domain, no CORS) |
| Budget alert | $1 to the owner's email; **includes R2** (resolves U-CF3) |
| R2 tokens | `moviespk-scraper-prod` (Object Read & Write, `moviespk-prod` only) → env `production`; `moviespk-scraper-dev` (`moviespk-dev` only) → env `dev`. Dev token denied on prod: tested 2026-11-25 |
| Deploy token | `CF_WORKERS_DEPLOY_TOKEN`: Workers Scripts Write, this account only, no zones, no R2 → env `production` |
