import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

// Tests run inside workerd (the Workers runtime) with the `dev` environment's bindings,
// simulated locally by Miniflare. remoteBindings stays off: tests never reach Cloudflare.
// Workers Caching is not exercised locally (plan §11.3.2); P1-21 tests it on the deployed
// dev Worker.
export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.jsonc", environment: "dev" },
      remoteBindings: false,
    }),
  ],
  test: {
    include: ["test/**/*.test.ts"],
  },
});
