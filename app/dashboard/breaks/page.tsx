import Link from "next/link";
import { BreakCard } from "@/components/break-card";
import { DashboardGate, PageHead } from "@/components/dashboard/tiles";
import { loadBreaks, loadContext } from "@/lib/workspaces";

export const metadata = { title: "Breaks · CodeIntent" };

const VIEWS = { open: "Open", resolved: "Resolved", all: "All" } as const;
type View = keyof typeof VIEWS;

/** Every recorded break: the code at each place, why upstream changed it, and what became of it. */
export default async function Breaks({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [context, query] = await Promise.all([loadContext(), searchParams]);
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/breaks" />;
  const view: View =
    typeof query.view === "string" && query.view in VIEWS
      ? (query.view as View)
      : "open";
  const items = await loadBreaks(view);
  const list = items || [];
  const repositories = [...new Set(list.map((b) => b.repository))];
  const breaking = list.filter((b) => b.severity === "breaks").length;
  const needed = list.length - breaking;
  return (
    <>
      <PageHead
        title={
          view !== "open"
            ? `${VIEWS[view]} breaks`
            : list.length === 0
              ? "Nothing breaks your code right now"
              : `${breaking} break${breaking === 1 ? "" : "s"}${needed ? `, ${needed} change${needed === 1 ? "" : "s"} needed` : ""}`
        }
        intro="From pull request checks and the daily scan of each default branch: the code at each place, why upstream changed it, and what to use instead."
        action={
          <nav className="ci-tabs" aria-label="Which breaks">
            {(Object.keys(VIEWS) as View[]).map((v) => (
              <Link
                key={v}
                href={
                  v === "open"
                    ? "/dashboard/breaks"
                    : `/dashboard/breaks?view=${v}`
                }
                aria-current={v === view ? "page" : undefined}
              >
                {VIEWS[v]}
              </Link>
            ))}
          </nav>
        }
      />
      {items === null ? (
        <p className="ci-alert" role="alert">
          Breaks could not be loaded. Verdicts on GitHub are unaffected.
        </p>
      ) : list.length === 0 ? (
        <p className="ci-note">
          {view === "open"
            ? "No open break in any watched repository. New ones appear here after a pull request check or the daily scan."
            : "Nothing here yet."}
        </p>
      ) : (
        repositories.map((repo) => (
          <section key={repo} className="ci-run-section" aria-label={repo}>
            <h2 className="ci-section-title">{repo}</h2>
            {list
              .filter((b) => b.repository === repo)
              .map((b) => (
                <BreakCard
                  key={`${b.source}-${b.pull_number}-${b.key}`}
                  item={b}
                  showRepository={false}
                />
              ))}
          </section>
        ))
      )}
    </>
  );
}
