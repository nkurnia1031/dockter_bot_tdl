import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [
      // HTML and BFF routes must always be revalidated after a deployment.
      {source: "/:path*", headers: [{key: "Cache-Control", value: "no-store, max-age=0, must-revalidate"}]},
      // Next static assets are content-hashed, therefore safe and fast to cache.
      {source: "/_next/static/:path*", headers: [{key: "Cache-Control", value: "public, max-age=31536000, immutable"}]},
    ];
  },
};

export default nextConfig;
