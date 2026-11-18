import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [{ source: "/_admin/rq/:path*", destination: "/operations/:path*" }];
  },
};

export default nextConfig;
