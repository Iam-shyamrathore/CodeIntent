import { Filters, pick } from "@/components/dashboard/filters";
import {
  DashboardGate,
  PageHead,
  upcomingKind,
  UpcomingTile,
  type UpcomingKind,
} from "@/components/dashboard/tiles";
import { loadContext, loadUpcoming } from "@/lib/workspaces";

export const metadata = { title: "Before you upgrade · CodeIntent" };

const FILTERS = [
  "all",
  "breaks",
  "needs-change",
  "pins",
  "advisories",
] as const;
const LABEL: Record<(typeof FILTERS)[number], string> = {
  all: "All",
  breaks: "Breaks you",
  "needs-change": "Needs a change",
  pins: "Pins to lift",
  advisories: "Advisories",
};

export default async function BeforeYouUpgrade({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [context, query] = await Promise.all([loadContext(), searchParams]);
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/upcoming" />;
  const summary = await loadUpcoming();
  const findings = summary?.findings || [];
  const filter = pick(query.kind, FILTERS, "all");
  const count = (k: UpcomingKind) =>
    findings.filter((f) => upcomingKind(f) === k).length;
  return (
    <>
      <PageHead
        title="Before you upgrade"
        intro="Each repository’s dependencies against their latest releases, checked after install, after each merge and daily: what would break, pins you can lift, and advisories on the versions you run."
      />
      {findings.length > 0 && (
        <Filters
          label="Filter findings"
          current={filter}
          href={(v) =>
            v === "all"
              ? "/dashboard/upcoming"
              : `/dashboard/upcoming?kind=${v}`
          }
          options={FILTERS.map((v) => ({
            value: v,
            label: LABEL[v],
            count: v === "all" ? findings.length : count(v),
          }))}
        />
      )}
      <UpcomingTile
        summary={summary}
        kind={filter === "all" ? undefined : filter}
      />
    </>
  );
}
