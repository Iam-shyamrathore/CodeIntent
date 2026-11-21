import "server-only";
import { cache } from "react";
import {
  read,
  type Break,
  type SecurityNews,
  type Installation,
  type RunKind,
  type RunSummary,
  type InstalledRepository,
  type PullSummary,
  type RepositoryPulls,
  type UpcomingSummary,
} from "./dashboard";
import type { McpToken } from "./mcp";
import {
  canAccessInstallation,
  getSession,
  installationQuery,
  type Session,
} from "./session";
import type { TelegramLinks } from "./telegram";

export const WEEK = 7 * 24 * 60 * 60 * 1000;
/** Recent pull requests are read for at most this many repositories, newest activity first. */
export const RECENT_REPOSITORIES = 12;
const RECENT_PER_REPOSITORY = 10;

export type Workspace = Installation & {
  repos:
    { state: "ok"; list: InstalledRepository[] } | { state: "unavailable" };
  telegram: TelegramLinks | null;
  agents: McpToken[] | null;
};
export type Watched = InstalledRepository & { installation: number };

/** Why the dashboard cannot show data yet; each section renders the same gate for these. */
export type Gate =
  | { state: "signed-out" }
  | { state: "no-installations"; session: Session }
  | { state: "unavailable"; session: Session };
export type Context = {
  state: "ok";
  session: Session;
  workspaces: Workspace[];
  repos: Watched[];
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
        const [repos, telegram, agents] = await Promise.all([
          read<{ repositories: InstalledRepository[] }>(
            `/app/installations/${installation.id}/repositories`,
          ),
          read<TelegramLinks>(`/app/installations/${installation.id}/telegram`),
          read<{ tokens: McpToken[] }>(
            `/app/installations/${installation.id}/mcp-tokens`,
          ),
        ]);
        return {
          telegram: telegram.state === "ok" ? telegram.data : null,
          agents: agents.state === "ok" ? agents.data.tokens : null,
          ...installation,
          repos:
            repos.state === "ok"
              ? { state: "ok" as const, list: repos.data.repositories }
              : { state: "unavailable" as const },
        };
      }),
  );
}

/** Session, workspaces and watched repositories; read once per request, shared by the layout and the page. */
export const loadContext = cache(async (): Promise<Context | Gate> => {
  const session = await getSession();
  if (!session) return { state: "signed-out" };
  if (session.kind === "github" && session.installations.length === 0)
    return { state: "no-installations", session };
  const workspaces = await loadWorkspaces(session);
  if (workspaces === null) return { state: "unavailable", session };
  const repos = workspaces.flatMap((w) =>
    w.repos.state === "ok"
      ? w.repos.list.map((r) => ({ ...r, installation: w.id }))
      : [],
  );
  return { state: "ok", session, workspaces, repos };
});

/** The newest dependency pull requests across the repositories with any analysis. */
export const loadRecent = cache(async (): Promise<PullSummary[]> => {
  const context = await loadContext();
  if (context.state !== "ok") return [];
  const { session, repos } = context;
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
});

export const loadUpcoming = cache(async (): Promise<UpcomingSummary | null> => {
  const context = await loadContext();
  if (context.state !== "ok") return null;
  const result = await read<UpcomingSummary>(
    context.session.kind === "github"
      ? `/app/upcoming?${installationQuery(context.session)}`
      : "/app/upcoming",
  );
  return result.state === "ok" ? result.data : null;
});

export function thisWeek(pulls: PullSummary[]) {
  const since = Date.now() - WEEK;
  return pulls.filter((p) => new Date(p.created_at).getTime() >= since);
}

/** Active repositories first (newest pull request), then the rest by name. */
export function byActivity(a: Watched, b: Watched): number {
  const left = a.last_analysis?.created_at || "";
  const right = b.last_analysis?.created_at || "";
  if (left !== right) return right.localeCompare(left);
  return a.full_name.localeCompare(b.full_name);
}

export function repoHref(fullName: string) {
  const [owner, name] = fullName.split("/");
  return `/dashboard/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`;
}

export function pageNumber(
  value: string | string[] | undefined,
  pages: number,
): number {
  const parsed = Number(Array.isArray(value) ? value[0] : value);
  return Number.isInteger(parsed) && parsed >= 1 ? Math.min(parsed, pages) : 1;
}

/** The `installations=` scope of this session, as a query string fragment ("" for the operator). */
async function scope(): Promise<string> {
  const session = await getSession();
  return session?.kind === "github" ? installationQuery(session) : "";
}

export const loadBreaks = cache(
  async (
    status: "open" | "resolved" | "all" = "open",
  ): Promise<Break[] | null> => {
    const q = await scope();
    const result = await read<{ breaks: Break[] }>(
      `/app/breaks?status=${status}${q ? `&${q}` : ""}`,
    );
    return result.state === "ok" ? result.data.breaks : null;
  },
);

export const loadNews = cache(async (): Promise<SecurityNews[] | null> => {
  const q = await scope();
  const result = await read<{ news: SecurityNews[] }>(
    `/app/news${q ? `?${q}` : ""}`,
  );
  return result.state === "ok" ? result.data.news : null;
});

export const loadRuns = cache(
  async (
    filter: "problems" | "all" | RunKind = "all",
    limit = 30,
  ): Promise<RunSummary[] | null> => {
    const q = await scope();
    const which =
      filter === "problems"
        ? "&problems=true"
        : filter === "all"
          ? ""
          : `&kind=${filter}`;
    const result = await read<{ runs: RunSummary[] }>(
      `/app/runs?limit=${limit}${which}${q ? `&${q}` : ""}`,
    );
    return result.state === "ok" ? result.data.runs : null;
  },
);
