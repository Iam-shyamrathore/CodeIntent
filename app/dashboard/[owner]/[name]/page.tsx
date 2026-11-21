import Link from "next/link";
import { notFound } from "next/navigation";
import { SignInPanel } from "@/components/auth-panel";
import { ArrowOut, ArrowRight } from "@/components/site/icons";
import { DependencyGraphLazy } from "@/components/dependency-graph-lazy";
import { Upcoming } from "@/components/upcoming";
import { PackageChanges, VerdictLabel } from "@/components/verdict";
import {
  canAccessInstallation,
  getSession,
  installationQuery,
} from "@/lib/session";
import {
  formatDate,
  GITHUB_NAME,
  pullUrl,
  read,
  type DependencyTree,
  type Exposure,
  type RepositoryPulls,
  type RepositoryScan,
} from "@/lib/dashboard";

type Props = {
  params: Promise<{ owner: string; name: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

export async function generateMetadata({ params }: Props) {
  const { owner, name } = await params;
  return { title: `${owner}/${name} · CodeIntent` };
}

export default async function RepositoryDashboard({
  params,
  searchParams,
}: Props) {
  const [{ owner, name }, query, session] = await Promise.all([
    params,
    searchParams,
    getSession(),
  ]);
  if (!GITHUB_NAME.test(owner) || !GITHUB_NAME.test(name)) notFound();
  const base = `/dashboard/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`;
  // Signed out: the same prompt for every repository, so it says nothing about which exist.
  if (!session)
    return (
      <>
        <div className="ci-head">
          <div>
            <p className="ci-crumb">
              <Link href="/dashboard/repositories">Repositories</Link>
              <span aria-hidden="true">/</span>
              {owner}/{name}
            </p>
            <h1 className="ci-title">Dependency pull requests</h1>
          </div>
        </div>
        <SignInPanel
          next={base}
          title="Sign in to see this repository"
          body="Dependency pull requests are listed for people with access to the repository’s installation of the GitHub App."
          operatorPurpose="For the deployment operator: the workspace key shows every repository."
        />
      </>
    );
  const cursor =
    typeof query.cursor === "string" &&
    /^[A-Za-z0-9_-]{1,200}$/.test(query.cursor)
      ? query.cursor
      : "";
  // Repositories outside the user's installations are "not found", never "forbidden".
  if (session.kind === "github" && session.installations.length === 0)
    notFound();
  const scope =
    session.kind === "github" ? `&${installationQuery(session)}` : "";
  const path = `/app/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`;
  const why =
    typeof query.why === "string" &&
    /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(query.why)
      ? query.why
      : "";
  const graphPath = `/app/graph/dependencies/${encodeURIComponent(owner)}/${encodeURIComponent(name)}?depth=4${why ? `&why=${encodeURIComponent(why)}` : ""}${scope}`;
  const [result, upcoming, dependencies, exposure] = await Promise.all([
    read<RepositoryPulls>(
      `${path}/pulls?limit=25${cursor ? `&cursor=${cursor}` : ""}${scope}`,
    ),
    cursor
      ? null
      : read<RepositoryScan>(
          `${path}/upcoming${scope ? `?${scope.slice(1)}` : ""}`,
        ),
    cursor ? null : read<DependencyTree>(graphPath),
    cursor
      ? null
      : read<{ advisories: Exposure[] }>(
          `/app/graph/exposure${scope ? `?${scope.slice(1)}` : ""}`,
        ),
  ]);
  if (
    result.state === "missing" ||
    (result.state === "ok" &&
      !canAccessInstallation(session, result.data.repository.installation_id))
  )
    notFound();
  const fullName =
    result.state === "ok"
      ? result.data.repository.full_name
      : `${owner}/${name}`;
  return (
    <>
      <div className="ci-head">
        <div>
          <p className="ci-crumb">
            <Link href="/dashboard/repositories">Repositories</Link>
            <span aria-hidden="true">/</span>
            {cursor ? "Older pull requests" : "Dependency pull requests"}
          </p>
          <h1 className="ci-title">
            {fullName.split("/")[0]}/<wbr />
            {fullName.split("/")[1]}
          </h1>
        </div>
        <a className="ci-link" href={`https://github.com/${fullName}/pulls`}>
          Pull requests on GitHub <ArrowOut />
        </a>
      </div>
      {result.state === "unavailable" ? (
        <p role="alert" className="ci-alert">
          The verdict service is unavailable. Verdicts on GitHub are unaffected;
          try this page again shortly.
        </p>
      ) : (
        <section className="ci-tile" aria-label="Dependency pull requests">
          {result.data.pulls.length === 0 ? (
            <p className="ci-note">
              {cursor
                ? "There are no older pull requests."
                : "No dependency pull request has been analysed here yet. Open one, or wait for Dependabot or Renovate."}
            </p>
          ) : (
            <ul className="ci-rows">
              {result.data.pulls.map((pull) => (
                <li key={pull.id} className="ci-row">
                  <VerdictLabel verdict={pull.verdict} status={pull.status} />
                  <div className="ci-row-title">
                    <strong>
                      <Link href={`/pulls/${pull.id}`}>
                        #{pull.number} {pull.title || "Untitled pull request"}
                      </Link>
                    </strong>
                    <PackageChanges packages={pull.packages} />
                  </div>
                  <span className="ci-row-meta">
                    <time dateTime={pull.created_at}>
                      {formatDate(pull.created_at)}
                    </time>{" "}
                    ·{" "}
                    <a
                      className="ci-link"
                      href={pullUrl(pull.repository, pull.number)}
                    >
                      GitHub <ArrowOut size={12} />
                    </a>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {result.state === "ok" && (cursor || result.data.next_cursor) && (
        <nav className="ci-tg-actions ci-pager" aria-label="Pages">
          {cursor && (
            <Link className="ci-btn-quiet" href={base}>
              Newest
            </Link>
          )}
          {result.data.next_cursor && (
            <Link
              className="ci-btn-quiet"
              href={`${base}?cursor=${result.data.next_cursor}`}
            >
              Older pull requests <ArrowRight />
            </Link>
          )}
        </nav>
      )}
      {result.state === "ok" && upcoming && (
        <Upcoming
          repository={fullName}
          result={upcoming.state === "ok" ? upcoming.data.scan : "unavailable"}
        />
      )}
      {result.state === "ok" && dependencies && (
        <section
          className="ci-run-section"
          id="dependencies"
          aria-labelledby="deps-title"
        >
          <div className="ci-tile-head">
            <h2 id="deps-title" className="ci-section-title">
              Dependency graph
            </h2>
            <span className="ci-row-meta">Neo4j ecosystem graph</span>
          </div>
          {dependencies.state !== "ok" ? (
            <p className="ci-note" role="status">
              The dependency graph is unavailable right now.
            </p>
          ) : dependencies.data.nodes.length === 0 ? (
            <p className="ci-note">
              The graph fills in after this repository’s first scan: every
              locked release, then what each one pulls in.
            </p>
          ) : (
            <>
              {dependencies.data.why && (
                <div className="ci-why">
                  <p>
                    <strong>
                      Why is <code>{dependencies.data.why.package}</code>{" "}
                      installed?
                    </strong>
                  </p>
                  {dependencies.data.why.chains.length ? (
                    <ol>
                      {dependencies.data.why.chains.map((chain, i) => (
                        <li key={i}>
                          {chain.map((step, j) => (
                            <span key={j}>
                              {j > 0 && <span aria-hidden="true"> → </span>}
                              <code translate="no">{step}</code>
                            </span>
                          ))}
                          {chain.length === 1 && " (declared directly)"}
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="ci-note">
                      It is not in this repository’s known dependency tree.
                    </p>
                  )}
                </div>
              )}
              <DependencyGraphLazy
                tree={dependencies.data}
                base={`/dashboard/${owner}/${name}`}
                exposed={
                  exposure?.state === "ok"
                    ? exposure.data.advisories
                        .filter((a) => a.repository === fullName)
                        .map((a) => a.package)
                    : []
                }
              />
              {exposure?.state === "ok" &&
                exposure.data.advisories.some(
                  (a) => a.repository === fullName,
                ) && (
                  <ul className="ci-rows ci-exposure">
                    {exposure.data.advisories
                      .filter((a) => a.repository === fullName)
                      .map((a) => (
                        <li
                          key={`${a.package}-${a.advisory}`}
                          className="ci-row"
                        >
                          <span className="ci-verdict">Known advisory</span>
                          <span className="ci-row-title">
                            <strong>
                              <code translate="no">
                                {a.package} {a.version}
                              </code>
                              {a.direct
                                ? " (declared)"
                                : a.pulled_in_by.length
                                  ? ` (pulled in by ${a.pulled_in_by.join(", ")})`
                                  : " (transitive)"}
                            </strong>
                            <span>
                              {a.url ? (
                                <a href={a.url}>{a.advisory}</a>
                              ) : (
                                a.advisory
                              )}
                              {a.fixed ? `, fixed in ${a.fixed}` : ""}
                              {a.summary ? ` · ${a.summary}` : ""}
                            </span>
                          </span>
                        </li>
                      ))}
                  </ul>
                )}
            </>
          )}
        </section>
      )}
    </>
  );
}
