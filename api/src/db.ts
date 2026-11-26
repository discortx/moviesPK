import { MongoClient, type Db, type MongoClientOptions } from "mongodb";

/**
 * One module-level client promise reused across invocations (plan §9.2 "DB"), using the
 * read-only API user. `maxIdleTimeMS` lets idle pooled connections close between
 * serverless invocations; `serverSelectionTimeoutMS` keeps a dead cluster from hanging.
 * Errors never include the URI (it holds the password).
 */
export const CLIENT_OPTIONS: MongoClientOptions = {
  maxPoolSize: 5,
  minPoolSize: 0,
  maxIdleTimeMS: 60_000,
  serverSelectionTimeoutMS: 5_000,
};

export const PING_TIMEOUT_MS = 2_000;

let clientPromise: Promise<MongoClient> | undefined;

export class DbConfigError extends Error {}

function getClient(): Promise<MongoClient> {
  if (clientPromise === undefined) {
    const uri = process.env.MONGODB_URI_API;
    if (!uri) return Promise.reject(new DbConfigError("MONGODB_URI_API is not set"));
    clientPromise = new MongoClient(uri, CLIENT_OPTIONS).connect().catch((error: unknown) => {
      clientPromise = undefined; // retry on the next request instead of caching a failure
      throw error;
    });
  }
  return clientPromise;
}

export async function getDb(): Promise<Db> {
  const name = process.env.MONGODB_DB;
  if (!name) throw new DbConfigError("MONGODB_DB is not set");
  return (await getClient()).db(name);
}

/**
 * The routes reach the database only through this object, so tests can spy on it
 * (plan P1-15: "/cities makes no DB call", "unknown parameter → 400 with no DB call").
 */
export const dbAccess = { getDb: (): Promise<Db> => getDb() };

/** `true` when the database answers a ping within `timeoutMs`. Never throws. */
export async function pingDb(timeoutMs = PING_TIMEOUT_MS): Promise<boolean> {
  let timer: NodeJS.Timeout | undefined;
  const timeout = new Promise<boolean>((resolve) => {
    timer = setTimeout(() => resolve(false), timeoutMs);
  });
  const ping = getDb()
    .then((db) => db.command({ ping: 1 }))
    .then(() => true)
    .catch(() => false);
  try {
    return await Promise.race([ping, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

/** Tests only: drop the cached client so the next call reads the environment again. */
export async function resetDb(): Promise<void> {
  const pending = clientPromise;
  clientPromise = undefined;
  if (pending) await pending.then((c) => c.close()).catch(() => undefined);
}
