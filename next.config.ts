import type { NextConfig } from "next";
const config: NextConfig = {
  devIndicators: false,
  output: "standalone",
  poweredByHeader: false,
  outputFileTracingIncludes: { "/*": ["./fixtures/studies/*.json"] },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
  turbopack: { root: process.cwd() },
};
export default config;
