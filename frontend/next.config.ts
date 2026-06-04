import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // The Python API is the source of truth — proxy /api/* to it during dev so
  // the browser-side fetch never deals with CORS. In production, terminate
  // both behind the same reverse proxy.
  async rewrites() {
    const target = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8080";
    return [
      { source: "/api/:path*", destination: `${target}/:path*` },
    ];
  },
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: false },
};

export default config;
