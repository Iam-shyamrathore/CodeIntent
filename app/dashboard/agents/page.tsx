import Link from "next/link";
import {
  AgentsTile,
  DashboardGate,
  PageHead,
} from "@/components/dashboard/tiles";
import { loadContext } from "@/lib/workspaces";

export const metadata = { title: "AI agents · CodeIntent" };

const TOOLS: [string, string][] = [
  [
    "upgrade_brief",
    "What breaks if a package moves to a version, and the steps to fix it",
  ],
  ["why_pinned", "Every pin of a package, and the commit and PR that added it"],
  [
    "list_dependencies",
    "Direct dependencies, their latest releases and what blocks them",
  ],
  ["advisories", "Known advisories for every locked or exactly pinned package"],
];

export default async function Agents() {
  const context = await loadContext();
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/agents" />;
  return (
    <>
      <PageHead
        title="AI agents"
        intro="Give Claude Code, Codex, Cursor or Devin the same answers the GitHub App posts, over MCP. Tokens belong to one installation and can be revoked here."
      />
      <div className="ci-bento">
        <AgentsTile workspaces={context.workspaces} />
        <section
          className="ci-tile ci-tile-explain ci-tile-wide"
          aria-labelledby="tools"
        >
          <div className="ci-tile-head">
            <h2 id="tools">Tools</h2>
            <Link href="/docs/mcp/clients">Connect a client</Link>
          </div>
          <dl className="ci-commands">
            {TOOLS.map(([t, d]) => (
              <div key={t}>
                <dt>
                  <code>{t}</code>
                </dt>
                <dd>{d}</dd>
              </div>
            ))}
          </dl>
          <p className="ci-tile-note">
            All four are read-only.{" "}
            <Link className="ci-link" href="/docs/mcp">
              MCP reference
            </Link>
          </p>
        </section>
      </div>
    </>
  );
}
