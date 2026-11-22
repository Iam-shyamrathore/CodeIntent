import type { NextConfig } from "next";
import createMDX from "@next/mdx";

const config: NextConfig = {
  devIndicators: false,
  pageExtensions: ["js", "jsx", "md", "mdx", "ts", "tsx"],
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
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains",
          },
          {
            key: "Permissions-Policy",
            value:
              "camera=(), microphone=(), geolocation=(), browsing-topics=()",
          },
        ],
      },
    ];
  },
  turbopack: { root: process.cwd() },
  experimental: {
    // Client cache: moving between dashboard sections, or back, reuses what was rendered in the last
    // 30 s instead of asking the API again. Actions (Scan now, tokens, Telegram) refresh explicitly.
    staleTimes: { dynamic: 30, static: 180 },
  },
};
/** Docs pages are MDX under app/docs; plugins are named as strings so Turbopack can load them. */
const withMDX = createMDX({
  options: { remarkPlugins: ["remark-gfm"], rehypePlugins: ["rehype-slug"] },
});
export default withMDX(config);
