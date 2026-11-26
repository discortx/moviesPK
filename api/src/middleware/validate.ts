import type { RequestHandler } from "express";
import type { z } from "zod";
import { badRequest } from "../lib/errors.js";

/**
 * Validate `req.query` with a strict Zod schema (plan §9.1: unknown parameters → 400).
 * The parsed value is stored on `res.locals.query`; handlers never read `req.query`
 * directly, so no raw query value can reach MongoDB as an object.
 */
export function validateQuery<S extends z.ZodType>(schema: S): RequestHandler {
  return (req, res, next) => {
    const result = schema.safeParse(req.query);
    if (!result.success) {
      next(
        badRequest(
          "Invalid query parameters",
          result.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })),
        ),
      );
      return;
    }
    res.locals.query = result.data;
    next();
  };
}
