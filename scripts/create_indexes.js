#!/usr/bin/env node
// Create the MoviesPK indexes (plan §8.2). Idempotent: safe to run any number of times.
//
//   MONGODB_URI_SCRAPER=... MONGODB_DB=moviespk_dev node scripts/create_indexes.js
//
// Prints the resulting index list per collection. Never prints the connection string.
import { MongoClient } from "mongodb";

/** @type {Record<string, Array<{key: Record<string, unknown>, name: string} & Record<string, unknown>>>} */
const INDEXES = {
  cinemas: [
    { key: { location: "2dsphere" }, name: "location_2dsphere" },
    { key: { city: 1, enabled: 1 }, name: "city_enabled" },
  ],
  movies: [
    {
      key: { tmdbId: 1 },
      name: "tmdbId_unique",
      unique: true,
      partialFilterExpression: { tmdbId: { $exists: true } },
    },
    { key: { localKey: 1 }, name: "localKey_unique", unique: true },
    { key: { slug: 1 }, name: "slug_unique", unique: true },
    { key: { title: "text", originalTitle: "text" }, name: "title_text" },
    { key: { lastShowingAt: 1 }, name: "lastShowingAt" },
  ],
  showtimes: [
    { key: { "cinema.city": 1, startsAt: 1, status: 1 }, name: "city_startsAt_status" },
    { key: { movieId: 1, startsAt: 1 }, name: "movieId_startsAt" },
    { key: { cinemaId: 1, startsAt: 1 }, name: "cinemaId_startsAt" },
    { key: { expireAt: 1 }, name: "expireAt_ttl", expireAfterSeconds: 0 },
  ],
  scrape_runs: [
    { key: { cinemaId: 1, startedAt: -1 }, name: "cinemaId_startedAt" },
    { key: { expireAt: 1 }, name: "expireAt_ttl", expireAfterSeconds: 0 },
  ],
  movie_aliases: [],
};

/** @param {import("mongodb").Db} db */
async function createIndexes(db) {
  const existing = new Set(
    await db
      .listCollections({}, { nameOnly: true })
      .map((c) => c.name)
      .toArray(),
  );
  const result = {};
  for (const [collection, specs] of Object.entries(INDEXES)) {
    if (!existing.has(collection)) await db.createCollection(collection);
    if (specs.length > 0) await db.collection(collection).createIndexes(specs);
    result[collection] = await db.collection(collection).indexes();
  }
  return result;
}

async function main() {
  const uri =
    process.env.MONGODB_URI_SCRAPER ?? process.env.MONGODB_URI ?? "mongodb://localhost:27017";
  const dbName = process.env.MONGODB_DB ?? "moviespk_dev";
  const client = new MongoClient(uri, { serverSelectionTimeoutMS: 10000 });
  try {
    await client.connect();
    const result = await createIndexes(client.db(dbName));
    console.log(`database: ${dbName}`);
    for (const [collection, indexes] of Object.entries(result)) {
      console.log(`\n${collection}`);
      for (const ix of indexes) {
        const extra = [
          ix.unique ? "unique" : "",
          ix.partialFilterExpression ? `partial=${JSON.stringify(ix.partialFilterExpression)}` : "",
          ix.expireAfterSeconds !== undefined ? `expireAfterSeconds: ${ix.expireAfterSeconds}` : "",
        ].filter(Boolean);
        console.log(
          `  ${ix.name}  ${JSON.stringify(ix.key)}${extra.length ? `  (${extra.join(", ")})` : ""}`,
        );
      }
    }
  } finally {
    await client.close();
  }
}

main().catch((err) => {
  console.error(`create_indexes failed: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
