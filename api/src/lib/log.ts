import { randomUUID } from "node:crypto";
import type { RequestHandler } from "express";
import { pino, type Logger } from "pino";

/**
 * pino logger with a request ID (plan §9.2 "Logging"). Requests are logged by path only:
 * never the query string (it can hold `lat`/`lng`), headers, cookies or bodies.
 */
export const logger: Logger = pino({
  level: process.env.LOG_LEVEL ?? "info",
  base: null, // no pid/hostname in every line
  timestamp: pino.stdTimeFunctions.isoTime,
});

export function requestLogger(log: Logger = logger): RequestHandler {
  return (req, res, next) => {
    const started = process.hrtime.bigint();
    const reqId = randomUUID();
    res.setHeader("X-Request-Id", reqId);
    res.on("finish", () => {
      log.info(
        {
          reqId,
          method: req.method,
          path: req.path, // Express's path excludes the query string
          status: res.statusCode,
          durationMs: Number((process.hrtime.bigint() - started) / 1_000_000n),
        },
        "request",
      );
    });
    next();
  };
}
