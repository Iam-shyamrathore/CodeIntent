import { Filters, pick } from "@/components/dashboard/filters";
import {
  DashboardGate,
  PageHead,
  PullList,
  UnavailableNotice,
} from "@/components/dashboard/tiles";
import { LABELS, type Verdict } from "@/lib/dashboard";
import { loadContext, loadRecent, RECENT_REPOSITORIES } from "@/lib/workspaces";

export const metadata = { title: "Pull requests · CodeIntent" };

const FILTERS = [
  "all",
  "breaks",
  "needs-change",
  "not-checked",
  "no-known-impact",
] as const;

export default async function PullRequests({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [context, query] = await Promise.all([loadContext(), searchParams]);
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/pulls" />;
  const recent = await loadRecent();
  const filter = pick(query.verdict, FILTERS, "all");
  const shown =
    filter === "all" ? recent : recent.filter((p) => p.verdict === filter);
  const count = (v: Verdict) => recent.filter((p) => p.verdict === v).length;
  return (
    <>
      <PageHead
        title="Pull requests"
        intro={`Every dependency pull request CodeIntent checked, newest first, from your ${RECENT_REPOSITORIES} most active repositories. Open a repository for its full history.`}
      />
      <UnavailableNotice
        repos={context.workspaces.some((w) => w.repos.state === "unavailable")}
      />
      <Filters
        label="Filter by verdict"
        current={filter}
        href={(v) =>
          v === "all" ? "/dashboard/pulls" : `/dashboard/pulls?verdict=${v}`
        }
        options={FILTERS.map((v) => ({
          value: v,
          label: v === "all" ? "All" : LABELS[v],
          count: v === "all" ? recent.length : count(v),
        }))}
      />
      <section className="ci-tile" aria-label="Dependency pull requests">
        {shown.length === 0 && recent.length > 0 ? (
          <p className="ci-note">No pull request has this verdict.</p>
        ) : (
          <PullList pulls={shown} />
        )}
      </section>
    </>
  );
}
