import Link from "next/link";
import { BookOpen, SquareTerminal } from "lucide-react";
import {
  AgentsTile,
  DashboardGate,
  PageHead,
} from "@/components/dashboard/tiles";
import { ArrowRight } from "@/components/site/icons";
import { loadContext } from "@/lib/workspaces";

export const metadata = { title: "AI agents · CodeIntent" };

const CLIENTS: [string, string][] = [
  ["Claude Code", "claude-code"],
  ["Cursor", "cursor"],
  ["Codex", "codex"],
  ["Devin and others", "devin-and-other-clients"],
];
const TOOLS: [string, string][] = [
  [
    "upgrade_brief",
    "What breaks if a package moves to a version, and how to fix it",
  ],
  ["why_pinned", "Every pin of a package, and the commit and PR that added it"],
  [
    "list_dependencies",
    "Direct dependencies and what blocks their latest release",
  ],
  ["advisories", "Known advisories for every pinned package"],
];

export default async function Agents() {
  const context = await loadContext();
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/agents" />;
  return (
    <>
      <PageHead
        title="AI agents"
        intro="Your coding agent asks CodeIntent over MCP."
        action={
          <Link className="ci-btn-quiet" href="/docs/mcp">
            <BookOpen size={15} strokeWidth={1.5} aria-hidden="true" />
            Docs
          </Link>
        }
      />
      <div className="ci-bento">
        <AgentsTile workspaces={context.workspaces} />
        <section className="ci-tile ci-tile-explain" aria-labelledby="clients">
          <h2 id="clients">Connect</h2>
          <ul className="ci-chips">
            {CLIENTS.map(([name, id]) => (
              <li key={id}>
                <Link href={`/docs/mcp/clients#${id}`}>
                  <SquareTerminal
                    size={15}
                    strokeWidth={1.5}
                    aria-hidden="true"
                  />
                  {name}
                  <ArrowRight size={12} />
                </Link>
              </li>
            ))}
          </ul>
          <h2>Tools</h2>
          <ul className="ci-chips">
            {TOOLS.map(([name, what]) => (
              <li key={name}>
                <code title={what} translate="no">
                  {name}
                </code>
              </li>
            ))}
          </ul>
          <p className="ci-tile-note">All read-only.</p>
        </section>
      </div>
    </>
  );
}
