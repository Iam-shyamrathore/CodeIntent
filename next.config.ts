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
        ],
      },
    ];
  },
  turbopack: { root: process.cwd() },
};
/** Docs pages are MDX under app/docs; plugins are named as strings so Turbopack can load them. */
const withMDX = createMDX({
  options: { remarkPlugins: ["remark-gfm"], rehypePlugins: ["rehype-slug"] },
});
export default withMDX(config);
