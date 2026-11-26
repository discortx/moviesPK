import { Writable } from "node:stream";
import express from "express";
import { pino } from "pino";
import request from "supertest";
import { describe, expect, it } from "vitest";
import app from "../src/app.js";
import { CLIENT_OPTIONS } from "../src/db.js";
import { addDays, isIsoDate, pktDate, pktDayRange } from "../src/lib/dates.js";
import { badRequest } from "../src/lib/errors.js";
import { requestLogger } from "../src/lib/log.js";
import { cors } from "../src/middleware/cors.js";
import { errorHandler, notFound } from "../src/middleware/errorHandler.js";

describe("db client options (plan §9.2)", () => {
  it("are tuned for serverless", () => {
    expect(CLIENT_OPTIONS).toEqual({
      maxPoolSize: 5,
      minPoolSize: 0,
      maxIdleTimeMS: 60_000,
      serverSelectionTimeoutMS: 5_000,
    });
  });
});

describe("errors", () => {
  it("unknown route returns the standard 404 envelope", async () => {
    const res = await request(app).get("/api/v1/nope?lat=31.5");
    expect(res.status).toBe(404);
    expect(res.body).toEqual({ error: { code: "not_found", message: "Not found" } });
    expect(res.headers["cache-control"]).toBe("no-store");
  });

  it("unexpected errors become a bare 500 without details", async () => {
    const test = express();
    test.get("/boom", () => {
      throw new Error("secret: mongodb+srv://user:pass@host");
    });
    test.use(notFound);
    test.use(errorHandler);
    const res = await request(test).get("/boom");
    expect(res.status).toBe(500);
    expect(res.body).toEqual({ error: { code: "internal", message: "Internal server error" } });
  });

  it("ApiError details are kept", async () => {
    const test = express();
    test.get("/bad", (_req, _res, next) => next(badRequest("Invalid", [{ path: "q" }])));
    test.use(errorHandler);
    const res = await request(test).get("/bad");
    expect(res.status).toBe(400);
    expect(res.body.error).toEqual({
      code: "bad_request",
      message: "Invalid",
      details: [{ path: "q" }],
    });
  });
});

describe("request logging", () => {
  it("logs the path but never the query string", async () => {
    const lines: string[] = [];
    const sink = new Writable({
      write(chunk, _enc, done) {
        lines.push(String(chunk));
        done();
      },
    });
    const test = express();
    test.use(requestLogger(pino({ base: null }, sink)));
    test.get("/api/v1/cinemas/nearby", (_req, res) => {
      res.json({ ok: true });
    });
    await request(test).get("/api/v1/cinemas/nearby?lat=31.55&lng=74.35&radiusKm=10");
    await new Promise((r) => setImmediate(r));
    const record = JSON.parse(lines.join(""));
    expect(record).toMatchObject({ path: "/api/v1/cinemas/nearby", status: 200, method: "GET" });
    expect(lines.join("")).not.toMatch(/lat|lng|31\.55|74\.35/);
  });
});

describe("cors", () => {
  const test = express();
  test.use(cors("https://moviespk-web.vercel.app, https://other.example/"));
  test.get("/x", (_req, res) => {
    res.json({});
  });

  it("allows listed origins only", async () => {
    const ok = await request(test).get("/x").set("Origin", "https://moviespk-web.vercel.app");
    expect(ok.headers["access-control-allow-origin"]).toBe("https://moviespk-web.vercel.app");
    const trailing = await request(test).get("/x").set("Origin", "https://other.example");
    expect(trailing.headers["access-control-allow-origin"]).toBe("https://other.example");
    const evil = await request(test).get("/x").set("Origin", "https://evil.example");
    expect(evil.headers["access-control-allow-origin"]).toBeUndefined();
    expect(evil.headers.vary).toContain("Origin");
  });

  it("answers preflight with 204", async () => {
    const res = await request(test).options("/x").set("Origin", "https://moviespk-web.vercel.app");
    expect(res.status).toBe(204);
    expect(res.headers["access-control-allow-methods"]).toBe("GET, HEAD, OPTIONS");
  });
});

describe("PKT dates (plan §9.1)", () => {
  it("groups by the PKT calendar day", () => {
    expect(pktDate(new Date("2026-12-01T18:30:00Z"))).toBe("2026-12-01"); // 23:30 PKT
    expect(pktDate(new Date("2026-12-01T19:15:00Z"))).toBe("2026-12-02"); // 00:15 PKT
  });

  it("gives the UTC range of a PKT day", () => {
    const { start, end } = pktDayRange("2026-12-02");
    expect(start.toISOString()).toBe("2026-12-01T19:00:00.000Z");
    expect(end.toISOString()).toBe("2026-12-02T19:00:00.000Z");
  });

  it("validates and adds days", () => {
    expect(isIsoDate("2026-02-29")).toBe(false);
    expect(isIsoDate("2028-02-29")).toBe(true);
    expect(isIsoDate("2026-12-1")).toBe(false);
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(() => pktDayRange("tomorrow")).toThrow(RangeError);
  });
});
