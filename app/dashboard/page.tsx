import Link from "next/link";
import { ArrowRight, ArrowUpRight, GitBranch, LockKeyhole } from "lucide-react";
import {
  AuthNotice,
  NoInstallations,
  SignInPanel,
} from "@/components/auth-panel";
import { ConsoleHeader } from "@/components/console-header";
import { TelegramConnect } from "@/components/telegram-connect";
import { VerdictLabel } from "@/components/verdict";
import { installUrl } from "@/lib/auth";
import {
  canAccessInstallation,
  getSession,
  installationQuery,
  type Session,
} from "@/lib/session";
import {
  formatDate,
  LABELS,
  read,
  VERDICT_ORDER,
  type Installation,
  type InstalledRepository,
} from "@/lib/dashboard";
import type { TelegramLinks } from "@/lib/telegram";

export const metadata = { title: "Dashboard · Code Intent" };

type Workspace = Installation & {
  repos:
    { state: "ok"; list: InstalledRepository[] } | { state: "unavailable" };
  telegram: TelegramLinks | null;
};

/** Installations this session may see: all for the operator, the user's own for GitHub sessions. */
async function loadWorkspaces(session: Session): Promise<Workspace[] | null> {
  const installations = await read<{ installations: Installation[] }>(
    session.kind === "github"
      ? `/app/installations?${installationQuery(session)}`
      : "/app/installations",
  );
  if (installations.state !== "ok") return null;
  return Promise.all(
    installations.data.installations
      // The backend already filters; this keeps the page safe if it ever does not.
      .filter((installation) => canAccessInstallation(session, installation.id))
      .map(async (installation) => {
        const [repos, telegram] = await Promise.all([
          read<{ repositories: InstalledRepository[] }>(
            `/app/installations/${installation.id}/repositories`,
          ),
          read<TelegramLinks>(`/app/installations/${installation.id}/telegram`),
        ]);
        return {
          telegram: telegram.state === "ok" ? telegram.data : null,
          ...installation,
          repos:
            repos.state === "ok"
              ? { state: "ok" as const, list: repos.data.repositories }
              : { state: "unavailable" as const },
        };
      }),
  );
}

function Telegram({ workspace }: { workspace: Workspace }) {
  const links = workspace.telegram;
  return (
    <div
      className="telegram-panel"
      aria-labelledby={`telegram-${workspace.id}`}
      role="group"
    >
      <h3 id={`telegram-${workspace.id}`}>Telegram alerts</h3>
      {links === null && (
        <p className="muted-state" role="status">
          Linked Telegram chats could not be loaded.
        </p>
      )}
      {links && !links.configured && (
        <p className="telegram-note">
          Telegram is not configured on this deployment. The operator sets{" "}
          <code>TELEGRAM_BOT_TOKEN</code>, <code>TELEGRAM_BOT_USERNAME</code>{" "}
          and <code>TELEGRAM_WEBHOOK_SECRET</code>; see{" "}
          <Link href="/setup#telegram-heading">Setup</Link>.
        </p>
      )}
      {links && links.chats.length > 0 && (
        <ul className="telegram-chats">
          {links.chats.map((chat, i) => (
            <li key={`${chat.linked_at}-${i}`}>
              {chat.title || "Telegram chat"}
              <span>
                Linked{" "}
                <time dateTime={chat.linked_at}>
                  {formatDate(chat.linked_at)}
                </time>
              </span>
            </li>
          ))}
        </ul>
      )}
      {links?.configured && links.chats.length === 0 && (
        <p className="telegram-note">
          No chat is linked. Linked chats get an alert when a pull request
          breaks your code, needs a change, or moves to a version with known
          advisories, and can ask <code>/status</code> and{" "}
          <code>/why package</code>.
        </p>
      )}
      {links?.configured && (
        <TelegramConnect
          installation={workspace.id}
          account={workspace.account_login}
        />
      )}
    </div>
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

export default async function Dashboard({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [session, query] = await Promise.all([getSession(), searchParams]);
  if (!session)
    return (
      <div className="repository-page">
        <ConsoleHeader current="dashboard" />
        <main className="collection-main" id="main">
          <div className="collection-intro">
            <div>
              <p className="collection-breadcrumb">Workspace / Dashboard</p>
              <h1>Every dependency pull request, in one place.</h1>
              <p>
                The dashboard lists the repositories where you installed the
                GitHub App, with the latest verdict for each.
              </p>
            </div>
          </div>
          <AuthNotice code={query.auth} />
          <SignInPanel
            next="/dashboard"
            title="Sign in to see your repositories"
            body="Sign in with the GitHub account that installed the App, or any account with access to an installed repository. You see only the installations GitHub says you can access."
            operatorPurpose="For the deployment operator: the workspace key shows every installation."
          />
        </main>
      </div>
    );
  if (session.kind === "github" && session.installations.length === 0)
    return (
      <div className="repository-page">
        <ConsoleHeader current="dashboard" session={session} />
        <main className="collection-main" id="main">
          <div className="collection-intro">
            <div>
              <p className="collection-breadcrumb">Workspace / Dashboard</p>
              <h1>Every dependency pull request, in one place.</h1>
            </div>
          </div>
          <NoInstallations next="/dashboard" />
        </main>
      </div>
    );
  const workspaces = await loadWorkspaces(session);
  return (
    <div className="repository-page">
      <ConsoleHeader current="dashboard" session={session} />
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
              {session.kind === "github"
                ? "Code Intent has not heard from your installations yet. New installations appear here within a minute; their dependency pull requests appear once they are analysed."
                : "Install the GitHub App on at least one repository. Its dependency pull requests will appear here once they are analysed."}
            </p>
            {session.kind === "github" ? (
              <a className="text-link" href={installUrl()}>
                Install the GitHub App{" "}
                <ArrowUpRight size={14} aria-hidden="true" />
              </a>
            ) : (
              <Link className="text-link" href="/setup">
                Set up the GitHub App{" "}
                <ArrowRight size={14} aria-hidden="true" />
              </Link>
            )}
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
            <Telegram workspace={w} />
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
