import type { NextConfig } from "next";

// cacheComponents stays OFF: the plan's ISR model (plan §9.3) relies on the
// `revalidate` and `dynamicParams = false` segment configs, which Next 16
// removes when Cache Components is enabled.
const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Plan §11.3: never use Vercel Image Optimization.
  images: { unoptimized: true },
  // Plan §9.2, P1-16: browser API calls stay same-origin; the rewrite goes to the API
  // project's production domain, where its Vercel-CDN-Cache-Control responses are edge-cached.
  async rewrites() {
    const origin = process.env.API_ORIGIN?.replace(/\/+$/, "");
    return origin ? [{ source: "/api/:path*", destination: `${origin}/api/:path*` }] : [];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
