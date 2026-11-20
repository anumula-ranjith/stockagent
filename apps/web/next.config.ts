import type { NextConfig } from "next";

const dailyTool = ":tool(screener|backtest|methodology|assistant|account|admin)";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
  skipTrailingSlashRedirect: true,
  async redirects() {
    return [{ source: "/" + dailyTool, destination: "/datadaily/:tool", permanent: false }];
  },
  async rewrites() {
    const views = ["", "/:instance(\\d+)", "/:instance(\\d+)/view/:path*"];
    return [
      { source: "/datadaily/" + dailyTool, destination: "/:tool" },
      { source: "/datadaily/job-queues/:path*", destination: "/job-queues/:path*" },
      ...views.map(suffix => ({
        source: "/_admin/rq" + suffix,
        destination: "/job-queues" + suffix.replace("(\\d+)", ""),
        missing: [{type: "header" as const, key: "sec-fetch-dest", value: "iframe"}],
      })),
      { source: "/_admin/rq/:path*", destination: "/operations/:path*" },
    ];
  },
};

export default nextConfig;
