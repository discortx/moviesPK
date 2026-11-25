import express, { type ErrorRequestHandler, type RequestHandler } from "express";
import * as helmetModule from "helmet";

// Vercel's builder type-checks this entry file with its own module settings, under which
// helmet's default import is typed as a non-callable namespace (TS2349), even though our
// NodeNext build accepts it. At runtime helmet is callable both as the module itself (CJS)
// and as its `default` export (ESM), so resolve it without relying on default-import typing.
const helmet = ((helmetModule as { default?: unknown }).default ??
  helmetModule) as unknown as () => RequestHandler;

export const API_VERSION = "0.1.0";

const app = express();
app.disable("x-powered-by");
app.set("query parser", "simple");
app.use(helmet());

// Placeholder health route (P0-02). The DB ping arrives with P1-14.
app.get("/api/v1/health", (_req, res) => {
  res.set("Cache-Control", "no-store");
  res.json({ data: { status: "ok", db: "unknown", version: API_VERSION }, meta: {} });
});

const notFound: RequestHandler = (_req, res) => {
  res.status(404).json({ error: { code: "not_found", message: "Not found" } });
};

const errorHandler: ErrorRequestHandler = (_err, _req, res, _next) => {
  res.status(500).json({ error: { code: "internal", message: "Internal server error" } });
};

app.use(notFound);
app.use(errorHandler);

export default app;
