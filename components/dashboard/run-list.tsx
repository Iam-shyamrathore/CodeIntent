import Link from "next/link";
import type { RunSummary } from "@/lib/dashboard";
import { duration, failure, KIND, runTitle, STATUS } from "@/lib/runs";

function when(value: string) {
  return new Date(value).toLocaleString("en-GB", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Runs as rows: status, what ran, why it failed (when it did), when and how long. */
export function RunList({
  runs,
  empty,
}: {
  runs: RunSummary[];
  empty: string;
}) {
  if (!runs.length) return <p className="ci-note">{empty}</p>;
  return (
    <ul className="ci-rows">
      {runs.map((run) => {
        const problem = failure(run);
        return (
          <li key={run.id}>
            <Link className="ci-row ci-run-row" href={`/runs/${run.id}`}>
              <span className="ci-run-status" data-status={run.status}>
                {STATUS[run.status]}
              </span>
              <span className="ci-row-title">
                <strong>{runTitle(run)}</strong>
                <span>
                  {KIND[run.kind]}
                  {problem ? ` · ${problem.title}` : ""}
                  {run.attempt > 1 ? ` · attempt ${run.attempt}` : ""}
                </span>
              </span>
              <span className="ci-row-meta">
                <time dateTime={run.started_at}>{when(run.started_at)}</time> ·{" "}
                {duration(run.duration_ms)}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** Overview tile: final failures and partial runs, or a quiet all-clear with the latest run. */
export function AttentionTile({
  problems,
  latest,
}: {
  problems: RunSummary[] | null;
  latest: RunSummary[] | null;
}) {
  return (
    <section className="ci-tile ci-tile-attention" aria-labelledby="attention">
      <div className="ci-tile-head">
        <h2 id="attention">
          Needs attention
          {problems?.length ? (
            <span className="ci-count">{problems.length}</span>
          ) : null}
        </h2>
        <Link href="/dashboard/runs">All runs</Link>
      </div>
      {problems === null ? (
        <p className="ci-note" role="status">
          Runs could not be loaded.
        </p>
      ) : problems.length ? (
        <RunList runs={problems.slice(0, 4)} empty="" />
      ) : (
        <p className="ci-note">
          Every check, scan and agent call finished.
          {latest?.[0] && (
            <>
              {" "}
              Latest:{" "}
              <Link href={`/runs/${latest[0].id}`}>{runTitle(latest[0])}</Link>.
            </>
          )}
        </p>
      )}
    </section>
  );
}
