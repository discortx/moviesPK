import { Router } from "express";
import { z } from "zod";
import { pingDb } from "../db.js";
import { validateQuery } from "../middleware/validate.js";

export const API_VERSION = "0.1.0";

/**
 * `GET /api/v1/health` (plan §9.1): `{status, db: "ok" | "down", version}`, `no-store`,
 * DB ping with a 2 s timeout. A down database answers 503 so monitors see the outage.
 */
export const healthRouter = Router();

healthRouter.get("/api/v1/health", validateQuery(z.strictObject({})), async (_req, res) => {
  const dbOk = await pingDb();
  res.set("Cache-Control", "no-store");
  res.status(dbOk ? 200 : 503).json({
    data: { status: dbOk ? "ok" : "degraded", db: dbOk ? "ok" : "down", version: API_VERSION },
    meta: { generatedAt: new Date().toISOString() },
  });
});
