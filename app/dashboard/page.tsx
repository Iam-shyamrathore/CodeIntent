import Link from "next/link";
import { ArrowRight, GitBranch, LockKeyhole } from "lucide-react";
import { ConsoleHeader } from "@/components/console-header";
import { OperatorSignIn } from "@/components/operator-access";
import { VerdictLabel } from "@/components/verdict";
import { isOperator } from "@/lib/session";
import {
  formatDate,
  LABELS,
  read,
  VERDICT_ORDER,
  type Installation,
  type InstalledRepository,
} from "@/lib/dashboard";

export const metadata = { title: "Dashboard · Code Intent" };

type Workspace = Installation & {
  repos:
    { state: "ok"; list: InstalledRepository[] } | { state: "unavailable" };
};

async function loadWorkspaces(): Promise<Workspace[] | null> {
  const installations = await read<{ installations: Installation[] }>(
    "/app/installations",
  );
  if (installations.state !== "ok") return null;
  return Promise.all(
    installations.data.installations.map(async (installation) => {
      const repos = await read<{ repositories: InstalledRepository[] }>(
        `/app/installations/${installation.id}/repositories`,
      );
      return {
        ...installation,
        repos:
          repos.state === "ok"
            ? { state: "ok" as const, list: repos.data.repositories }
            : { state: "unavailable" as const },
      };
    }),
  );
}

function Counts({ repo }: { repo: InstalledRepository }) {
  const parts = VERDICT_ORDER.filter((v) => repo.verdict_counts[v]).map(
    (v) => `${LABELS[v]}: ${repo.verdict_counts[v]}`,
  );
  return (
    <span className="repo-counts">
      {repo.analyses} dependency pull request{repo.analyses === 1 ? "" : "s"}
      {parts.length ? ` · ${parts.join(" · ")}` : ""}
    </span>
  );
}

export default async function Dashboard() {
  const operator = await isOperator();
  if (!operator)
    return (
      <div className="repository-page">
        <ConsoleHeader current="dashboard" />
        <main className="collection-main" id="main">
          <div className="collection-intro">
            <div>
              <p className="collection-breadcrumb">Workspace / Dashboard</p>
              <h1>Every dependency pull request, in one place.</h1>
              <p>
                The dashboard lists installed repositories and their verdicts.
                It is limited to the workspace operator for now.
              </p>
            </div>
          </div>
          <OperatorSignIn purpose="Operator access is required to see installations and their pull requests." />
        </main>
      </div>
    );
  const workspaces = await loadWorkspaces();
  return (
    <div className="repository-page">
      <ConsoleHeader current="dashboard" operator />
      <main className="collection-main" id="main">
        <div className="collection-intro">
          <div>
            <p className="collection-breadcrumb">Workspace / Dashboard</p>
            <h1>Every dependency pull request, in one place.</h1>
            <p>
              The latest verdict for each installed repository. The full report
              for each pull request is one click away, and on GitHub.
            </p>
          </div>
        </div>
        {workspaces === null && (
          <p role="alert" className="request-error collection-error">
            The verdict service is unavailable. Verdicts on GitHub are
            unaffected; try this page again shortly.
          </p>
        )}
        {workspaces?.length === 0 && (
          <section className="console-empty" aria-labelledby="empty-heading">
            <h2 id="empty-heading">Nothing is installed yet</h2>
            <p>
              Install the GitHub App on at least one repository. Its dependency
              pull requests will appear here once they are analysed.
            </p>
            <Link className="text-link" href="/setup">
              Set up the GitHub App <ArrowRight size={14} aria-hidden="true" />
            </Link>
          </section>
        )}
        {workspaces?.map((w) => (
          <section
            key={w.id}
            className="console-section"
            aria-labelledby={`installation-${w.id}`}
          >
            <div className="section-line">
              <h2 id={`installation-${w.id}`}>{w.account_login}</h2>
              <span>
                {w.account_type === "Organization" ? "Organization" : "Account"}{" "}
                · {w.repositories} repositor{w.repositories === 1 ? "y" : "ies"}
                {w.suspended ? " · Suspended on GitHub" : ""}
              </span>
            </div>
            {w.repos.state === "unavailable" && (
              <p className="muted-state" role="status">
                Repositories for this installation could not be loaded.
              </p>
            )}
            {w.repos.state === "ok" && w.repos.list.length === 0 && (
              <p className="muted-state">
                No repositories are selected for this installation. Add them in
                the App settings on GitHub.
              </p>
            )}
            {w.repos.state === "ok" && w.repos.list.length > 0 && (
              <ul className="console-list">
                {w.repos.list.map((repo) => {
                  const [owner, name] = repo.full_name.split("/");
                  const last = repo.last_analysis,
                    decided = repo.last_verdict;
                  const newer = last && last.id !== decided?.id ? last : null;
                  return (
                    <li key={repo.repository_id}>
                      <Link
                        className="repository-row dashboard-row"
                        href={`/dashboard/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`}
                      >
                        <GitBranch size={20} aria-hidden="true" />
                        <div>
                          <h3>
                            {repo.full_name}
                            {repo.private && (
                              <span className="private-note">
                                <LockKeyhole size={12} aria-hidden="true" />
                                Private
                              </span>
                            )}
                          </h3>
                          {decided && (
                            <p>
                              Latest verdict: #{decided.number}
                              {decided.title ? ` ${decided.title}` : ""} ·{" "}
                              <time dateTime={decided.created_at}>
                                {formatDate(decided.created_at)}
                              </time>
                            </p>
                          )}
                          {newer && (
                            <p>
                              Newer: #{newer.number}
                              {newer.title ? ` ${newer.title}` : ""} ·{" "}
                              <VerdictLabel
                                verdict={newer.verdict}
                                status={newer.status}
                              />
                            </p>
                          )}
                          {!last && (
                            <p>No dependency pull request analysed yet.</p>
                          )}
                          <Counts repo={repo} />
                        </div>
                        <div className="row-verdict">
                          {decided ? (
                            <VerdictLabel verdict={decided.verdict} />
                          ) : (
                            <span className="verdict-label verdict-none">
                              No verdict yet
                            </span>
                          )}
                        </div>
                        <ArrowRight size={20} aria-hidden="true" />
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        ))}
        <p className="collection-footnote">
          Verdicts are decided by fixed rules over a static comparison of the
          two releases. “No known impact” is not a guarantee.
        </p>
      </main>
    </div>
  );
}
