import {
  BreaksTile,
  DashboardGate,
  LatestTile,
  PageHead,
  SetupTile,
  UnavailableNotice,
  UpcomingTile,
} from "@/components/dashboard/tiles";
import {
  loadContext,
  loadRecent,
  loadUpcoming,
  thisWeek,
} from "@/lib/workspaces";

export const metadata = { title: "Dashboard · CodeIntent" };

const LATEST_SHOWN = 5;
const UPCOMING_SHOWN = 3;

/** Overview: only what needs attention, each part linking to its full section. */
export default async function Dashboard({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [context, query] = await Promise.all([loadContext(), searchParams]);
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard" auth={query.auth} />;
  const { session, workspaces, repos } = context;
  const [recent, upcoming] = await Promise.all([loadRecent(), loadUpcoming()]);
  const week = thisWeek(recent);
  const breaking = week.filter((p) => p.verdict === "breaks").length;
  return (
    <>
      <PageHead
        crumb={`Overview · ${session.kind === "github" ? session.login : "every installation"}`}
        title={
          repos.length === 0
            ? "Nothing to watch yet"
            : week.length > 0
              ? `${week.length} dependency upgrade${week.length === 1 ? "" : "s"} checked this week`
              : "No dependency upgrades this week"
        }
      />
      <UnavailableNotice
        repos={workspaces.some((w) => w.repos.state === "unavailable")}
      />
      <div className="ci-bento">
        <BreaksTile breaking={breaking} />
        <LatestTile
          pulls={recent.slice(0, LATEST_SHOWN)}
          seeAll="/dashboard/pulls"
        />
        <SetupTile workspaces={workspaces} repos={repos.length} />
        {repos.length > 0 && (
          <UpcomingTile
            summary={upcoming}
            limit={UPCOMING_SHOWN}
            seeAll="/dashboard/upcoming"
          />
        )}
      </div>
    </>
  );
}
