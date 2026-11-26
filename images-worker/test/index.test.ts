import { env, SELF } from "cloudflare:test";
import { describe, expect, it } from "vitest";

// P1-18 smoke tests: the Worker runs inside workerd with its R2 binding (local, simulated).
describe("moviespk-img scaffold", () => {
  it("answers 404 with a short cache lifetime", async () => {
    const res = await SELF.fetch("https://moviespk-img.example/img/movies/x");
    expect(res.status).toBe(404);
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=60");
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(await res.text()).toBe("Not found\n");
  });

  it("has the IMAGES R2 binding (local)", async () => {
    await env.IMAGES.put("probe", "ok");
    expect(await (await env.IMAGES.get("probe"))?.text()).toBe("ok");
  });
});
