import { MongoMemoryServer } from "mongodb-memory-server";
import request from "supertest";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import app from "../src/app.js";
import { resetDb } from "../src/db.js";

let mongo: MongoMemoryServer;
const saved = { ...process.env };

beforeAll(async () => {
  mongo = await MongoMemoryServer.create({ binary: { version: "7.0.14" } });
}, 120_000);

afterAll(async () => {
  await resetDb();
  await mongo.stop();
});

afterEach(async () => {
  process.env = { ...saved };
  await resetDb();
});

function useDb(uri: string | undefined, name: string | undefined = "moviespk_test_dev"): void {
  if (uri === undefined) delete process.env.MONGODB_URI_API;
  else process.env.MONGODB_URI_API = uri;
  if (name === undefined) delete process.env.MONGODB_DB;
  else process.env.MONGODB_DB = name;
}

describe("GET /api/v1/health", () => {
  it("returns 200 with db ok and no-store when MongoDB answers", async () => {
    useDb(mongo.getUri());
    const res = await request(app).get("/api/v1/health");
    expect(res.status).toBe(200);
    expect(res.headers["cache-control"]).toBe("no-store");
    expect(res.body.data).toEqual({ status: "ok", db: "ok", version: "0.1.0" });
    expect(typeof res.body.meta.generatedAt).toBe("string");
  });

  it("returns 503 with db down when the database is not configured", async () => {
    useDb(undefined);
    const res = await request(app).get("/api/v1/health");
    expect(res.status).toBe(503);
    expect(res.body.data).toMatchObject({ status: "degraded", db: "down" });
  });

  it("gives up after the 2 s ping timeout when MongoDB is unreachable", async () => {
    useDb("mongodb://127.0.0.1:9/?directConnection=true");
    const started = Date.now();
    const res = await request(app).get("/api/v1/health");
    expect(res.status).toBe(503);
    expect(Date.now() - started).toBeLessThan(4_000);
    expect(JSON.stringify(res.body)).not.toContain("127.0.0.1");
  }, 10_000);

  it("applies helmet security headers and a request id", async () => {
    useDb(mongo.getUri());
    const res = await request(app).get("/api/v1/health");
    expect(res.headers["x-content-type-options"]).toBe("nosniff");
    expect(res.headers["x-powered-by"]).toBeUndefined();
    expect(res.headers["x-request-id"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("rejects unknown parameters", async () => {
    const res = await request(app).get("/api/v1/health?x=1");
    expect(res.status).toBe(400);
    expect(res.body.error.code).toBe("bad_request");
  });
});
