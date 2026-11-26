// The bindings `env` from "cloudflare:test" carries (the dev environment of wrangler.jsonc).
declare namespace Cloudflare {
  interface Env {
    IMAGES: R2Bucket;
  }
}
