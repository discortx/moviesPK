import { env, SELF } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { handle, type Env } from "../src/index";

const ID = "6740a1b2c3d4e5f6a7b8c9d0";
const STEM = `movies/${ID}/poster-1a2b3c4d`;
const BASE = "https://moviespk-img.moviespk.workers.dev";
const url = (path: string) => `${BASE}${path}`;
const POSTER = `/img/${STEM}-w342.webp`;
const BYTES = new Uint8Array([0x52, 0x49, 0x46, 0x46, 1, 2, 3, 4, 0x57, 0x45, 0x42, 0x50]);

beforeAll(async () => {
  for (const w of [185, 342, 780]) await env.IMAGES.put(`${STEM}-w${w}.webp`, BYTES);
});

/** A bucket stand-in that records every call: proves "no R2 call" for rejected requests. */
function spyEnv(impl: Partial<R2Bucket> = {}): { env: Env; calls: string[] } {
  const calls: string[] = [];
  const bucket = new Proxy(impl as R2Bucket, {
    get(target, prop: string) {
      return (...args: unknown[]) => {
        calls.push(prop);
        const fn = (
          target as unknown as Record<string, ((...a: unknown[]) => unknown) | undefined>
        )[prop];
        if (!fn) throw new Error(`unexpected R2 call: ${prop}`);
        return fn(...args);
      };
    },
  });
  return { env: { IMAGES: bucket }, calls };
}

describe("valid poster (real local R2)", () => {
  it.each([185, 342, 780])("GET w%i → 200 with the poster bytes and headers", async (w) => {
    const res = await SELF.fetch(url(`/img/${STEM}-w${w}.webp`));
    expect(res.status).toBe(200);
    expect(new Uint8Array(await res.arrayBuffer())).toEqual(BYTES);
    expect(res.headers.get("Content-Type")).toBe("image/webp");
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=31536000, immutable");
    expect(res.headers.get("ETag")).toMatch(/^".+"$/);
    expect(res.headers.get("Content-Length")).toBe(String(BYTES.length));
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(res.headers.get("Set-Cookie")).toBeNull();
  });

  it("HEAD → 200 with headers and no body", async () => {
    const res = await SELF.fetch(url(POSTER), { method: "HEAD" });
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Length")).toBe(String(BYTES.length));
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=31536000, immutable");
    expect(await res.text()).toBe("");
  });

  it("missing object → 404, cacheable for 60 s", async () => {
    const res = await SELF.fetch(url(`/img/movies/${ID}/poster-00000000-w342.webp`));
    expect(res.status).toBe(404);
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=60");
    expect(res.headers.get("Content-Type")).toBe("text/plain; charset=utf-8");
    expect(await res.text()).toBe("Not found\n");
  });

  it("HEAD of a missing object → 404", async () => {
    const res = await SELF.fetch(url(`/img/movies/${ID}/poster-00000000-w342.webp`), {
      method: "HEAD",
    });
    expect(res.status).toBe(404);
  });
});

describe("rejected without touching R2", () => {
  it.each(["POST", "PUT", "DELETE", "PATCH", "OPTIONS"])("%s → 405 with Allow", async (method) => {
    const spy = spyEnv();
    const res = await handle(new Request(url(POSTER), { method }), spy.env);
    expect(res.status).toBe(405);
    expect(res.headers.get("Allow")).toBe("GET, HEAD");
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    expect(spy.calls).toEqual([]);
  });

  it.each([
    ["width not allowed", `/img/${STEM}-w500.webp`],
    ["width missing", `/img/${STEM}.webp`],
    ["wrong extension", `/img/${STEM}-w342.jpg`],
    ["uppercase hex id", `/img/movies/${ID.toUpperCase()}/poster-1a2b3c4d-w342.webp`],
    ["uppercase hex hash", `/img/movies/${ID}/poster-1A2B3C4D-w342.webp`],
    ["short id", `/img/movies/${ID.slice(1)}/poster-1a2b3c4d-w342.webp`],
    ["traversal leaving the allow-list", `/img/movies/${ID}/../../../secret.webp`],
    ["encoded traversal", `/img/movies/${ID}/%2e%2e/poster-1a2b3c4d-w342.webp`],
    ["encoded slash", `/img/movies/${ID}%2Fposter-1a2b3c4d-w342.webp`],
    ["extra segment", `/img/movies/${ID}/x/poster-1a2b3c4d-w342.webp`],
    ["trailing slash", `${POSTER}/`],
    ["no /img prefix", `/${STEM}-w342.webp`],
    ["listing", "/img/movies/"],
    ["root", "/"],
  ])("%s → 404", async (_name, path) => {
    const spy = spyEnv();
    const res = await handle(new Request(url(path)), spy.env);
    expect(res.status).toBe(404);
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=60");
    expect(spy.calls).toEqual([]);
  });

  it.each(["?v=2", "?", "?width=342&x=1"])("query string %s → 404", async (query) => {
    const spy = spyEnv();
    const res = await handle(new Request(url(`${POSTER}${query}`)), spy.env);
    // A bare "?" is an empty query (WHATWG URL): it is served, not rejected.
    if (query === "?") {
      expect(spy.calls).toEqual(["get"]);
      return;
    }
    expect(res.status).toBe(404);
    expect(spy.calls).toEqual([]);
  });
});

describe("dot segments", () => {
  it("are resolved by the URL parser first, so they can only reach an allowed key", async () => {
    // `/img/movies/<id>/../<id>/poster-…` normalizes to the valid poster path: it is served
    // as that key. A `..` can never reach a key outside the allow-list.
    const spy = spyEnv({ get: () => Promise.resolve(null) });
    const req = new Request(url(`/img/movies/${ID}/../${ID}/poster-1a2b3c4d-w342.webp`));
    expect(new URL(req.url).pathname).toBe(POSTER);
    await handle(req, spy.env);
    expect(spy.calls).toEqual(["get"]);
  });
});

describe("R2 failures", () => {
  it("GET: an R2 exception → 503 no-store", async () => {
    const spy = spyEnv({
      get: () => Promise.reject(new Error("R2 down")),
    });
    const res = await handle(new Request(url(POSTER)), spy.env);
    expect(res.status).toBe(503);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    expect(spy.calls).toEqual(["get"]);
  });

  it("HEAD: an R2 exception → 503 no-store", async () => {
    const spy = spyEnv({ head: () => Promise.reject(new Error("R2 down")) });
    const res = await handle(new Request(url(POSTER), { method: "HEAD" }), spy.env);
    expect(res.status).toBe(503);
    expect(spy.calls).toEqual(["head"]);
  });

  it("valid requests make exactly one R2 call", async () => {
    const spy = spyEnv({ get: () => Promise.resolve(null) });
    await handle(new Request(url(POSTER)), spy.env);
    expect(spy.calls).toEqual(["get"]);
  });
});
