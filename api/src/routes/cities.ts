import { Router } from "express";
import { z } from "zod";
import { CITIES } from "../lib/cities.js";
import { cacheHeaders } from "../middleware/cacheHeaders.js";
import { validateQuery } from "../middleware/validate.js";

/** `GET /api/v1/cities` (plan §9.1): bundled list, no DB read; edge 1 h, SWR 1 day. */
export const citiesRouter = Router();

citiesRouter.get(
  "/api/v1/cities",
  validateQuery(z.strictObject({})),
  cacheHeaders({ cdnTtl: 3600, swr: 86400 }),
  (_req, res) => {
    res.json({ data: CITIES, meta: { generatedAt: new Date().toISOString() } });
  },
);
