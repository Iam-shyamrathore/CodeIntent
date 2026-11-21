import { ArrowUpRight } from "lucide-react";
import { VerdictLabel } from "./verdict";
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

const KIND: Record<Change["kind"], string> = {
  removed: "Removed",
  "parameter-removed": "Argument removed",
  "parameter-required": "Argument now required",
  "parameter-moved": "Argument moved",
  "default-changed": "Default changed",
  deprecated: "Deprecated",
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
  message: "named in the library’s deprecation message",
  "message-unverified":
    "suggested by the library’s message; not confirmed in the new release",
  signature: "found in the new release’s signature",
};
const VISIBLE_LOCATIONS = 12;

const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const plural = (n: number, one: string, many = `${one}s`) =>
  `${n.toLocaleString("en-GB")} ${n === 1 ? one : many}`;
const where = (l: Location) =>
  `${l.file}${l.line ? `:${l.line}` : ""}${l.line && l.column ? `:${l.column}` : ""}`;

function CodeLink({
  pull,
  location,
}: {
  pull: PullDetail;
  location: Location;
}) {
  const href = `https://github.com/${pull.repository}/blob/${pull.head_sha}/${location.file
    .split("/")
    .map(encodeURIComponent)
    .join("/")}${location.line ? `#L${location.line}` : ""}`;
  return (
    <a className="code-location" href={href}>
      {where(location)}
    </a>
  );
}

function Locations({ pull, items }: { pull: PullDetail; items: Location[] }) {
  const shown = items.slice(0, VISIBLE_LOCATIONS),
    rest = items.slice(VISIBLE_LOCATIONS);
  return (
    <>
      <ul className="location-list">
        {shown.map((l, i) => (
          <li key={`${where(l)}-${i}`}>
            <CodeLink pull={pull} location={l} />
          </li>
        ))}
      </ul>
      {rest.length > 0 && (
        <details className="report-more">
          <summary>{plural(rest.length, "more place")}</summary>
          <ul className="location-list">
            {rest.map((l, i) => (
              <li key={`${where(l)}-${i}`}>
                <CodeLink pull={pull} location={l} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

function FindingEntry({
  pull,
  verdict,
  finding,
}: {
  pull: PullDetail;
  verdict: UpgradeVerdict;
  finding: Finding;
}) {
  const { change } = finding;
  return (
    <li className="finding">
      <div className="finding-head">
        <VerdictLabel verdict={finding.severity} />
        <span className="finding-kind">{KIND[change.kind]}</span>
        {finding.guarded && (
          <span className="finding-kind">Behind an import fallback</span>
        )}
      </div>
      <h4>
        <code>
          {publicSymbol(change.symbol)}
          {change.parameter ? `(${change.parameter}=)` : ""}
        </code>
      </h4>
      <p className="finding-detail">{change.detail}.</p>
      <dl className="finding-facts">
        <div>
          <dt>Your code</dt>
          <dd>
            <Locations pull={pull} items={finding.locations} />
          </dd>
        </div>
        {(change.before || change.after) && (
          <div>
            <dt>Upstream</dt>
            <dd>
              {change.before && (
                <span className="upstream-location">
                  <code>{where(change.before)}</code> in {verdict.start}
                </span>
              )}
              {change.after && (
                <span className="upstream-location">
                  <code>{where(change.after)}</code> in {verdict.end}
                </span>
              )}
            </dd>
          </div>
        )}
        {change.replacement && (
          <div>
            <dt>Use instead</dt>
            <dd>
              <code className="replacement">{change.replacement}</code>
              {change.replacement_source && (
                <span className="fact-note">
                  {REPLACEMENT_SOURCE[change.replacement_source]}
                </span>
              )}
            </dd>
          </div>
        )}
      </dl>
      {change.message && (
        <figure className="library-message">
          <blockquote>
            <p>
              <mark>“{change.message}”</mark>
            </p>
          </blockquote>
          <figcaption>
            {verdict.package}{" "}
            {change.message_version ??
              (change.kind === "deprecated" ? verdict.end : verdict.start)}
            , in its own words
          </figcaption>
        </figure>
      )}
    </li>
  );
}

function UncheckedList({
  pull,
  items,
}: {
  pull: PullDetail;
  items: Unchecked[];
}) {
  return (
    <ul className="unchecked-list">
      {items.map((u, i) => (
        <li key={`${where(u.location)}-${i}`}>
          <strong>
            {REASON[u.reason] || sentence(u.reason.replace(/-/g, " "))}
          </strong>
          <span>{sentence(u.detail)}</span>
          <CodeLink pull={pull} location={u.location} />
        </li>
      ))}
    </ul>
  );
}

function AdvisoryItem({ advisory }: { advisory: Advisory }) {
  return (
    <li>
      <a href={advisory.url}>
        {advisory.id} <ArrowUpRight size={12} aria-hidden="true" />
      </a>
      {advisory.summary && <span>{advisory.summary}</span>}
      <small>
        {[
          advisory.severity && `Severity ${advisory.severity.toLowerCase()}`,
          advisory.fixed
            ? `Fixed in ${advisory.fixed}`
            : "No fixed version listed",
          advisory.aliases?.length ? advisory.aliases.join(", ") : "",
        ]
          .filter(Boolean)
          .join(" · ")}
      </small>
    </li>
  );
}

function Advisories({ verdict }: { verdict: UpgradeVerdict }) {
  const checks = verdict.advisories || [];
  if (!checks.length) return null;
  const at = (version: string): AdvisoryCheck | undefined =>
    checks.find((c) => c.version === version);
  const active = (c?: AdvisoryCheck) =>
    (c?.advisories || []).filter((a) => !a.withdrawn);
  const start = at(verdict.start),
    end = at(verdict.end);
  const remaining = active(end);
  const ids = new Set(remaining.map((a) => a.id));
  const resolved = active(start).filter((a) => !ids.has(a.id));
  return (
    <section
      className="report-block"
      aria-label={`${verdict.package} advisories`}
    >
      <h3>Known advisories</h3>
      {!end || end.status === "not-checked" ? (
        <p className="report-note">
          Advisories for {verdict.package} {verdict.end} were not checked
          {end?.detail ? `: ${end.detail}` : ""}.
        </p>
      ) : remaining.length ? (
        <>
          <p className="report-note">
            OSV.dev lists {plural(remaining.length, "advisory", "advisories")}{" "}
            affecting {verdict.package} {verdict.end}, the version this pull
            request moves to.
          </p>
          <ul className="advisory-list">
            {remaining.map((a) => (
              <AdvisoryItem key={a.id} advisory={a} />
            ))}
          </ul>
        </>
      ) : (
        <p className="report-note">
          OSV.dev lists no advisories for {verdict.package} {verdict.end}.
        </p>
      )}
      {start?.status === "not-checked" && (
        <p className="report-note">
          Advisories for {verdict.start} were not checked
          {start.detail ? `: ${start.detail}` : ""}.
        </p>
      )}
      {resolved.length > 0 && (
        <>
          <p className="report-note">
            {plural(resolved.length, "advisory", "advisories")} affecting{" "}
            {verdict.start} do not list {verdict.end} as affected:
          </p>
          <ul className="advisory-list">
            {resolved.map((a) => (
              <AdvisoryItem key={a.id} advisory={a} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Release({ verdict }: { verdict: UpgradeVerdict }) {
  const release = verdict.release;
  if (!release) return null;
  const { repository, start, end } = release;
  const compare =
    repository && start.tag && end.tag
      ? `https://github.com/${repository}/compare/${encodeURIComponent(start.tag)}...${encodeURIComponent(end.tag)}`
      : null;
  return (
    <p className="report-note release-line">
      {compare ? (
        <a href={compare}>
          Upstream changes {start.tag}…{end.tag} in {repository}
          <ArrowUpRight size={12} aria-hidden="true" />
        </a>
      ) : (
        <>
          Upstream release range not located
          {release.not_located ? `: ${release.not_located}` : ""}.
          {repository && (
            <>
              {" "}
              <a href={`https://github.com/${repository}/releases`}>
                {repository} releases
                <ArrowUpRight size={12} aria-hidden="true" />
              </a>
            </>
          )}
        </>
      )}
    </p>
  );
}

function PackageVerdict({
  pull,
  verdict,
  index,
}: {
  pull: PullDetail;
  verdict: UpgradeVerdict;
  index: number;
}) {
  const findings = verdict.findings || [],
    unchecked = verdict.unchecked || [],
    limits = verdict.limits || [],
    coverage = verdict.coverage;
  const id = `package-${index}`;
  return (
    <section className="package-verdict" aria-labelledby={id}>
      <div className="package-verdict-head">
        <h2 id={id}>
          <code>{verdict.package}</code> {verdict.start}
          <span aria-hidden="true"> → </span>
          <span className="sr-only"> to </span>
          {verdict.end}
        </h2>
        <VerdictLabel verdict={verdict.verdict} size="large" />
      </div>
      <p className="package-reason">{sentence(verdict.reason)}.</p>
      {coverage && (
        <p className="coverage-line">
          Compared {plural(coverage.usages, "use")} in{" "}
          {plural(coverage.files, "file")} ·{" "}
          {coverage.checked.toLocaleString("en-GB")} followed in both releases ·{" "}
          {coverage.unchecked.toLocaleString("en-GB")} could not be followed ·{" "}
          {plural(coverage.upstream_changes, "upstream change")}
        </p>
      )}
      <Release verdict={verdict} />
      {findings.length > 0 && (
        <section
          className="report-block"
          aria-label={`${verdict.package} findings`}
        >
          <h3>What changes for your code</h3>
          <ol className="finding-list">
            {findings.map((f, i) => (
              <FindingEntry key={i} pull={pull} verdict={verdict} finding={f} />
            ))}
          </ol>
        </section>
      )}
      {unchecked.length > 0 && (
        <section
          className="report-block"
          aria-label={`${verdict.package} not checked`}
        >
          <h3>Not checked</h3>
          <p className="report-note">
            These uses could not be followed, and they touch parts of{" "}
            {verdict.package} that changed in {verdict.end}. Review them by
            hand.
          </p>
          <UncheckedList pull={pull} items={unchecked} />
        </section>
      )}
      {limits.length > 0 && (
        <details className="report-more report-limits">
          <summary>
            {plural(limits.length, "other use")} could not be followed but touch
            nothing this upgrade changed
          </summary>
          <UncheckedList pull={pull} items={limits} />
        </details>
      )}
      <Advisories verdict={verdict} />
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

export function PullReport({ pull }: { pull: PullDetail }) {
  const manifest = pull.diff?.changed || [];
  const issues = pull.diff?.issues || [];
  return (
    <>
      <div className="collection-intro report-intro">
        <div>
          <p className="collection-breadcrumb">
            {pull.repository} · pull request #{pull.number}
          </p>
          <h1 className="console-title">
            {pull.title || `Pull request #${pull.number}`}
          </h1>
          <div className="report-summary">
            <VerdictLabel
              verdict={pull.verdict}
              status={pull.status}
              size="large"
            />
            <span>
              {pull.verdicts.length
                ? plural(pull.verdicts.length, "package") + " judged"
                : ""}
            </span>
          </div>
          <p className="pull-meta">
            Analysed{" "}
            <time dateTime={pull.updated_at}>
              {formatDate(pull.updated_at)}
            </time>{" "}
            at <code>{pull.head_sha.slice(0, 7)}</code> ·{" "}
            <a href={pullUrl(pull.repository, pull.number)}>
              Open the pull request on GitHub
              <ArrowUpRight size={12} aria-hidden="true" />
            </a>
          </p>
        </div>
      </div>
      {pull.verdicts.length > 1 && (
        <nav className="report-index" aria-label="Packages in this report">
          <ul>
            {pull.verdicts.map((v, i) => (
              <li key={`${v.package}-${i}`}>
                <a href={`#package-${i}`}>
                  <code>{v.package}</code> {v.start} → {v.end}
                </a>
                <VerdictLabel verdict={v.verdict} />
              </li>
            ))}
          </ul>
        </nav>
      )}
      {pull.verdicts.length === 0 && (
        <div className="console-empty" role="status">
          <p>{PENDING_TEXT[pull.status] || PENDING_TEXT.queued}</p>
          {pull.status === "failed" && pull.error && (
            <p className="report-note">Failure category: {pull.error}</p>
          )}
        </div>
      )}
      {pull.verdicts.map((v, i) => (
        <PackageVerdict
          key={`${v.package}-${i}`}
          pull={pull}
          verdict={v}
          index={i}
        />
      ))}
      {(manifest.length > 0 || issues.length > 0) && (
        <section
          className="report-block manifest-block"
          aria-labelledby="manifest-heading"
        >
          <h2 id="manifest-heading">Manifest changes</h2>
          {manifest.length > 0 && (
            <ul className="manifest-list">
              {manifest.map((m, i) => (
                <li key={`${m.name}-${m.file}-${i}`}>
                  <code>{m.name}</code>
                  <span>
                    {m.old?.locked_version || m.old?.specifier || "unpinned"}
                    <span aria-hidden="true"> → </span>
                    <span className="sr-only"> to </span>
                    {m.new?.locked_version || m.new?.specifier || "unpinned"}
                  </span>
                  <small>{m.file}</small>
                </li>
              ))}
            </ul>
          )}
          {issues.length > 0 && (
            <>
              <p className="report-note">
                Parts of the manifests could not be read:
              </p>
              <ul className="unchecked-list">
                {issues.map((issue, i) => (
                  <li key={i}>
                    <strong>{sentence(issue.reason.replace(/-/g, " "))}</strong>
                    <span>{sentence(issue.detail)}</span>
                    <code>{where(issue.location)}</code>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
      <p className="collection-footnote">
        Verdicts come from fixed rules over a static comparison of both releases
        against this revision; no model is involved. “No known impact” means
        everything that could be followed was compared and nothing relevant
        changed. It is not a guarantee.
      </p>
    </>
  );
}
