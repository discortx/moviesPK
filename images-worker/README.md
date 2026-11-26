# images-worker (`moviespk-img`)

Serves movie posters from a **private** Cloudflare R2 bucket on the account's free
`workers.dev` subdomain (plan §11.3.2, ADR-0009). No zone, no custom domain, no secrets:
the R2 binding in `wrangler.jsonc` is the only access, one bucket per environment.

| Environment | Worker             | Bucket          | Deploy                                                  |
| ----------- | ------------------ | --------------- | ------------------------------------------------------- |
| production  | `moviespk-img`     | `moviespk-prod` | `deploy-images-worker.yml` after owner approval (P1-20) |
| dev         | `moviespk-img-dev` | `moviespk-dev`  | `deploy-images-worker.yml`, automatically (P1-20)       |

URLs: `https://moviespk-img.moviespk.workers.dev/img/movies/<movieId>/poster-<hash8>-w<185|342|780>.webp`
(dev: `moviespk-img-dev.moviespk.workers.dev`). The web reads the base only from
`NEXT_PUBLIC_IMAGE_BASE`.

## Develop

```sh
npm ci
npm run lint && npm run typecheck && npm test   # tests run inside workerd, R2 simulated locally
npm run check:deploy                            # wrangler dry-run for both environments
npm run dev                                     # local Worker against a local (empty) dev bucket
```

- Tests use `@cloudflare/vitest-plugin` (the renamed `@cloudflare/vitest-pool-workers`,
  which is deprecated) with `remoteBindings: false`: they never reach Cloudflare.
  Workers Caching is not exercised locally; P1-21 tests it on the deployed dev Worker.
- `wrangler` is pinned exactly; `@cloudflare/vitest-plugin` 1.8.0 bundles the same
  version. Update both together.
- Deploy production with `--env=""` (explicit top-level environment), never without a
  flag. Real deploys happen only in CI (P1-20); nobody deploys from a laptop.
- `send_metrics: false` turns off Wrangler's usage telemetry for this project.
