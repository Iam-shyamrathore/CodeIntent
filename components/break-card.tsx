import Link from "next/link";
import { ArrowOut } from "./site/icons";
import { VerdictLabel } from "./verdict";
import { formatDate, publicSymbol, pullUrl, type Break } from "@/lib/dashboard";
import { BREAK_STATUS, githubLine } from "@/lib/runs";

const WHAT: Record<string, string> = {
  removed: "was removed",
  "parameter-removed": "no longer accepts this argument",
  "parameter-required": "now requires an argument you don’t pass",
  "parameter-moved": "changed the order of its positional arguments",
  "default-changed": "changed a default",
  deprecated: "is deprecated",
};

/** One break: where it is in your code, what changed upstream and why, what to use, and its fate. */
export function BreakCard({
  item,
  showRepository = true,
}: {
  item: Break;
  showRepository?: boolean;
}) {
  const change = item.change;
  const target = `${publicSymbol(change.symbol)}${change.parameter ? `(${change.parameter}=)` : ""}`;
  const decision = item.decision;
  const quote = decision?.quotes?.find((q) => q.source_kind !== "pr-title");
  const ref = item.source === "scan" ? "HEAD" : null;
  return (
    <article className="ci-break" data-status={item.status}>
      <header className="ci-break-head">
        <VerdictLabel verdict={item.severity} />
        <h3>
          <code translate="no">{item.package}</code> {item.start_version}
          <span aria-hidden="true"> → </span>
          <span className="sr-only"> to </span>
          {item.end_version}
        </h3>
        <span className="ci-break-status" data-status={item.status}>
          {BREAK_STATUS[item.status]}
          {item.resolved_at && ` · ${formatDate(item.resolved_at)}`}
        </span>
      </header>
      <p className="ci-break-what">
        <code translate="no">{target}</code> {WHAT[change.kind] || change.kind}
        {change.guarded && " (your import has a fallback)"}.
        {change.replacement && (
          <>
            {" "}
            Use <code className="ci-instead">{change.replacement}</code>.
          </>
        )}
      </p>
      <ul className="ci-break-places">
        {item.places.slice(0, 4).map((p, i) => (
          <li key={`${p.file}:${p.line}:${i}`}>
            <a
              href={
                ref
                  ? githubLine(item.repository, ref, p.file, p.line)
                  : `${pullUrl(item.repository, item.pull_number)}/files`
              }
            >
              <code translate="no">
                {p.file}
                {p.line ? `:${p.line}` : ""}
              </code>
            </a>
            {p.code && (
              <pre className="ci-break-code">
                <code translate="no">{p.code}</code>
              </pre>
            )}
          </li>
        ))}
        {item.places.length > 4 && (
          <li className="ci-note">and {item.places.length - 4} more places</li>
        )}
      </ul>
      {decision?.pr_url && (
        <p className="ci-break-why">
          <span>Why:</span> changed in{" "}
          <a href={decision.pr_url}>
            #{decision.pr_number} {decision.pr_title}
          </a>
          {decision.deprecation?.pr_url && (
            <>
              , deprecated earlier in{" "}
              <a href={decision.deprecation.pr_url}>
                #{decision.deprecation.pr_number}
              </a>
            </>
          )}
          .{quote && <q>{quote.text.trim()}</q>}
        </p>
      )}
      <footer className="ci-break-foot">
        {showRepository && <strong>{item.repository}</strong>}
        <span>
          Found by{" "}
          {item.source === "pull" ? (
            item.analysis_id ? (
              <Link href={`/pulls/${item.analysis_id}`}>
                pull request #{item.pull_number}
              </Link>
            ) : (
              <a href={pullUrl(item.repository, item.pull_number)}>
                pull request #{item.pull_number} <ArrowOut size={12} />
              </a>
            )
          ) : (
            "the daily scan"
          )}
          {" · first seen "}
          <time dateTime={item.first_seen}>{formatDate(item.first_seen)}</time>
          {item.last_run && (
            <>
              {" · "}
              <Link href={`/runs/${item.last_run}`}>latest run</Link>
            </>
          )}
        </span>
      </footer>
    </article>
  );
}
