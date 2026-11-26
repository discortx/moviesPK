import type { ErrorRequestHandler, RequestHandler } from "express";
import { ApiError, internalError, notFoundError } from "../lib/errors.js";
import { logger } from "../lib/log.js";

export const notFound: RequestHandler = (_req, _res, next) => {
  next(notFoundError());
};

/** Every error leaves as the standard envelope; unexpected ones as a bare 500. */
export const errorHandler: ErrorRequestHandler = (err, req, res, _next) => {
  const apiError = err instanceof ApiError ? err : internalError();
  if (!(err instanceof ApiError)) {
    logger.error(
      { path: req.path, error: err instanceof Error ? err.name : typeof err },
      "unhandled error",
    );
  }
  if (apiError.status >= 400 && !res.getHeader("Cache-Control")) {
    res.set("Cache-Control", "no-store");
  }
  res.status(apiError.status).json(apiError.toBody());
};
