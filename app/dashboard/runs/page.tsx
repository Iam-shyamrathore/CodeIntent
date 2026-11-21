import Link from "next/link";
import { DashboardGate, PageHead } from "@/components/dashboard/tiles";
import { RunList } from "@/components/dashboard/run-list";
import type { RunKind } from "@/lib/dashboard";
import { KIND } from "@/lib/runs";
import { loadContext, loadRuns } from "@/lib/workspaces";

export const metadata = { title: "Runs · CodeIntent" };

const FILTERS = ["all", "problems", "pull", "scan", "mcp"] as const;
type Filter = (typeof FILTERS)[number];
const LABEL: Record<Filter, string> = {
  all: "All",
  problems: "Needs attention",
  pull: KIND.pull + "s",
  scan: KIND.scan + "s",
  mcp: KIND.mcp + "s",
};

/** Every recorded run, each opening its steps, failure explanation, findings and graph. */
export default async function Runs({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [context, query] = await Promise.all([loadContext(), searchParams]);
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/runs" />;
  const filter: Filter = FILTERS.includes(query.show as Filter)
    ? (query.show as Filter)
    : "all";
  const runs = await loadRuns(
    filter === "all" || filter === "problems" ? filter : (filter as RunKind),
    50,
  );
  return (
    <>
      <PageHead
        title="Runs"
        intro="Every pull request check, repository scan and agent call, with each step timed. Failures say which step stopped, why, and whether it retries."
        action={
          <nav className="ci-tabs" aria-label="Which runs">
            {FILTERS.map((f) => (
              <Link
                key={f}
                href={
                  f === "all" ? "/dashboard/runs" : `/dashboard/runs?show=${f}`
                }
                aria-current={f === filter ? "page" : undefined}
              >
                {LABEL[f]}
              </Link>
            ))}
          </nav>
        }
      />
      <section className="ci-tile">
        {runs === null ? (
          <p className="ci-alert" role="alert">
            Runs could not be loaded.
          </p>
        ) : (
          <RunList
            runs={runs}
            empty={
              filter === "problems"
                ? "Nothing needs attention: every run finished."
                : "No runs yet. They appear after the first pull request check, scan or agent call."
            }
          />
        )}
      </section>
    </>
  );
}
