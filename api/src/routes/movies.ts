import { Router } from "express";
import type { Document, ObjectId } from "mongodb";
import { z } from "zod";
import { dbAccess } from "../db.js";
import { pktDate, pktDayRange } from "../lib/dates.js";
import { notFoundError } from "../lib/errors.js";
import { CityParam, dateParam } from "../lib/params.js";
import { cinemaItem, movieItem, showtimeItem } from "../lib/serialize.js";
import { cacheHeaders } from "../middleware/cacheHeaders.js";
import { validateQuery } from "../middleware/validate.js";

/**
 * `GET /api/v1/movies?city&date` and `GET /api/v1/movies/:slug/showtimes?city&date`
 * (plan §9.1). A show belongs to PKT day D when `D 00:00 PKT <= startsAt < D+1 00:00 PKT`;
 * for today the lower bound is "now", so past shows are hidden. Only `active` showtimes
 * of enabled cinemas are listed. Edge 5 min, SWR 10 min, stale-if-error 1 day.
 */
export const moviesRouter = Router();

export const MAX_SHOWTIMES = 300;
const SHOWTIME_CACHE = { cdnTtl: 300, swr: 600, sie: 86400 } as const;
const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;

const Query = z.strictObject({ city: CityParam, date: dateParam() });
type QueryValue = z.infer<typeof Query>;

/** The `startsAt` window for PKT day `date`, starting at "now" when the day is today. */
export function showtimeWindow(date: string, now = new Date()): { $gte: Date; $lt: Date } {
  const { start, end } = pktDayRange(date);
  const from = date === pktDate(now) && now > start ? now : start;
  return { $gte: from, $lt: end };
}

async function enabledCinemaIds(city: string): Promise<string[]> {
  const db = await dbAccess.getDb();
  const docs = await db
    .collection("cinemas")
    .find({ enabled: true, city }, { projection: { _id: 1 } })
    .toArray();
  return docs.map((d) => String(d._id));
}

moviesRouter.get(
  "/api/v1/movies",
  validateQuery(Query),
  cacheHeaders(SHOWTIME_CACHE),
  async (_req, res, next) => {
    try {
      const { city, date } = res.locals.query as QueryValue;
      const db = await dbAccess.getDb();
      const cinemaIds = await enabledCinemaIds(city);
      const groups = await db
        .collection("showtimes")
        .aggregate<{ _id: ObjectId; formats: string[]; cinemaIds: string[] }>([
          {
            $match: {
              cinemaId: { $in: cinemaIds },
              status: "active",
              startsAt: showtimeWindow(date),
            },
          },
          {
            $group: {
              _id: "$movieId",
              formats: { $addToSet: "$format" },
              cinemaIds: { $addToSet: "$cinemaId" },
            },
          },
        ])
        .toArray();
      const byId = new Map(groups.map((g) => [g._id.toHexString(), g]));
      const movies = await db
        .collection("movies")
        .find({ _id: { $in: groups.map((g) => g._id) } })
        .sort({ title: 1 })
        .toArray();
      res.json({
        data: movies.map((m: Document) => {
          const g = byId.get((m._id as ObjectId).toHexString());
          return {
            ...movieItem(m),
            formats: [...(g?.formats ?? [])].sort(),
            cinemaIds: [...(g?.cinemaIds ?? [])].sort(),
          };
        }),
        meta: { generatedAt: new Date().toISOString() },
      });
    } catch (error) {
      next(error);
    }
  },
);

moviesRouter.get(
  "/api/v1/movies/:slug/showtimes",
  validateQuery(Query),
  cacheHeaders(SHOWTIME_CACHE),
  async (req, res, next) => {
    try {
      const slug = String(req.params.slug);
      if (!SLUG.test(slug) || slug.length > 80) throw notFoundError("Movie not found");
      const { city, date } = res.locals.query as QueryValue;
      const db = await dbAccess.getDb();
      const movie = await db.collection("movies").findOne({ slug });
      if (movie === null) throw notFoundError("Movie not found");

      const cinemas = await db
        .collection("cinemas")
        .find({ enabled: true, city })
        .sort({ name: 1 })
        .toArray();
      const shows = await db
        .collection("showtimes")
        .find({
          movieId: movie._id,
          cinemaId: { $in: cinemas.map((c) => String(c._id)) },
          status: "active",
          startsAt: showtimeWindow(date),
        })
        .sort({ startsAt: 1, _id: 1 })
        .limit(MAX_SHOWTIMES)
        .toArray();

      const byCinema = new Map<string, Document[]>();
      for (const show of shows) {
        const list = byCinema.get(String(show.cinemaId)) ?? [];
        list.push(show);
        byCinema.set(String(show.cinemaId), list);
      }
      res.json({
        data: {
          movie: movieItem(movie),
          city,
          date,
          cinemas: cinemas
            .filter((c) => byCinema.has(String(c._id)))
            .map((c) => ({
              cinema: cinemaItem(c),
              showtimes: (byCinema.get(String(c._id)) ?? []).map(showtimeItem),
            })),
        },
        meta: { generatedAt: new Date().toISOString() },
      });
    } catch (error) {
      next(error);
    }
  },
);
