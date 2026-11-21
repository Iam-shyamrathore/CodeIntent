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
  const shown = compared.filter(
    (i) => i.verdict!.verdict !== "no-known-impact",
  );
  const quiet = compared.length - shown.length;
  const current = result.items.filter((i) => i.status === "current").length;
  const loose = result.items.filter((i) => i.status === "not-locked").length;
  const advised = result.items.filter((i) => activeAdvisories(i).length);
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
      {advised.length > 0 && (
        <ul
          className="ci-rows"
          aria-label="Known advisories on versions in use"
        >
          {advised.map((item) => (
            <li key={item.package} className="ci-row">
              <span className="ci-verdict ci-verdict-regular">
                Known advisory
              </span>
              <span className="ci-row-title">
                <strong>
                  <code translate="no">{item.package}</code> {item.current}, the
                  version you run now
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
      )}
      {shown.length === 0 ? (
        <p className="ci-upcoming-clear">
          <VerdictLabel verdict="no-known-impact" /> No latest release changes
          anything your code uses.
        </p>
      ) : (
        shown.map((item, index) => (
          <PackageVerdict
            key={item.package}
            pull={source}
            verdict={item.verdict!}
            index={index}
            single={false}
            heading="h3"
          />
        ))
      )}
    </section>
  );
}
