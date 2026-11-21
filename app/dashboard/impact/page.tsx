import { DashboardGate, PageHead } from "@/components/dashboard/tiles";
import { read, type Impact } from "@/lib/dashboard";
import { githubLine } from "@/lib/runs";
import { getSession, installationQuery } from "@/lib/session";
import { loadContext } from "@/lib/workspaces";

export const metadata = { title: "Impact · CodeIntent" };

const PACKAGE = /^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$/;
const VERSION = /^[A-Za-z0-9.+!_-]{1,64}$/;

const one = (value: string | string[] | undefined) =>
  (Array.isArray(value) ? value[0] : value)?.trim() || "";

export default async function ImpactPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const [context, query, session] = await Promise.all([
    loadContext(),
    searchParams,
    getSession(),
  ]);
  if (context.state !== "ok" || !session)
    return context.state !== "ok" ? (
      <DashboardGate gate={context} next="/dashboard/impact" />
    ) : null;
  const pkg = one(query.package);
  const version = one(query.version);
  const valid = PACKAGE.test(pkg) && (!version || VERSION.test(version));
  const scope =
    session.kind === "github" ? `&${installationQuery(session)}` : "";
  const result = valid
    ? await read<Impact>(
        `/app/graph/impact?package=${encodeURIComponent(pkg)}${version ? `&version=${encodeURIComponent(version)}` : ""}${scope}`,
      )
    : null;
  const impact = result?.state === "ok" ? result.data : null;
  const lines = impact?.lines || [];
  const unconfirmed = lines.filter((l) => !l.confirmed);
  return (
    <>
      <PageHead
        title="Impact"
        intro="Answered from your workspace graph in Neo4j: every change CodeIntent has found in a library, joined to every place your default branches use the same name and pass the same argument, in every repository."
      />
      <form className="ci-impact-form" method="get" role="search">
        <label>
          <span>Package</span>
          <input
            name="package"
            defaultValue={pkg}
            placeholder="httpx"
            required
            pattern="[A-Za-z0-9][A-Za-z0-9._\-]*"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label>
          <span>Version (optional)</span>
          <input
            name="version"
            defaultValue={version}
            placeholder="0.28.1"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <button className="ci-btn" type="submit">
          Search the graph
        </button>
      </form>
      {pkg && !valid && (
        <p className="ci-alert" role="alert">
          That is not a Python package name and version.
        </p>
      )}
      {result && result.state !== "ok" && (
        <p className="ci-alert" role="alert">
          The workspace graph is unavailable right now.
        </p>
      )}
      {impact && lines.length === 0 && (
        <p className="ci-note">
          No known change in <code>{impact.package}</code>
          {version && ` ${version}`} touches code in your repositories. A change
          becomes known once a pull request check or the daily scan has compared
          a release that contains it.
        </p>
      )}
      {impact && lines.length > 0 && (
        <>
          <p className="ci-impact-summary">
            <strong>{lines.length}</strong> line{lines.length === 1 ? "" : "s"}{" "}
            in <strong>{impact.repositories.length}</strong> repositor
            {impact.repositories.length === 1 ? "y" : "ies"}
            {unconfirmed.length > 0 && (
              <>
                , including <strong>{unconfirmed.length}</strong> found through
                the graph alone, in code no run has compared this upgrade for
              </>
            )}
            .
          </p>
          {impact.repositories.map((repo) => (
            <section key={repo} className="ci-tile ci-run-section">
              <h2>{repo}</h2>
              <ul className="ci-rows">
                {lines
                  .filter((l) => l.repository === repo)
                  .map((l) => (
                    <li
                      key={`${l.file}:${l.line}:${l.change}`}
                      className="ci-impact-line"
                    >
                      <div>
                        <a href={githubLine(repo, "HEAD", l.file, l.line)}>
                          <code translate="no">
                            {l.file}
                            {l.line ? `:${l.line}` : ""}
                          </code>
                        </a>
                        <span
                          className="ci-impact-tag"
                          data-confirmed={l.confirmed ? "" : undefined}
                        >
                          {l.confirmed ? "Compared" : "Found through the graph"}
                        </span>
                      </div>
                      {l.code && (
                        <pre className="ci-break-code">
                          <code translate="no">{l.code}</code>
                        </pre>
                      )}
                      <p>
                        <code translate="no">{l.change}</code> changed in{" "}
                        {l.version}
                        {l.replacement && (
                          <>
                            ; use{" "}
                            <code className="ci-instead">{l.replacement}</code>
                          </>
                        )}
                        {l.locked && (
                          <span className="ci-note">
                            {" "}
                            · this repository locks {l.locked}
                          </span>
                        )}
                      </p>
                    </li>
                  ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </>
  );
}
