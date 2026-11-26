import express, { type RequestHandler } from "express";
import * as helmetModule from "helmet";
import { requestLogger } from "./lib/log.js";
import { cors } from "./middleware/cors.js";
import { errorHandler, notFound } from "./middleware/errorHandler.js";
import { citiesRouter } from "./routes/cities.js";
import { API_VERSION, healthRouter } from "./routes/health.js";

// Vercel's builder type-checks this entry file with its own module settings, under which
// helmet's default import is typed as a non-callable namespace (TS2349), even though our
// NodeNext build accepts it. At runtime helmet is callable both as the module itself (CJS)
// and as its `default` export (ESM), so resolve it without relying on default-import typing.
const helmet = ((helmetModule as { default?: unknown }).default ??
  helmetModule) as unknown as () => RequestHandler;

export { API_VERSION };

const app = express();
app.disable("x-powered-by");
app.set("query parser", "simple");
app.use(requestLogger());
app.use(helmet());
app.use(cors());

app.use(healthRouter);
app.use(citiesRouter);

app.use(notFound);
app.use(errorHandler);

export default app;
