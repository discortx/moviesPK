# Local development setup

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.12 or newer | CI runs 3.12 |
| Node.js | see `.nvmrc` (24 LTS) | `engines` requires 22 or newer |
| MongoDB | 7 | Docker (`docker compose up mongo`) **or** a native MongoDB Community install / Podman. Docker Desktop is free only for personal/educational use: confirm it fits before using it (plan §6.2). |
| pre-commit | latest | `pip install pre-commit && pre-commit install` |

Copy `.env.example` to `.env` and fill in values. Never commit `.env`.

## Scraper

```sh
cd scraper
python -m venv .venv
.venv/Scripts/activate          # Windows; use `source .venv/bin/activate` elsewhere
pip install -e ".[dev]"
ruff check . && mypy && pytest
python -m moviespk_scraper --help
```

Integration tests (`pytest -m integration`) need MongoDB at `MONGODB_URI_SCRAPER`
(default `mongodb://localhost:27017`); they are skipped when it is unreachable.

## API

```sh
cd api
npm ci
npm run lint && npm run typecheck && npm test
npm run dev                     # http://localhost:4000/api/v1/health
```

## Web

```sh
cd web
npm ci
npm run lint && npm run typecheck && npm test
npm run dev                     # http://localhost:3000
```

Next.js 16 note: `cacheComponents` is deliberately **off** because the plan's ISR design
uses the `revalidate` and `dynamicParams` segment configs, which Cache Components removes.
Next.js has announced that Cache Components becomes the default in the next major
version; that upgrade needs a re-plan of §9.3 rendering.

## Shared contract and scripts

```sh
python scripts/gen_constants.py          # regenerate shared/constants/cities.json
python scripts/gen_constants.py --check  # CI: fails if cities.json is stale
node scripts/create_indexes.js           # idempotent; uses MONGODB_URI_SCRAPER / MONGODB_DB
python scripts/seed_dev.py               # seeds moviespk_dev
```

## Windows gotcha: drive-letter case

If Vitest reports *"failed to find the current suite"*, your shell's working directory
uses a lower-case drive letter (`e:\...`) while Node resolves `E:\...`, so Vitest loads two
copies of itself. `cd` using the upper-case drive letter (`cd E:\moviesPK\web`) and re-run.
CI (Linux) is unaffected.
