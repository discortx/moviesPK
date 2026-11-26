// Local MongoDB 7 without Docker (dev only): `npm run mongo:dev` in api/.
// Starts an in-memory server on 127.0.0.1:27017 and keeps it running until Ctrl+C.
// Data is lost when it stops. The first start downloads the MongoDB binary (cached after).
import { MongoMemoryServer } from "mongodb-memory-server";

const server = await MongoMemoryServer.create({
  instance: { port: Number(process.env.MONGO_PORT ?? 27017), ip: "127.0.0.1" },
  binary: { version: "7.0.14" },
});
console.log(`MongoDB ready at ${server.getUri()}  (Ctrl+C to stop; data is not kept)`);

const stop = async () => {
  await server.stop();
  process.exit(0);
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
