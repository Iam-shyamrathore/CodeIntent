import Link from "next/link";
import {
  AuthNotice,
  NoInstallations,
  SignInPanel,
} from "@/components/auth-panel";
import { AgentTokens } from "@/components/agent-tokens";
import { ArrowOut, ArrowRight, GitHubMark } from "@/components/site/icons";
import { DEMO_PR } from "@/components/site/links";
import { TelegramConnect } from "@/components/telegram-connect";
import { PackageChanges, VerdictLabel } from "@/components/verdict";
import { installUrl } from "@/lib/auth";
import {
  formatDate,
  type Ops,
  type PullSummary,
  type UpcomingFinding,
  type UpcomingSummary,
} from "@/lib/dashboard";
import {
  repoHref,
  type Gate,
  type Watched,
  type Workspace,
} from "@/lib/workspaces";

export function PageHead({
  title,
  intro,
  crumb,
  action,
}: {
  title: React.ReactNode;
  intro?: React.ReactNode;
  crumb?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="ci-head">
      <div>
        {crumb && <p className="ci-crumb">{crumb}</p>}
        <h1 className="ci-title">{title}</h1>
        {intro && <p className="ci-intro">{intro}</p>}
      </div>
      {action}
    </div>
  );
}

/** Signed out, nothing installed, or the service down: the same screen in every section. */
export function DashboardGate({
  gate,
  next,
  auth,
}: {
  gate: Gate;
  next: string;
  auth?: string | string[];
}) {
  if (gate.state === "signed-out")
    return (
      <>
        <PageHead
          title="Your dependency pull requests"
          intro="Every repository you installed CodeIntent on, the latest verdicts, and your Telegram alerts."
        />
        <AuthNotice code={auth} />
        <SignInPanel
          next={next}
          title="Sign in to see your repositories"
          body="Use the GitHub account that installed the App, or any account with access to an installed repository. You see only the installations GitHub says you can access."
          operatorPurpose="For the deployment operator: the workspace key shows every installation."
        />
      </>
    );
  if (gate.state === "no-installations")
    return (
      <>
        <PageHead title="Your dependency pull requests" />
        <NoInstallations next={next} />
      </>
    );
  return (
    <>
      <PageHead title="Dashboard" />
      <p role="alert" className="ci-alert">
        The verdict service is unavailable. Verdicts on GitHub are unaffected;
        try this page again shortly.
      </p>
    </>
  );
}

export function UnavailableNotice({ repos }: { repos: boolean }) {
  return repos ? (
    <p role="status" className="ci-alert">
      Some repositories could not be loaded. Verdicts on GitHub are unaffected.
    </p>
  ) : null;
}

export function SeeAll({ href, label }: { href: string; label: string }) {
  return (
    <Link className="ci-see-all" href={href}>
      {label} <ArrowRight size={12} />
    </Link>
  );
}

export function BreaksTile({ breaking }: { breaking: number }) {
  return (
    <section
      className="ci-tile ci-tile-breaks"
      data-zero={breaking === 0 ? "" : undefined}
      aria-labelledby="breaks-title"
    >
      <h2 id="breaks-title">Breaks you this week</h2>
      <p className="ci-big">{breaking}</p>
      <p className="ci-tile-note">
        {breaking === 0 ? (
          "No pull request in the last 7 days breaks your code."
        ) : (
          <Link href="/dashboard/pulls?verdict=breaks">
            See the pull requests <ArrowRight size={12} />
          </Link>
        )}
      </p>
    </section>
  );
}

function NoPulls() {
  return (
    <div className="ci-empty">
      <p>
        No dependency pull request has been analysed yet. Open one, or wait for
        Dependabot or Renovate: CodeIntent comments on it automatically.
      </p>
      <a className="ci-link" href={DEMO_PR}>
        See what the comment looks like <ArrowOut />
      </a>
    </div>
  );
}

/** Compact verdict rows for the overview. */
export function LatestTile({
  pulls,
  seeAll,
}: {
  pulls: PullSummary[];
  seeAll?: string;
}) {
  return (
    <section className="ci-tile ci-tile-latest" aria-labelledby="latest">
      <div className="ci-tile-head">
        <h2 id="latest">Latest verdicts</h2>
        {seeAll && pulls.length > 0 && (
          <SeeAll href={seeAll} label="All pull requests" />
        )}
      </div>
      {pulls.length === 0 ? (
        <NoPulls />
      ) : (
        <ul className="ci-rows">
          {pulls.map((pull) => (
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
  );
}

/** Full pull request rows, with the packages each one changes. */
export function PullList({ pulls }: { pulls: PullSummary[] }) {
  return pulls.length === 0 ? (
    <NoPulls />
  ) : (
    <ul className="ci-rows">
      {pulls.map((pull) => (
        <li key={pull.id}>
          <Link className="ci-row" href={`/pulls/${pull.id}`}>
            <VerdictLabel verdict={pull.verdict} status={pull.status} />
            <span className="ci-row-title">
              <strong>
                #{pull.number} {pull.title || "Untitled pull request"}
              </strong>
              <span>{pull.repository}</span>
              <PackageChanges packages={pull.packages} />
            </span>
            <time className="ci-row-meta" dateTime={pull.created_at}>
              {formatDate(pull.created_at)}
            </time>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export type UpcomingKind = "breaks" | "needs-change" | "pins" | "advisories";
export function upcomingKind(f: UpcomingFinding): UpcomingKind {
  if (f.verdict === "breaks" || f.verdict === "needs-change") return f.verdict;
  return f.lift === "can-be-lifted" ? "pins" : "advisories";
}

export function UpcomingTile({
  summary,
  limit,
  kind,
  seeAll,
}: {
  summary: UpcomingSummary | null;
  limit?: number;
  kind?: UpcomingKind;
  seeAll?: string;
}) {
  const all = summary?.findings || [];
  const findings = kind ? all.filter((f) => upcomingKind(f) === kind) : all;
  const shown = limit ? findings.slice(0, limit) : findings;
  const breaking = all.filter((f) => f.verdict === "breaks").length;
  return (
    <section className="ci-tile ci-tile-upcoming" aria-labelledby="upcoming">
      <div className="ci-tile-head">
        <h2 id="upcoming">
          Before you upgrade
          {breaking > 0 && <span className="ci-count">{breaking}</span>}
        </h2>
        {seeAll && findings.length > shown.length ? (
          <SeeAll href={seeAll} label={`All ${findings.length} findings`} />
        ) : (
          <span className="ci-row-meta">Latest releases, checked daily</span>
        )}
      </div>
      {summary === null ? (
        <p className="ci-note" role="status">
          Upcoming breakage could not be loaded.
        </p>
      ) : findings.length === 0 ? (
        <p className="ci-note">
          {kind && all.length > 0
            ? "Nothing of this kind right now."
            : summary.totals.pending > 0
              ? `Comparing the dependencies of ${summary.totals.pending} repositor${summary.totals.pending === 1 ? "y" : "ies"} with their latest releases…`
              : summary.totals.scanned > 0
                ? "No latest release changes anything your code uses, and no known advisories affect the versions you run."
                : "Each repository is compared with the latest releases of its dependencies after install, then daily."}
        </p>
      ) : (
        <ul className="ci-rows">
          {shown.map((f) => (
            <li key={`${f.repository}-${f.project}-${f.package}`}>
              <Link className="ci-row" href={repoHref(f.repository)}>
                {f.verdict === "breaks" || f.verdict === "needs-change" ? (
                  <VerdictLabel verdict={f.verdict} />
                ) : f.lift === "can-be-lifted" ? (
                  <span className="ci-verdict ci-verdict-no-known-impact">
                    Pin can be lifted
                  </span>
                ) : (
                  <span className="ci-verdict">Known advisory</span>
                )}
                <span className="ci-row-title">
                  <strong>
                    <code translate="no">{f.package}</code>{" "}
                    {f.verdict === "breaks" || f.verdict === "needs-change"
                      ? `${f.current} → ${f.latest}`
                      : f.lift === "can-be-lifted"
                        ? `${f.specifier} blocks ${f.latest}, which changes nothing you use`
                        : `${f.current}: ${f.advisories.slice(0, 2).join(", ")}${f.advisories.length > 2 ? ` and ${f.advisories.length - 2} more` : ""}`}
                  </strong>
                  <span>{f.repository}</span>
                </span>
                <span className="ci-row-meta">
                  {f.places > 0
                    ? `${f.places} place${f.places === 1 ? "" : "s"} in your code`
                    : f.advisories.length > 0
                      ? `${f.advisories.length} advisor${f.advisories.length === 1 ? "y" : "ies"}`
                      : ""}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Overview: one line per thing to set up, each linking to its section. */
export function SetupTile({
  workspaces,
  repos,
}: {
  workspaces: Workspace[];
  repos: number;
}) {
  const chats = workspaces.flatMap((w) => w.telegram?.chats || []);
  const tokens = workspaces.reduce((n, w) => n + (w.agents?.length || 0), 0);
  const rows: { href: string; label: string; value: string; on: boolean }[] = [
    {
      href: "/dashboard/repositories",
      label: "Repositories",
      value: `${repos} watched`,
      on: repos > 0,
    },
    {
      href: "/dashboard/alerts",
      label: "Telegram",
      value:
        chats.length > 0
          ? chats.map((c) => c.title || "Telegram chat").join(", ")
          : "Not connected",
      on: chats.length > 0,
    },
    {
      href: "/dashboard/agents",
      label: "AI agents",
      value:
        tokens > 0
          ? `${tokens} token${tokens === 1 ? "" : "s"}`
          : "No token yet",
      on: tokens > 0,
    },
  ];
  return (
    <section className="ci-tile ci-tile-setup" aria-labelledby="setup-title">
      <h2 id="setup-title">Your setup</h2>
      <ul className="ci-setup-rows">
        {rows.map((row) => (
          <li key={row.href}>
            <Link href={row.href} data-on={row.on ? "" : undefined}>
              <span>{row.label}</span>
              <strong>{row.value}</strong>
              <ArrowRight size={12} />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function RepoGrid({
  repos,
  page,
  pages,
  pageHref,
  total,
  query,
}: {
  repos: Watched[];
  page: number;
  pages: number;
  pageHref: (page: number) => string;
  total: number;
  query?: string;
}) {
  return (
    <section className="ci-tile ci-tile-repos" aria-labelledby="repos">
      <div className="ci-tile-head">
        <h2 id="repos">
          Repositories watched
          <span className="ci-count">{total}</span>
        </h2>
        {total > 6 && (
          <form className="ci-search" role="search" action="">
            <label className="sr-only" htmlFor="repo-search">
              Find a repository
            </label>
            <input
              id="repo-search"
              name="q"
              type="search"
              placeholder="Find a repository"
              defaultValue={query}
              autoComplete="off"
              spellCheck={false}
            />
          </form>
        )}
      </div>
      {total === 0 ? (
        <p className="ci-note">
          No repositories are selected yet. Choose them in the App settings on
          GitHub; they appear here within a minute.
        </p>
      ) : repos.length === 0 ? (
        <p className="ci-note">No repository matches “{query}”.</p>
      ) : (
        <ul className="ci-repo-list">
          {repos.map((repo) => (
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
                    {repo.upcoming?.breaks
                      ? ` · ${repo.upcoming.breaks} upcoming break${repo.upcoming.breaks === 1 ? "" : "s"}`
                      : ""}
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
            <Link href={pageHref(page - 1)} scroll={false}>
              ← Previous
            </Link>
          ) : (
            <span aria-hidden="true">← Previous</span>
          )}
          <span>
            {page} of {pages}
          </span>
          {page < pages ? (
            <Link href={pageHref(page + 1)} scroll={false}>
              Next →
            </Link>
          ) : (
            <span aria-hidden="true">Next →</span>
          )}
        </nav>
      )}
    </section>
  );
}

export function InstallTile() {
  return (
    <section className="ci-tile ci-tile-install" aria-labelledby="more">
      <h2 id="more">Watch more repositories</h2>
      <p>Add or remove repositories on GitHub at any time.</p>
      <a className="ci-btn" href={installUrl()}>
        <GitHubMark />
        Choose repositories <ArrowOut />
      </a>
      <ol className="ci-install-steps" aria-label="What happens next">
        <li>
          <span className="ci-num" aria-hidden="true">
            1
          </span>
          Pick them on GitHub
        </li>
        <li>
          <span className="ci-num" aria-hidden="true">
            2
          </span>
          Their next dependency PR is checked
        </li>
        <li>
          <span className="ci-num" aria-hidden="true">
            3
          </span>
          One check and one comment land on it
        </li>
      </ol>
    </section>
  );
}

export function TelegramTile({ workspaces }: { workspaces: Workspace[] }) {
  return (
    <section className="ci-tile ci-tile-telegram" aria-labelledby="tg-title">
      <div className="ci-tile-head">
        <h2 id="tg-title">Telegram</h2>
        <Link href="/docs/telegram">How it works</Link>
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

export function AgentsTile({ workspaces }: { workspaces: Workspace[] }) {
  return (
    <section className="ci-tile ci-tile-agents" aria-labelledby="agents">
      <div className="ci-tile-head">
        <h2 id="agents">AI agents</h2>
        <Link href="/docs/mcp">MCP tools</Link>
      </div>
      <p className="ci-tile-note">
        Claude Code, Codex or Cursor ask CodeIntent what an upgrade breaks and
        get the exact lines to change.
      </p>
      {workspaces.map((w) =>
        w.agents === null ? (
          <p key={w.id} className="ci-note" role="status">
            Agent tokens for {w.account_login} could not be loaded.
          </p>
        ) : (
          <AgentTokens
            key={w.id}
            installation={w.id}
            account={w.account_login}
            tokens={w.agents}
          />
        ),
      )}
    </section>
  );
}

const total = (counts: Record<string, number>) =>
  Object.values(counts).reduce((a, b) => a + b, 0);
const listed = (counts: Record<string, number>) =>
  Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${n} ${k.replaceAll("_", " ")}`)
    .join(", ") || "none";

/** Operator only: is the worker alive, is anything stuck or failing, is anything being used. */
export function OpsTile({ ops }: { ops: Ops | null }) {
  if (ops === null)
    return (
      <section className="ci-tile ci-tile-ops" aria-labelledby="ops">
        <h2 id="ops">Operations</h2>
        <p className="ci-note" role="status">
          The operations view could not be loaded.
        </p>
      </section>
    );
  const failed = total(ops.queue.failed_24h);
  const rows: [string, string, boolean?][] = [
    [
      "Worker",
      ops.worker.stalled
        ? `stalled · last heartbeat ${ops.worker.last_heartbeat ? formatDate(ops.worker.last_heartbeat) : "never"}`
        : `${ops.worker.live} live`,
      ops.worker.stalled,
    ],
    [
      "Queue",
      `${total(ops.queue.running)} running, ${total(ops.queue.waiting)} waiting`,
    ],
    ["Failed, 24 h", listed(ops.queue.failed_24h), failed > 0],
    ["Webhooks, 24 h", listed(ops.webhooks_24h)],
    ["Pull requests, 24 h", listed(ops.analyses_24h)],
    ["Repository scans", listed(ops.scans)],
    [
      "Telegram",
      `${ops.telegram.chats} chat${ops.telegram.chats === 1 ? "" : "s"}, ${ops.telegram.alerts_24h} alerts in 24 h`,
    ],
    [
      "Agent tokens",
      `${ops.mcp.active} active, ${ops.mcp.used_24h} used in 24 h`,
    ],
  ];
  return (
    <section className="ci-tile ci-tile-ops" aria-labelledby="ops">
      <div className="ci-tile-head">
        <h2 id="ops">Operations</h2>
        <span className="ci-row-meta">Only you see this</span>
      </div>
      <dl className="ci-ops">
        {rows.map(([label, value, bad]) => (
          <div key={label} data-bad={bad ? "" : undefined}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
