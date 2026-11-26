import { Router } from "express";
import { z } from "zod";
import { dbAccess } from "../db.js";
import { CityParam } from "../lib/params.js";
import { cinemaItem } from "../lib/serialize.js";
import { cacheHeaders } from "../middleware/cacheHeaders.js";
import { validateQuery } from "../middleware/validate.js";

/**
 * `GET /api/v1/cinemas?city` (plan §9.1): every enabled cinema (optionally one city) with
 * `location: {lat, lng}`, `health` and `lastScrapedAt`. Edge 1 h, SWR 1 day.
 */
export const cinemasRouter = Router();

const Query = z.strictObject({ city: CityParam.optional() });

cinemasRouter.get(
  "/api/v1/cinemas",
  validateQuery(Query),
  cacheHeaders({ cdnTtl: 3600, swr: 86400 }),
  async (_req, res, next) => {
    try {
      const { city } = res.locals.query as z.infer<typeof Query>;
      const db = await dbAccess.getDb();
      const docs = await db
        .collection("cinemas")
        .find({ enabled: true, ...(city ? { city } : {}) })
        .sort({ name: 1 })
        .toArray();
      const scraped = docs
        .map((d) => d.lastScrapedAt as unknown)
        .filter((d): d is Date => d instanceof Date)
        .sort((a, b) => b.getTime() - a.getTime());
      res.json({
        data: docs.map(cinemaItem),
        meta: {
          generatedAt: new Date().toISOString(),
          ...(scraped[0] ? { dataAsOf: scraped[0].toISOString() } : {}),
        },
      });
    } catch (error) {
      next(error);
    }
  },
);
