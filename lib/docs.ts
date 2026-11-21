/** The docs sidebar, in reading order; the pager at the foot of each page follows it too. */
export type DocLink = { href: string; title: string };
export const DOCS: { group: string; pages: DocLink[] }[] = [
  {
    group: "Getting started",
    pages: [
      { href: "/docs", title: "Introduction" },
      { href: "/docs/quickstart", title: "Quickstart" },
    ],
  },
  {
    group: "How it works",
    pages: [
      { href: "/docs/how-it-works", title: "The analysis" },
      { href: "/docs/verdicts", title: "Verdicts" },
      { href: "/docs/before-you-upgrade", title: "Before you upgrade" },
    ],
  },
  {
    group: "Integrations",
    pages: [
      { href: "/docs/telegram", title: "Telegram" },
      { href: "/docs/mcp", title: "MCP server" },
      { href: "/docs/mcp/clients", title: "Connect an agent" },
      { href: "/docs/mcp/self-host", title: "Run the MCP server" },
    ],
  },
  {
    group: "Trust",
    pages: [{ href: "/docs/security", title: "Security and data" }],
  },
];
export const DOC_ORDER = DOCS.flatMap((g) => g.pages);
