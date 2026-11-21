import { ArrowOut } from "./site/icons";
import { PackageChanges, VerdictLabel } from "./verdict";
import type {
  Advisory,
  AdvisoryCheck,
  Change,
  Finding,
  Location,
  PullDetail,
  Unchecked,
  UpgradeVerdict,
} from "@/lib/dashboard";
import { formatDate, publicSymbol, pullUrl } from "@/lib/dashboard";

const WHAT: Record<Change["kind"], string> = {
  removed: "removed",
  "parameter-removed": "no longer accepts this argument",
  "parameter-required": "now requires an argument you don’t pass",
  "parameter-moved": "positional arguments changed order",
  "default-changed": "default changed",
  deprecated: "deprecated",
};
const REASON: Record<string, string> = {
  "compiled-module": "Compiled module, no readable source",
  "dynamic-attribute": "Attribute looked up at run time",
  "dynamic-definition": "Defined at run time",
  "dynamic-import": "Module imported by a computed name",
  "environment-dependent": "Depends on the environment",
  "external-alias": "Re-exported from another package",
  "external-base": "Inherits from another package",
  "file-too-large": "File too large to scan",
  "kwargs-absorbed": "Arguments absorbed by **kwargs",
  "kwargs-passthrough": "Keyword arguments passed through **",
  "load-error": "Release could not be loaded",
  "not-in-distribution": "Not found in the release",
  "not-in-old-version": "Not present in the old release",
  "parse-error": "File could not be parsed",
  "path-outside-repository": "Path outside the repository",
  "return-value": "Used through a return value",
  "signature-unknown": "Signature unknown",
  "star-import": "Star import",
};
const REPLACEMENT_SOURCE = {
  message: "from the library’s deprecation message",
  "message-unverified":
    "suggested by the library; not confirmed in the release",
  signature: "from the new release’s signature",
};
const VISIBLE_LOCATIONS = 3;
/** Where code links point: the repository at the commit that was checked. */
type Source = Pick<PullDetail, "repository" | "head_sha">;

const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const plural = (n: number, one: string, many = `${one}s`) =>
  `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;
const where = (l: Location) =>
  `${l.file}${l.line ? `:${l.line}` : ""}${l.line && l.column ? `:${l.column}` : ""}`;
const target = (change: Change) =>
  `${publicSymbol(change.symbol)}${change.parameter ? `(${change.parameter}=)` : ""}`;

function CodeLink({ pull, location }: { pull: Source; location: Location }) {
  const href = `https://github.com/${pull.repository}/blob/${pull.head_sha}/${location.file
    .split("/")
    .map(encodeURIComponent)
    .join("/")}${location.line ? `#L${location.line}` : ""}`;
  return (
    <a href={href}>
      <code translate="no">
        {location.file}
        {location.line ? `:${location.line}` : ""}
      </code>
    </a>
  );
}

function Locations({ pull, items }: { pull: Source; items: Location[] }) {
  const shown = items.slice(0, VISIBLE_LOCATIONS),
    rest = items.slice(VISIBLE_LOCATIONS);
  return (
    <ul>
      {shown.map((l, i) => (
        <li key={`${where(l)}-${i}`}>
          <CodeLink pull={pull} location={l} />
        </li>
      ))}
      {rest.length > 0 && (
        <li>
          <details>
            <summary>{plural(rest.length, "more place")}</summary>
            <ul>
              {rest.map((l, i) => (
                <li key={`${where(l)}-${i}`}>
                  <CodeLink pull={pull} location={l} />
                </li>
              ))}
            </ul>
          </details>
        </li>
      )}
    </ul>
  );
}

function Findings({
  pull,
  verdict,
}: {
  pull: Source;
  verdict: UpgradeVerdict;
}) {
  const findings = verdict.findings || [];
  if (!findings.length) return null;
  return (
    <table className="ci-findings">
      <caption className="sr-only">
        What changes for your code in {verdict.package}
      </caption>
      <thead>
        <tr>
          <th scope="col">Your code</th>
          <th scope="col">What changed</th>
          <th scope="col">Use instead</th>
        </tr>
      </thead>
      <tbody>
        {findings.map((f: Finding, i) => (
          <tr key={i}>
            <td>
              <Locations pull={pull} items={f.locations} />
            </td>
            <td>
              {f.severity !== verdict.verdict && (
                <>
                  <VerdictLabel verdict={f.severity} />{" "}
                </>
              )}
              <code translate="no">{target(f.change)}</code>{" "}
              {WHAT[f.change.kind]}
              {f.guarded && <small>Your import has a fallback.</small>}
            </td>
            <td>
              {f.change.replacement ? (
                <>
                  <code className="ci-instead" translate="no">
                    {f.change.replacement}
                  </code>
                  {f.change.replacement_source && (
                    <small>
                      {REPLACEMENT_SOURCE[f.change.replacement_source]}
                    </small>
                  )}
                </>
              ) : (
                <span className="ci-note">No replacement named</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Text from GitHub with `backticks` shown as code. */
function Ticks({ text }: { text: string }) {
  return (
    <>
      {text.split("`").map((part, i) =>
        i % 2 ? (
          <code key={i} translate="no">
            {part}
          </code>
        ) : (
          part
        ),
      )}
    </>
  );
}

/** Why upstream changed it: one line per upstream pull request, with one checked quote. */
function Why({ verdict }: { verdict: UpgradeVerdict }) {
  const seen = new Set<string>();
  const lines = (verdict.decisions || []).filter((d) => {
    if (!d.pr_url || seen.has(d.pr_url)) return false;
    seen.add(d.pr_url);
    return true;
  });
  if (!lines.length) return null;
  return (
    <>
      <dt>Why</dt>
      {lines.slice(0, 3).map((d) => {
        const key = d.change_key;
        const quote = d.quotes?.find((q) => q.source_kind !== "pr-title");
        const origin = d.deprecation;
        return (
          <dd key={d.pr_url}>
            <code translate="no">
              {key.parameter
                ? `${key.parameter}=`
                : key.symbol.split(".").pop()}
            </code>{" "}
            changed in{" "}
            <a href={d.pr_url!}>
              #{d.pr_number} <Ticks text={d.pr_title || ""} />
            </a>
            {origin?.pr_url && origin.pr_url !== d.pr_url && (
              <>
                , deprecated earlier in{" "}
                <a href={origin.pr_url}>#{origin.pr_number}</a>
              </>
            )}
            {d.reversal ? `. Later restored: ${d.reversal}` : ""}.
            {quote && (
              <span className="ci-quote">
                <Ticks text={quote.text.trim()} />{" "}
                <a href={quote.source_url}>Source</a>
              </span>
            )}
          </dd>
        );
      })}
    </>
  );
}

function AdvisoryLinks({ list }: { list: Advisory[] }) {
  return (
    <>
      {list.slice(0, 5).map((a, i) => (
        <span key={a.id}>
          {i > 0 && ", "}
          <a href={a.url}>{a.id}</a>
          {a.fixed ? ` (fixed in ${a.fixed})` : ""}
        </span>
      ))}
      {list.length > 5 ? ` and ${list.length - 5} more` : ""}
    </>
  );
}

function Advisories({ verdict }: { verdict: UpgradeVerdict }) {
  const checks = verdict.advisories || [];
  const at = (version: string): AdvisoryCheck | undefined =>
    checks.find((c) => c.version === version);
  const active = (c?: AdvisoryCheck) =>
    (c?.advisories || []).filter((a) => !a.withdrawn);
  const end = at(verdict.end),
    start = at(verdict.start);
  const remaining = active(end);
  const ids = new Set(remaining.map((a) => a.id));
  const resolved = active(start).filter((a) => !ids.has(a.id));
  return (
    <>
      <dt>Advisories</dt>
      <dd>
        {!end || end.status === "not-checked" ? (
          <>
            Not checked for {verdict.end}
            {end?.detail ? `: ${end.detail}` : ""}.
          </>
        ) : remaining.length ? (
          <>
            {plural(remaining.length, "known advisory", "known advisories")} for{" "}
            {verdict.end}: <AdvisoryLinks list={remaining} />.
          </>
        ) : (
          <>None known for {verdict.end} on OSV.dev.</>
        )}
        {resolved.length > 0 && (
          <span className="ci-quote">
            This upgrade leaves behind{" "}
            {plural(resolved.length, "advisory", "advisories")} affecting{" "}
            {verdict.start}: <AdvisoryLinks list={resolved} />.
          </span>
        )}
      </dd>
    </>
  );
}

function UncheckedList({ pull, items }: { pull: Source; items: Unchecked[] }) {
  return (
    <ul>
      {items.map((u, i) => (
        <li key={`${where(u.location)}-${i}`}>
          <span>
            <strong>
              {REASON[u.reason] || sentence(u.reason.replace(/-/g, " "))}
            </strong>{" "}
            · <CodeLink pull={pull} location={u.location} />
          </span>
          <span>{sentence(u.detail)}</span>
        </li>
      ))}
    </ul>
  );
}

function MoreDetail({
  pull,
  verdict,
}: {
  pull: Source;
  verdict: UpgradeVerdict;
}) {
  const findings = verdict.findings || [],
    unchecked = verdict.unchecked || [],
    limits = verdict.limits || [],
    coverage = verdict.coverage,
    release = verdict.release;
  const compare =
    release?.repository && release.start.tag && release.end.tag
      ? `https://github.com/${release.repository}/compare/${encodeURIComponent(release.start.tag)}...${encodeURIComponent(release.end.tag)}`
      : null;
  const messages = findings.filter((f) => f.change.message);
  const upstream = findings.filter((f) => f.change.before || f.change.after);
  return (
    <details className="ci-more">
      <summary>Coverage, upstream source and everything else</summary>
      <div className="ci-more-body">
        {coverage && (
          <section>
            <h3>Coverage</h3>
            <p>
              Compared {plural(coverage.usages, "use")} in{" "}
              {plural(coverage.files, "file")}:{" "}
              {coverage.checked.toLocaleString("en-GB")} followed in both
              releases, {coverage.unchecked.toLocaleString("en-GB")} could not
              be followed.{" "}
              {plural(coverage.upstream_changes, "upstream change")} between the
              two releases.
            </p>
          </section>
        )}
        {release && (
          <section>
            <h3>Releases</h3>
            <p>
              {compare ? (
                <a href={compare}>
                  {release.repository} {release.start.tag}…{release.end.tag}
                </a>
              ) : (
                <>
                  Upstream release range not located
                  {release.not_located ? `: ${release.not_located}` : ""}.
                </>
              )}
            </p>
          </section>
        )}
        {messages.length > 0 && (
          <section>
            <h3>In the library’s own words</h3>
            <ul>
              {messages.map((f, i) => (
                <li key={i}>
                  <span>“{f.change.message}”</span>
                  <span>
                    {verdict.package}{" "}
                    {f.change.message_version ??
                      (f.change.kind === "deprecated"
                        ? verdict.end
                        : verdict.start)}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
        {upstream.length > 0 && (
          <section>
            <h3>Where it is defined upstream</h3>
            <ul>
              {upstream.map((f, i) => (
                <li key={i}>
                  <span>
                    <code translate="no">{target(f.change)}</code>
                    {f.change.before &&
                      ` · ${where(f.change.before)} in ${verdict.start}`}
                    {f.change.after &&
                      ` · ${where(f.change.after)} in ${verdict.end}`}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
        {unchecked.length > 0 && verdict.verdict !== "not-checked" && (
          <section>
            <h3>Not checked</h3>
            <UncheckedList pull={pull} items={unchecked} />
          </section>
        )}
        {limits.length > 0 && (
          <section>
            <h3>
              {plural(limits.length, "other use")} could not be followed but
              touch nothing this upgrade changed
            </h3>
            <UncheckedList pull={pull} items={limits} />
          </section>
        )}
      </div>
    </details>
  );
}

export function PackageVerdict({
  pull,
  verdict,
  index,
  single,
  heading: Heading = "h2",
}: {
  pull: Source;
  verdict: UpgradeVerdict;
  index: number;
  single: boolean;
  heading?: "h2" | "h3";
}) {
  const unchecked = verdict.unchecked || [];
  const id = `package-${index}`;
  return (
    <section className="ci-package" aria-labelledby={`${id}-title`} id={id}>
      <div className="ci-package-head">
        <Heading id={`${id}-title`}>
          <code translate="no">{verdict.package}</code> {verdict.start}
          <span aria-hidden="true"> → </span>
          <span className="sr-only"> to </span>
          {verdict.end}
        </Heading>
        <VerdictLabel verdict={verdict.verdict} size="large" />
      </div>
      {!single && (
        <p className="ci-package-reason">{sentence(verdict.reason)}.</p>
      )}
      <Findings pull={pull} verdict={verdict} />
      {unchecked.length > 0 && verdict.verdict === "not-checked" && (
        <div className="ci-more-body">
          <p>
            These uses could not be followed and touch parts of{" "}
            {verdict.package} that changed in {verdict.end}. Review them by
            hand.
          </p>
          <UncheckedList pull={pull} items={unchecked} />
        </div>
      )}
      <dl className="ci-facts">
        <Why verdict={verdict} />
        <Advisories verdict={verdict} />
      </dl>
      <MoreDetail pull={pull} verdict={verdict} />
    </section>
  );
}

const PENDING_TEXT: Record<string, string> = {
  queued: "This pull request is waiting to be analysed.",
  running: "This pull request is being analysed. Refresh in a minute.",
  retrying: "The analysis hit a problem and will retry shortly.",
  diffed: "The dependency changes have been read; verdicts are not ready yet.",
  analysed: "Verdicts are being written.",
  reported: "No package verdicts were recorded for this pull request.",
  skipped:
    "This pull request does not change any Python dependency, so there is nothing to judge.",
  failed: "The analysis could not be completed.",
};

export function PullReport({
  pull,
  crumb,
}: {
  pull: PullDetail;
  /** Breadcrumb links, shown above the verdict. */
  crumb?: React.ReactNode;
}) {
  const manifest = pull.diff?.changed || [];
  const issues = pull.diff?.issues || [];
  const single = pull.verdicts.length === 1;
  return (
    <>
      <header className="ci-report-head">
        <p className="ci-crumb">
          {crumb}
          <span>
            #{pull.number} {pull.title || "Untitled pull request"}
          </span>
        </p>
        <h1 className="ci-report-verdict">
          <VerdictLabel
            verdict={pull.verdict}
            status={pull.status}
            size="large"
          />
          <span className="sr-only">
            {" "}
            for {pull.repository} pull request #{pull.number}
          </span>
        </h1>
        <p className="ci-report-reason">
          {pull.verdicts.length === 0
            ? PENDING_TEXT[pull.status] || PENDING_TEXT.queued
            : single
              ? `${sentence(pull.verdicts[0].reason)}.`
              : `${plural(pull.verdicts.length, "package")} changed. Each is judged below, the worst first.`}
        </p>
        <div className="ci-report-meta">
          <PackageChanges packages={pull.packages} />
          <span>
            Analysed{" "}
            <time dateTime={pull.updated_at}>
              {formatDate(pull.updated_at)}
            </time>{" "}
            at <code translate="no">{pull.head_sha.slice(0, 7)}</code>
          </span>
          <a className="ci-link" href={pullUrl(pull.repository, pull.number)}>
            Pull request on GitHub <ArrowOut />
          </a>
        </div>
        {pull.status === "failed" && pull.error && (
          <p className="ci-note">Failure category: {pull.error}</p>
        )}
      </header>
      {pull.verdicts.length > 1 && (
        <nav aria-label="Packages in this report">
          <ul className="ci-index">
            {pull.verdicts.map((v, i) => (
              <li key={`${v.package}-${i}`}>
                <a href={`#package-${i}`}>
                  <code translate="no">{v.package}</code>
                  <VerdictLabel verdict={v.verdict} />
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}
      {pull.verdicts.map((v, i) => (
        <PackageVerdict
          key={`${v.package}-${i}`}
          pull={pull}
          verdict={v}
          index={i}
          single={single}
        />
      ))}
      {(manifest.length > 0 || issues.length > 0) && (
        <details className="ci-more ci-manifest">
          <summary>Manifest changes</summary>
          <div className="ci-more-body">
            {manifest.length > 0 && (
              <ul>
                {manifest.map((m, i) => (
                  <li key={`${m.name}-${m.file}-${i}`}>
                    <span>
                      <code translate="no">{m.name}</code>{" "}
                      {m.old?.locked_version || m.old?.specifier || "unpinned"}
                      <span aria-hidden="true"> → </span>
                      <span className="sr-only"> to </span>
                      {m.new?.locked_version || m.new?.specifier || "unpinned"}
                    </span>
                    <span>{m.file}</span>
                  </li>
                ))}
              </ul>
            )}
            {issues.length > 0 && (
              <ul>
                {issues.map((issue, i) => (
                  <li key={i}>
                    <strong>{sentence(issue.reason.replace(/-/g, " "))}</strong>
                    <span>
                      {sentence(issue.detail)} ·{" "}
                      <code>{where(issue.location)}</code>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </details>
      )}
    </>
  );
}
