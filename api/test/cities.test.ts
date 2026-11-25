import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import request from "supertest";
import { describe, expect, it } from "vitest";
import app from "../src/app.js";
import { CITIES } from "../src/lib/cities.js";
import { City } from "../src/schemas/contract.js";

const CITIES_JSON = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "shared",
  "constants",
  "cities.json",
);

describe("cities", () => {
  it("the bundled list equals shared/constants/cities.json", () => {
    expect([...CITIES]).toEqual(JSON.parse(readFileSync(CITIES_JSON, "utf8")));
  });

  it("every city matches the City contract", () => {
    for (const city of CITIES) {
      expect(City.safeParse(city).error?.issues ?? []).toEqual([]);
    }
  });
});

describe("GET /api/v1/cities", () => {
  it("returns the envelope with edge cache headers", async () => {
    const res = await request(app).get("/api/v1/cities");
    expect(res.status).toBe(200);
    expect(res.body.data).toEqual(JSON.parse(JSON.stringify(CITIES)));
    expect(typeof res.body.meta.generatedAt).toBe("string");
    expect(res.headers["vercel-cdn-cache-control"]).toBe(
      "max-age=3600, stale-while-revalidate=86400",
    );
    expect(res.headers["cache-control"]).toBe("public, max-age=60");
    expect(res.headers["x-vercel-enable-rewrite-caching"]).toBe("1");
  });

  it("rejects unknown parameters", async () => {
    const res = await request(app).get("/api/v1/cities?x=1");
    expect(res.status).toBe(400);
    expect(res.body.error.code).toBe("bad_request");
  });
});
