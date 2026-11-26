import { ObjectId, type Db, MongoClient } from "mongodb";
import { MongoMemoryServer } from "mongodb-memory-server";
import request from "supertest";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import app from "../src/app.js";
import { dbAccess, resetDb } from "../src/db.js";
import { addDays, pktDate } from "../src/lib/dates.js";
import { CinemaResponse, Meta, Movie, Showtime } from "../src/schemas/contract.js";

let mongo: MongoMemoryServer;
let client: MongoClient;
let db: Db;
const saved = { ...process.env };
const TODAY = pktDate(new Date());
const D1 = addDays(TODAY, 1);
const D2 = addDays(TODAY, 2);

/** A PKT wall-clock time on `date` as a UTC Date. */
const pkt = (date: string, hhmm: string): Date => new Date(`${date}T${hhmm}:00+05:00`);

const BELKIS = new ObjectId("6740a1b2c3d4e5f6a7b8c9d0");
const LOCAL = new ObjectId("6740a1b2c3d4e5f6a7b8c9d1");
const ROBOTS_ONLY = new ObjectId("6740a1b2c3d4e5f6a7b8c9d2");

function cinema(id: string, city: string, enabled = true): Record<string, unknown> {
  return {
    _id: id,
    chain: "cinepax",
    name: `Cinema ${id}`,
    city,
    address: "Main Boulevard",
    location: { type: "Point", coordinates: [74.35692, 31.47169] },
    websiteUrl: "https://web.cinepax.com",
    facilities: [],
    enabled,
    seatsEnabled: false,
    health: { status: "ok", lastSuccessAt: new Date(), lastRunAt: new Date() },
    lastScrapedAt: new Date("2026-11-26T02:08:00Z"),
    createdAt: new Date(),
    updatedAt: new Date(),
  };
}

function movie(_id: ObjectId, slug: string, title: string, extra: object = {}): object {
  return {
    _id,
    slug,
    localKey: slug,
    title,
    genres: ["horror"],
    languages: ["ur"],
    rating: { certification: "A" },
    poster: null,
    matchStatus: "matched",
    nowShowing: true,
    lastShowingAt: new Date(),
    updatedAt: new Date(),
    ...extra,
  };
}

let n = 0;
function show(movieId: ObjectId, cinemaId: string, startsAt: Date, extra: object = {}): object {
  n += 1;
  return {
    _id: n.toString(16).padStart(40, "0"),
    cinemaId,
    movieId,
    startsAt,
    format: "2D",
    language: "ur",
    seats: { status: "unknown" },
    status: "active",
    missCount: 0,
    lastSeenAt: new Date(),
    expireAt: new Date(startsAt.getTime() + 7 * 86400_000),
    cinema: { name: `Cinema ${cinemaId}`, city: "lahore" },
    movie: { title: "Belkis", slug: "belkis", posterKey: null, genres: ["horror"] },
    updatedAt: new Date(),
    ...extra,
  };
}

beforeAll(async () => {
  mongo = await MongoMemoryServer.create({ binary: { version: "7.0.14" } });
  client = await new MongoClient(mongo.getUri()).connect();
  db = client.db("moviespk_test_dev");
  process.env.MONGODB_URI_API = mongo.getUri();
  process.env.MONGODB_DB = "moviespk_test_dev";
  await db
    .collection("cinemas")
    .insertMany([
      cinema("packages", "lahore") as never,
      cinema("emporium", "lahore") as never,
      cinema("ocean", "karachi") as never,
      cinema("closed", "lahore", false) as never,
    ]);
  await db
    .collection("movies")
    .insertMany([
      movie(BELKIS, "belkis", "Belkis", { tmdbId: 1196970, runtimeMin: 85 }) as never,
      movie(LOCAL, "carry-on-jatta-4", "Carry On Jatta 4", { matchStatus: "unmatched" }) as never,
      movie(ROBOTS_ONLY, "only-closed", "Only At A Closed Cinema") as never,
    ]);
  await db.collection("showtimes").insertMany([
    show(BELKIS, "packages", pkt(D1, "23:30"), { hall: "Screen 4" }) as never,
    show(BELKIS, "emporium", pkt(D2, "00:15"), { format: "3D" }) as never, // after midnight
    show(BELKIS, "ocean", pkt(D1, "20:00")) as never, // other city
    show(BELKIS, "packages", pkt(D1, "18:00"), { status: "cancelled" }) as never,
    show(LOCAL, "packages", pkt(D1, "15:00"), { bookingUrl: "https://web.cinepax.com/b" }) as never,
    show(ROBOTS_ONLY, "closed", pkt(D1, "16:00")) as never, // disabled cinema
  ]);
}, 120_000);

afterAll(async () => {
  process.env = { ...saved };
  await resetDb();
  await client.close();
  await mongo.stop();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const MovieItem = Movie.extend({ formats: z.array(z.string()), cinemaIds: z.array(z.string()) });
const envelope = <T extends z.ZodType>(data: T) => z.strictObject({ data, meta: Meta });

describe("GET /api/v1/cinemas", () => {
  it("lists enabled cinemas with {lat, lng} and no GeoJSON", async () => {
    const res = await request(app).get("/api/v1/cinemas");
    expect(res.status).toBe(200);
    envelope(z.array(CinemaResponse)).parse(res.body);
    expect(res.body.data.map((c: { id: string }) => c.id)).toEqual([
      "emporium",
      "ocean",
      "packages",
    ]);
    const item = res.body.data[0];
    expect(item.location).toEqual({ lat: 31.47169, lng: 74.35692 });
    expect(JSON.stringify(res.body)).not.toMatch(/"type"|"coordinates"|"enabled"|"createdAt"/);
    expect(res.headers["vercel-cdn-cache-control"]).toBe(
      "max-age=3600, stale-while-revalidate=86400",
    );
    expect(res.body.meta.dataAsOf).toBe("2026-11-26T02:08:00.000Z");
  });

  it("filters by city", async () => {
    const res = await request(app).get("/api/v1/cinemas?city=karachi");
    expect(res.body.data.map((c: { id: string }) => c.id)).toEqual(["ocean"]);
  });

  it("rejects an unknown city", async () => {
    expect((await request(app).get("/api/v1/cinemas?city=quetta")).status).toBe(400);
  });
});

describe("GET /api/v1/movies", () => {
  it("lists the movies showing in a city on a PKT date", async () => {
    const res = await request(app).get(`/api/v1/movies?city=lahore&date=${D1}`);
    expect(res.status).toBe(200);
    envelope(z.array(MovieItem)).parse(res.body);
    const items = res.body.data as z.infer<typeof MovieItem>[];
    expect(items.map((m) => m.slug)).toEqual(["belkis", "carry-on-jatta-4"]);
    const [belkis] = items;
    if (!belkis) throw new Error("no movies");
    expect(belkis.cinemaIds).toEqual(["packages"]); // 18:00 is cancelled; 00:15 is D2
    expect(belkis.formats).toEqual(["2D"]);
    expect(res.headers["vercel-cdn-cache-control"]).toBe(
      "max-age=300, stale-while-revalidate=600, stale-if-error=86400",
    );
    expect(JSON.stringify(res.body)).not.toMatch(/localKey|lastShowingAt|updatedAt/);
  });

  it("puts the 00:15 show on the next PKT date", async () => {
    const res = await request(app).get(`/api/v1/movies?city=lahore&date=${D2}`);
    const items = res.body.data as z.infer<typeof MovieItem>[];
    expect(items.map((m) => [m.slug, m.cinemaIds, m.formats])).toEqual([
      ["belkis", ["emporium"], ["3D"]],
    ]);
  });

  it("needs a city", async () => {
    expect((await request(app).get(`/api/v1/movies?date=${D1}`)).status).toBe(400);
  });

  it.each([
    [addDays(TODAY, 8), 400],
    [addDays(TODAY, -1), 400],
    ["2026-02-30", 400],
    [addDays(TODAY, 7), 200],
  ])("date %s → %i", async (date, status) => {
    expect((await request(app).get(`/api/v1/movies?city=lahore&date=${date}`)).status).toBe(status);
  });

  it("an unknown parameter is a 400 with no DB call", async () => {
    const spy = vi.spyOn(dbAccess, "getDb");
    const res = await request(app).get("/api/v1/movies?city=lahore&lat[$ne]=1");
    expect(res.status).toBe(400);
    expect(res.body.error.code).toBe("bad_request");
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("GET /api/v1/movies/:slug/showtimes", () => {
  it("groups the day's showtimes by cinema", async () => {
    const res = await request(app).get(`/api/v1/movies/belkis/showtimes?city=lahore&date=${D1}`);
    expect(res.status).toBe(200);
    const Data = z.strictObject({
      movie: Movie,
      city: z.string(),
      date: z.string(),
      cinemas: z.array(z.strictObject({ cinema: CinemaResponse, showtimes: z.array(Showtime) })),
    });
    envelope(Data).parse(res.body);
    const { cinemas } = res.body.data;
    expect(cinemas.map((c: { cinema: { id: string } }) => c.cinema.id)).toEqual(["packages"]);
    const [only] = cinemas[0].showtimes;
    expect(only.startsAt).toBe(pkt(D1, "23:30").toISOString()); // 23:30 PKT stays on D1
    expect(only.hall).toBe("Screen 4");
    expect(JSON.stringify(res.body)).not.toMatch(/missCount|lastSeenAt|expireAt/);
  });

  it("puts 00:15 PKT on the next date, and not on the evening before", async () => {
    const d1 = await request(app).get(`/api/v1/movies/belkis/showtimes?city=lahore&date=${D1}`);
    const d2 = await request(app).get(`/api/v1/movies/belkis/showtimes?city=lahore&date=${D2}`);
    const starts = (body: { data: { cinemas: { showtimes: { startsAt: string }[] }[] } }) =>
      body.data.cinemas.flatMap((c) => c.showtimes.map((s) => s.startsAt));
    const late = pkt(D2, "00:15").toISOString();
    expect(starts(d1.body)).not.toContain(late);
    expect(starts(d2.body)).toEqual([late]);
  });

  it("returns 404 for an unknown movie", async () => {
    const res = await request(app).get(`/api/v1/movies/nope/showtimes?city=lahore&date=${D1}`);
    expect(res.status).toBe(404);
    expect(res.body.error.code).toBe("not_found");
  });

  it("returns an empty list when nothing is showing in that city", async () => {
    const res = await request(app).get(`/api/v1/movies/belkis/showtimes?city=multan&date=${D1}`);
    expect(res.status).toBe(200);
    expect(res.body.data.cinemas).toEqual([]);
  });
});

describe("GET /api/v1/cities", () => {
  it("makes no DB call", async () => {
    const spy = vi.spyOn(dbAccess, "getDb");
    const res = await request(app).get("/api/v1/cities");
    expect(res.status).toBe(200);
    expect(spy).not.toHaveBeenCalled();
  });
});
