import Link from "next/link";
import { DashboardGate, PageHead } from "@/components/dashboard/tiles";
import {
  read,
  type EcosystemStats,
  type Exposure,
  type PackageInfo,
} from "@/lib/dashboard";
import { getSession, installationQuery } from "@/lib/session";
import { loadContext, repoHref } from "@/lib/workspaces";

export const metadata = { title: "Ecosystem · CodeIntent" };

const PACKAGE = /^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$/;
const LABEL: Record<string, string> = {
  Package: "packages",
  Release: "releases",
  SourceRepo: "open-source repositories",
  Advisory: "advisories",
  APIChange: "API changes",
  UpstreamPR: "upstream PRs",
  Module: "library files",
};

const number = (n: number | null | undefined) =>
  typeof n === "number" ? n.toLocaleString("en-GB") : "—";

/** The public dependency graph: every package your repositories and indexed projects use, transitively. */
export default async function Ecosystem({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [context, query, session] = await Promise.all([
    loadContext(),
    searchParams,
    getSession(),
  ]);
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/ecosystem" />;
  const pkg = typeof query.package === "string" ? query.package.trim() : "";
  const valid = PACKAGE.test(pkg);
  const scope =
    session?.kind === "github" ? `?${installationQuery(session)}` : "";
  const [stats, info, exposure] = await Promise.all([
    read<EcosystemStats>("/app/graph/ecosystem"),
    valid
      ? read<PackageInfo>(
          `/app/graph/packages/${encodeURIComponent(pkg)}${scope}`,
        )
      : null,
    read<{ advisories: Exposure[] }>(`/app/graph/exposure${scope}`),
  ]);
  const data = info?.state === "ok" ? info.data : null;
  const mine = (data?.dependents || []).filter((d) => d.kind === "Repository");
  const projects = (data?.dependents || []).filter(
    (d) => d.kind === "SourceRepo",
  );
  const transitive =
    exposure.state === "ok"
      ? exposure.data.advisories.filter((a) => !a.direct)
      : [];
  return (
    <>
      <PageHead
        title="Ecosystem"
        intro="Every Python package your repositories and the indexed open-source projects depend on, directly or through other packages: releases, the resolved dependency tree between them, the GitHub repository behind each one and its known advisories. Stored as one graph in Neo4j."
      />
      {stats.state === "ok" && (
        <section className="ci-tile ci-eco-stats" aria-label="Graph size">
          {Object.entries(stats.data.nodes)
            .filter(([, n]) => n > 0)
            .map(([label, n]) => (
              <div key={label}>
                <strong>{number(n)}</strong>
                <span>{LABEL[label] || label}</span>
              </div>
            ))}
          <div>
            <strong>{number(stats.data.dependency_edges)}</strong>
            <span>dependency edges</span>
          </div>
          <div>
            <strong>
              {number(
                stats.data.projects.filter((p) => p.status === "indexed")
                  .length,
              )}
            </strong>
            <span>projects indexed</span>
          </div>
          {(stats.data.releases.queued || 0) > 0 && (
            <p className="ci-note">
              {number(stats.data.releases.queued)} releases are still being
              indexed.
            </p>
          )}
        </section>
      )}
      <form className="ci-impact-form" method="get" role="search">
        <label>
          <span>Package</span>
          <input
            name="package"
            defaultValue={pkg}
            placeholder="urllib3"
            required
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <button className="ci-btn" type="submit">
          Look it up
        </button>
      </form>
      {pkg && !valid && (
        <p className="ci-alert" role="alert">
          That is not a Python package name.
        </p>
      )}
      {info && info.state !== "ok" && (
        <p className="ci-alert" role="alert">
          The ecosystem graph is unavailable right now.
        </p>
      )}
      {data && !data.known && (
        <p className="ci-note">
          <code>{data.package}</code> is not in the graph yet. It is added when
          a watched repository or an indexed project depends on it.
        </p>
      )}
      {data?.known && (
        <div className="ci-run-grid">
          <section className="ci-tile" aria-labelledby="pkg">
            <h2 id="pkg">
              <code>{data.package}</code>
            </h2>
            {data.source ? (
              <dl className="ci-facts">
                <div>
                  <dt>Source</dt>
                  <dd>
                    <a href={data.source.url}>{data.source.name}</a>
                  </dd>
                </div>
                <div>
                  <dt>Stars</dt>
                  <dd>{number(data.source.stars)}</dd>
                </div>
                <div>
                  <dt>Licence</dt>
                  <dd>{data.source.license || "—"}</dd>
                </div>
                <div>
                  <dt>OpenSSF Scorecard</dt>
                  <dd>
                    {data.source.scorecard ?? "—"}
                    {data.source.maintained === 0 &&
                      " · not actively maintained"}
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="ci-note">No source repository is linked.</p>
            )}
            <h3>Depends on</h3>
            <p className="ci-chips-line">
              {(data.needs || []).length
                ? (data.needs || []).map((n) => (
                    <Link
                      key={n}
                      href={`/dashboard/ecosystem?package=${encodeURIComponent(n)}`}
                    >
                      {n}
                    </Link>
                  ))
                : "Nothing"}
            </p>
            <h3>Needed by</h3>
            <p className="ci-chips-line">
              {(data.needed_by || []).length
                ? (data.needed_by || []).slice(0, 30).map((n) => (
                    <Link
                      key={n}
                      href={`/dashboard/ecosystem?package=${encodeURIComponent(n)}`}
                    >
                      {n}
                    </Link>
                  ))
                : "No indexed package"}
            </p>
            {(data.advisories || []).length > 0 && (
              <>
                <h3>Advisories on indexed releases</h3>
                <ul className="ci-agent-steps">
                  {(data.advisories || []).slice(0, 8).map((a) => (
                    <li key={a.name}>
                      {a.url ? <a href={a.url}>{a.name}</a> : a.name}
                      {a.fixed ? `, fixed in ${a.fixed}` : ""}
                      {a.summary ? ` · ${a.summary}` : ""}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {(data.changes || []).length > 0 && (
              <>
                <h3>API changes CodeIntent has found</h3>
                <ul className="ci-agent-steps">
                  {(data.changes || []).map((c) => (
                    <li key={`${c.name}-${c.version}`}>
                      <code>{c.name}</code> {c.kind.replaceAll("-", " ")} in{" "}
                      {c.version}
                      {c.replacement ? `; use ${c.replacement}` : ""}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
          <section className="ci-tile" aria-labelledby="dependents">
            <h2 id="dependents">Who depends on it</h2>
            {mine.length > 0 && (
              <>
                <h3>Your repositories</h3>
                <ul className="ci-agent-steps">
                  {mine.map((d) => (
                    <li key={d.name}>
                      <Link
                        href={`${repoHref(d.name)}?why=${encodeURIComponent(data.package)}#dependencies`}
                      >
                        {d.name}
                      </Link>{" "}
                      {d.hops === 0
                        ? "locks it"
                        : `through ${d.via.join(", ")} (${d.hops} step${d.hops === 1 ? "" : "s"})`}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <h3>Open-source projects</h3>
            {projects.length ? (
              <ul className="ci-agent-steps">
                {projects.slice(0, 40).map((d) => (
                  <li key={d.name}>
                    <a href={`https://github.com/${d.name}`}>{d.name}</a>
                    {d.stars ? ` · ★ ${number(d.stars)}` : ""} ·{" "}
                    {d.hops === 0 ? "directly" : `through ${d.via.join(", ")}`}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="ci-note">None of the indexed projects.</p>
            )}
          </section>
        </div>
      )}
      {!pkg && transitive.length > 0 && (
        <section
          className="ci-tile ci-run-section"
          aria-labelledby="transitive"
        >
          <h2 id="transitive">Advisories reached through other packages</h2>
          <p className="ci-note">
            Releases your repositories lock without declaring them, with a known
            advisory, and the declared dependency that pulls each one in.
          </p>
          <ul className="ci-rows">
            {transitive.slice(0, 20).map((a) => (
              <li
                key={`${a.repository}-${a.package}-${a.advisory}`}
                className="ci-row"
              >
                <span className="ci-verdict">Known advisory</span>
                <span className="ci-row-title">
                  <strong>
                    <code>
                      {a.package} {a.version}
                    </code>{" "}
                    in {a.repository}
                    {a.pulled_in_by.length
                      ? `, pulled in by ${a.pulled_in_by.join(", ")}`
                      : ""}
                  </strong>
                  <span>
                    {a.url ? <a href={a.url}>{a.advisory}</a> : a.advisory}
                    {a.fixed ? `, fixed in ${a.fixed}` : ""}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
