import { PackageVerdict } from "./pull-report";
import { ScanNow } from "./scan-now";
import { VerdictLabel } from "./verdict";
import {
  formatDate,
  type RepositoryScan,
  type UpcomingItem,
  type Verdict,
} from "@/lib/dashboard";

const RANK: Record<Verdict, number> = {
  breaks: 0,
  "needs-change": 1,
  "not-checked": 2,
  "no-known-impact": 3,
};
const SKIPPED: Record<string, string> = {
  "no-python-manifests":
    "No Python manifest or lock file on the default branch, so there is nothing to compare.",
  "archived-or-empty": "The repository is archived or has no default branch.",
};

const LIFT: Record<string, string> = {
  "can-be-lifted": "Can be lifted",
  keep: "Keep the pin",
  unknown: "Lift unknown",
};
const itemKey = (item: UpcomingItem) =>
  `${item.project || "."}:${item.package}`;

function Pins({
  items,
  repository,
  sha,
}: {
  items: UpcomingItem[];
  repository: string;
  sha: string;
}) {
  if (!items.length) return null;
  return (
    <div className="ci-pins">
      <h3>Pins that hold back the latest release</h3>
      <ul className="ci-rows">
        {items.map((item) => {
          const origin = item.origin;
          const file = item.location.file
            .split("/")
            .map(encodeURIComponent)
            .join("/");
          return (
            <li key={itemKey(item)} className="ci-row">
              <span
                className={`ci-verdict ci-verdict-regular${item.lift === "can-be-lifted" ? " ci-verdict-no-known-impact" : ""}`}
              >
                {LIFT[item.lift || "unknown"]}
              </span>
              <span className="ci-row-title">
                <strong>
                  <code translate="no">
                    {item.package}
                    {item.specifier}
                  </code>{" "}
                  blocks {item.latest}
                </strong>
                <span>
                  {item.lift_reason
                    ? `${item.lift_reason[0].toUpperCase()}${item.lift_reason.slice(1)}. `
                    : ""}
                  Pinned at{" "}
                  <a
                    href={`https://github.com/${repository}/blob/${sha}/${file}${item.location.line ? `#L${item.location.line}` : ""}`}
                  >
                    <code translate="no">
                      {item.location.file}
                      {item.location.line ? `:${item.location.line}` : ""}
                    </code>
                  </a>
                </span>
                {origin ? (
                  <span>
                    Added in{" "}
                    {origin.pr_url && origin.pr_number ? (
                      <a href={origin.pr_url}>
                        #{origin.pr_number} {origin.pr_title}
                      </a>
                    ) : (
                      <a href={origin.commit_url || "#"}>
                        {origin.message.split("\n", 1)[0]}
                      </a>
                    )}
                    {origin.date && ` · ${formatDate(origin.date)}`}
                  </span>
                ) : (
                  item.origin_detail && (
                    <span>Origin not found: {item.origin_detail}.</span>
                  )
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const activeAdvisories = (item: UpcomingItem) =>
  item.advisories?.status === "advisories"
    ? (item.advisories.advisories || []).filter((a) => !a.withdrawn)
    : [];

/** Every direct dependency against its latest release, worst first, before any pull request exists. */
export function Upcoming({
  repository,
  result,
}: {
  repository: string;
  result: RepositoryScan["scan"] | "unavailable";
}) {
  const running =
    result !== "unavailable" &&
    (result?.status === "queued" || result?.status === "running");
  const head = (
    <div className="ci-tile-head">
      <h2 id="upcoming-title">Before you upgrade</h2>
      <ScanNow repository={repository} busy={running} />
    </div>
  );
  if (result === "unavailable" || result === null || result.status !== "done")
    return (
      <section className="ci-tile" aria-labelledby="upcoming-title">
        {head}
        <p className="ci-note" role="status">
          {result === "unavailable"
            ? "The latest scan could not be loaded."
            : result === null
              ? "Not scanned yet. Every direct dependency is compared with its latest release once a day, and after each merge into the default branch."
              : running
                ? "Comparing every direct dependency with its latest release. Refresh in a minute or two."
                : result.status === "skipped"
                  ? SKIPPED[result.error || ""] || "Skipped."
                  : `The last scan failed (${result.error || "unknown error"}). It runs again tomorrow, or scan now.`}
        </p>
      </section>
    );
  const compared = result.items
    .filter((i) => i.verdict)
    .sort(
      (a, b) =>
        RANK[a.verdict!.verdict] - RANK[b.verdict!.verdict] ||
        a.package.localeCompare(b.package),
    );
  const acting = compared.filter(
    (i) =>
      i.verdict!.verdict === "breaks" || i.verdict!.verdict === "needs-change",
  );
  const unchecked = compared.filter(
    (i) => i.verdict!.verdict === "not-checked",
  );
  const quiet = compared.length - acting.length - unchecked.length;
  const projects = new Set(result.items.map((i) => i.project || "."));
  const where = (item: UpcomingItem) =>
    projects.size > 1 ? ` in ${item.project || "the root project"}` : "";
  const current = result.items.filter((i) => i.status === "current").length;
  const loose = result.items.filter((i) => i.status === "not-locked").length;
  const advised = result.items.filter((i) => activeAdvisories(i).length);
  const pinned = result.items.filter(
    (i) => i.lift && i.allows_latest === false,
  );
  const source = {
    repository,
    head_sha: result.head_sha || result.ref || "HEAD",
  };
  return (
    <section className="ci-tile ci-upcoming" aria-labelledby="upcoming-title">
      {head}
      <p className="ci-note">
        Latest releases on PyPI against what{" "}
        <code translate="no">{result.ref}</code> locks
        {result.scanned_at && (
          <>
            , checked{" "}
            <time dateTime={result.scanned_at}>
              {formatDate(result.scanned_at)}
            </time>
          </>
        )}
        .{" "}
        {quiet > 0 &&
          `${quiet} upgrade${quiet === 1 ? "" : "s"} with no known impact`}
        {quiet > 0 && current > 0 && ", "}
        {current > 0 && `${current} already on the latest release`}
        {(quiet > 0 || current > 0) && loose > 0 && ", "}
        {loose > 0 && `${loose} without an exact version to compare`}
        {(quiet > 0 || current > 0 || loose > 0) && "."}
      </p>
      {acting.length === 0 ? (
        <p className="ci-upcoming-clear">
          <VerdictLabel verdict="no-known-impact" /> No latest release changes
          anything your code uses
          {unchecked.length > 0 ? " that could be checked." : "."}
        </p>
      ) : (
        acting.map((item, index) => (
          <PackageVerdict
            key={itemKey(item)}
            pull={source}
            verdict={item.verdict!}
            index={index}
            single={false}
            heading="h3"
          />
        ))
      )}
      <Pins items={pinned} repository={repository} sha={source.head_sha} />
      {advised.length > 0 && (
        <details className="ci-fold" open={advised.length <= 3}>
          <summary>
            Known advisories on {advised.length} version
            {advised.length === 1 ? "" : "s"} you run now
          </summary>
          <ul className="ci-rows">
            {advised.map((item) => (
              <li key={itemKey(item)} className="ci-row">
                <span className="ci-verdict ci-verdict-regular">
                  Known advisory
                </span>
                <span className="ci-row-title">
                  <strong>
                    <code translate="no">{item.package}</code> {item.current}
                    {where(item)}
                  </strong>
                  <span>
                    {activeAdvisories(item)
                      .slice(0, 4)
                      .map((a, i) => (
                        <span key={a.id}>
                          {i > 0 && ", "}
                          <a href={a.url}>{a.id}</a>
                          {a.fixed ? ` (fixed in ${a.fixed})` : ""}
                        </span>
                      ))}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {unchecked.length > 0 && (
        <details className="ci-fold">
          <summary>
            {unchecked.length} upgrade{unchecked.length === 1 ? "" : "s"} could
            not be fully checked
          </summary>
          <ul className="ci-rows">
            {unchecked.map((item) => (
              <li key={itemKey(item)} className="ci-row">
                <VerdictLabel verdict="not-checked" />
                <span className="ci-row-title">
                  <strong>
                    <code translate="no">{item.package}</code> {item.current} →{" "}
                    {item.latest}
                    {where(item)}
                  </strong>
                  <span>{item.verdict!.reason}.</span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
