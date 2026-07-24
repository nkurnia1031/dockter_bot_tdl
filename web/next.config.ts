import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  basePath: "/ui",
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
