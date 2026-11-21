import Link from "next/link";
import {
  AuthNotice,
  NoInstallations,
  SignInPanel,
} from "@/components/auth-panel";
import { ConsoleHeader } from "@/components/console-header";
import { SiteFooter } from "@/components/site/footer";
import { ArrowOut, GitHubMark } from "@/components/site/icons";
import { DEMO_PR } from "@/components/site/links";
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
  read,
  type Installation,
  type InstalledRepository,
  type PullSummary,
  type RepositoryPulls,
} from "@/lib/dashboard";
import type { TelegramLinks } from "@/lib/telegram";

export const metadata = { title: "Dashboard · CodeIntent" };

const WEEK = 7 * 24 * 60 * 60 * 1000;
/** Recent pull requests are read for at most this many repositories, newest activity first. */
const RECENT_REPOSITORIES = 12;
const RECENT_PER_REPOSITORY = 10;
const LATEST_SHOWN = 6;

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

type Watched = InstalledRepository & { installation: number };

const REPOS_PER_PAGE = 6;

/** Active repositories first (newest pull request), then the rest by name. */
function byActivity(a: Watched, b: Watched): number {
  const left = a.last_analysis?.created_at || "";
  const right = b.last_analysis?.created_at || "";
  if (left !== right) return right.localeCompare(left);
  return a.full_name.localeCompare(b.full_name);
}

function pageNumber(
  value: string | string[] | undefined,
  pages: number,
): number {
  const parsed = Number(Array.isArray(value) ? value[0] : value);
  return Number.isInteger(parsed) && parsed >= 1 ? Math.min(parsed, pages) : 1;
}

/** The newest dependency pull requests across the repositories with any analysis. */
async function loadRecent(
  session: Session,
  repos: Watched[],
): Promise<PullSummary[]> {
  const scope =
    session.kind === "github" ? `&${installationQuery(session)}` : "";
  const active = repos
    .filter((r) => r.last_analysis)
    .sort((a, b) =>
      (b.last_analysis?.created_at || "").localeCompare(
        a.last_analysis?.created_at || "",
      ),
    )
    .slice(0, RECENT_REPOSITORIES);
  const lists = await Promise.all(
    active.map(async (repo) => {
      const [owner, name] = repo.full_name.split("/");
      const result = await read<RepositoryPulls>(
        `/app/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/pulls?limit=${RECENT_PER_REPOSITORY}&installation=${repo.installation}${scope}`,
      );
      return result.state === "ok" &&
        canAccessInstallation(session, result.data.repository.installation_id)
        ? result.data.pulls
        : [];
    }),
  );
  return lists.flat().sort((a, b) => b.created_at.localeCompare(a.created_at));
}

function repoHref(fullName: string) {
  const [owner, name] = fullName.split("/");
  return `/dashboard/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`;
}

function Shell({
  session,
  children,
}: {
  session: Session | null;
  children: React.ReactNode;
}) {
  return (
    <div className="ci ci-page">
      <ConsoleHeader current="dashboard" session={session} />
      <main className="ci-main" id="main">
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}

function TelegramTile({ workspaces }: { workspaces: Workspace[] }) {
  return (
    <section className="ci-tile ci-tile-telegram" aria-labelledby="tg-title">
      <div className="ci-tile-head">
        <h2 id="tg-title">Telegram</h2>
        <Link href="/setup#telegram">How it works</Link>
      </div>
      {workspaces.map((w) => {
        const links = w.telegram;
        const chats = links?.chats || [];
        return (
          <div className="ci-tg-account" key={w.id}>
            {links === null ? (
              <p className="ci-note" role="status">
                Linked chats for {w.account_login} could not be loaded.
              </p>
            ) : !links.configured ? (
              <p className="ci-note">
                Telegram is not configured on this deployment.
              </p>
            ) : chats.length > 0 ? (
              <p className="ci-tg-status" data-on="">
                <span>
                  {chats.map((c) => c.title || "Telegram chat").join(", ")}{" "}
                  <small>
                    · {w.account_login} · linked{" "}
                    <time dateTime={chats[0].linked_at}>
                      {formatDate(chats[0].linked_at)}
                    </time>
                  </small>
                </span>
              </p>
            ) : (
              <p className="ci-tg-status">
                <span>
                  Not connected{" "}
                  {workspaces.length > 1 && <small>· {w.account_login}</small>}
                </span>
              </p>
            )}
            {links?.configured && chats.length === 0 && (
              <TelegramConnect installation={w.id} account={w.account_login} />
            )}
          </div>
        );
      })}
    </section>
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
      <Shell session={null}>
        <div className="ci-head">
          <div>
            <h1 className="ci-title">Your dependency pull requests</h1>
            <p className="ci-intro">
              Every repository you installed CodeIntent on, the latest verdicts,
              and your Telegram alerts.
            </p>
          </div>
        </div>
        <AuthNotice code={query.auth} />
        <SignInPanel
          next="/dashboard"
          title="Sign in to see your repositories"
          body="Use the GitHub account that installed the App, or any account with access to an installed repository. You see only the installations GitHub says you can access."
          operatorPurpose="For the deployment operator: the workspace key shows every installation."
        />
      </Shell>
    );
  if (session.kind === "github" && session.installations.length === 0)
    return (
      <Shell session={session}>
        <div className="ci-head">
          <h1 className="ci-title">Your dependency pull requests</h1>
        </div>
        <NoInstallations next="/dashboard" />
      </Shell>
    );
  const workspaces = await loadWorkspaces(session);
  if (workspaces === null)
    return (
      <Shell session={session}>
        <div className="ci-head">
          <h1 className="ci-title">Dashboard</h1>
        </div>
        <p role="alert" className="ci-alert">
          The verdict service is unavailable. Verdicts on GitHub are unaffected;
          try this page again shortly.
        </p>
      </Shell>
    );
  const repos: Watched[] = workspaces.flatMap((w) =>
    w.repos.state === "ok"
      ? w.repos.list.map((r) => ({ ...r, installation: w.id }))
      : [],
  );
  const pages = Math.max(1, Math.ceil(repos.length / REPOS_PER_PAGE));
  const page = pageNumber(query.repos, pages);
  const shown = [...repos]
    .sort(byActivity)
    .slice((page - 1) * REPOS_PER_PAGE, page * REPOS_PER_PAGE);
  const recent = await loadRecent(session, repos);
  const latest = recent.slice(0, LATEST_SHOWN);
  const since = Date.now() - WEEK;
  const breaking = recent.filter(
    (p) => p.verdict === "breaks" && new Date(p.created_at).getTime() >= since,
  ).length;
  const unavailable = workspaces.some((w) => w.repos.state === "unavailable");
  const install = installUrl();
  const greeting =
    session.kind === "github" ? session.login : "every installation";

  return (
    <Shell session={session}>
      <div className="ci-head">
        <div>
          <p className="ci-crumb">Dashboard · {greeting}</p>
          <h1 className="ci-title">
            {repos.length === 0
              ? "Nothing to watch yet"
              : breaking > 0
                ? `${breaking} upgrade${breaking === 1 ? "" : "s"} broke your code this week`
                : "No breaking upgrades this week"}
          </h1>
        </div>
      </div>
      {unavailable && (
        <p role="status" className="ci-alert">
          Some repositories could not be loaded. Verdicts on GitHub are
          unaffected.
        </p>
      )}
      <div className="ci-bento">
        <section
          className="ci-tile ci-tile-breaks"
          data-zero={breaking === 0 ? "" : undefined}
          aria-labelledby="breaks-title"
        >
          <h2 id="breaks-title">Breaks you this week</h2>
          <p className="ci-big">{breaking}</p>
          <p className="ci-tile-note">
            {breaking === 0
              ? "No pull request in the last 7 days breaks your code."
              : "Pull requests opened in the last 7 days."}
          </p>
        </section>

        <section className="ci-tile ci-tile-latest" aria-labelledby="latest">
          <div className="ci-tile-head">
            <h2 id="latest">Latest verdicts</h2>
          </div>
          {latest.length === 0 ? (
            <div className="ci-empty">
              <p>
                No dependency pull request has been analysed yet. Open one, or
                wait for Dependabot or Renovate: CodeIntent comments on it
                automatically.
              </p>
              <a className="ci-link" href={DEMO_PR}>
                See what the comment looks like <ArrowOut />
              </a>
            </div>
          ) : (
            <ul className="ci-rows">
              {latest.map((pull) => (
                <li key={pull.id}>
                  <Link className="ci-row" href={`/pulls/${pull.id}`}>
                    <VerdictLabel verdict={pull.verdict} status={pull.status} />
                    <span className="ci-row-title">
                      <strong>
                        #{pull.number} {pull.title || "Untitled pull request"}
                      </strong>
                      <span>{pull.repository}</span>
                    </span>
                    <time className="ci-row-meta" dateTime={pull.created_at}>
                      {formatDate(pull.created_at)}
                    </time>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <TelegramTile workspaces={workspaces} />

        <section className="ci-tile ci-tile-repos" aria-labelledby="repos">
          <div className="ci-tile-head">
            <h2 id="repos">
              Repositories watched
              <span className="ci-count">{repos.length}</span>
            </h2>
          </div>
          {repos.length === 0 ? (
            <p className="ci-note">
              No repositories are selected yet. Choose them in the App settings
              on GitHub; they appear here within a minute.
            </p>
          ) : (
            <ul className="ci-repo-list">
              {shown.map((repo) => (
                <li key={`${repo.installation}-${repo.repository_id}`}>
                  <Link className="ci-repo" href={repoHref(repo.full_name)}>
                    <strong>{repo.full_name}</strong>
                    <span>
                      {repo.last_verdict ? (
                        <VerdictLabel verdict={repo.last_verdict.verdict} />
                      ) : (
                        <span>No verdict yet</span>
                      )}
                      <span>
                        {repo.analyses} PR{repo.analyses === 1 ? "" : "s"}
                        {repo.private ? " · private" : ""}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {pages > 1 && (
            <nav className="ci-pager" aria-label="Repository pages">
              {page > 1 ? (
                <Link href={`/dashboard?repos=${page - 1}`} scroll={false}>
                  ← Previous
                </Link>
              ) : (
                <span aria-hidden="true">← Previous</span>
              )}
              <span>
                {page} of {pages}
              </span>
              {page < pages ? (
                <Link href={`/dashboard?repos=${page + 1}`} scroll={false}>
                  Next →
                </Link>
              ) : (
                <span aria-hidden="true">Next →</span>
              )}
            </nav>
          )}
        </section>

        <section className="ci-tile ci-tile-install" aria-labelledby="more">
          <h2 id="more">Install on more repositories</h2>
          <p>
            Add or remove repositories on GitHub at any time. New ones are
            checked from their next dependency pull request.
          </p>
          <a className="ci-btn" href={install}>
            <GitHubMark />
            Choose repositories <ArrowOut />
          </a>
        </section>
      </div>
    </Shell>
  );
}
