/**
 * Worker `moviespk-img` (plan §11.3.2). P1-18 scaffold: answers every request with a
 * short-lived 404 and never touches R2. The real poster handler arrives in P1-19.
 */

export interface Env {
  /** The private images bucket (`moviespk-prod`, or `moviespk-dev` with `--env dev`). */
  IMAGES: R2Bucket;
}

export default {
  fetch(): Response {
    return new Response("Not found\n", {
      status: 404,
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "public, max-age=60",
        "X-Content-Type-Options": "nosniff",
      },
    });
  },
} satisfies ExportedHandler<Env>;
