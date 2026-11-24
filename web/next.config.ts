import type { NextConfig } from "next";

// cacheComponents stays OFF: the plan's ISR model (plan §9.3) relies on the
// `revalidate` and `dynamicParams = false` segment configs, which Next 16
// removes when Cache Components is enabled.
const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Plan §11.3: never use Vercel Image Optimization.
  images: { unoptimized: true },
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
