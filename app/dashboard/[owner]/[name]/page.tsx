import Link from "next/link";
import { notFound } from "next/navigation";
import { ConsoleHeader } from "@/components/console-header";
import { SignInPanel } from "@/components/auth-panel";
import { SiteFooter } from "@/components/site/footer";
import { ArrowOut, ArrowRight } from "@/components/site/icons";
import { Upcoming } from "@/components/upcoming";
import { PackageChanges, VerdictLabel } from "@/components/verdict";
import {
  canAccessInstallation,
  getSession,
  installationQuery,
  type Session,
} from "@/lib/session";
import {
  formatDate,
  GITHUB_NAME,
  pullUrl,
  read,
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

function Shell({
  session,
  next,
  children,
}: {
  session: Session | null;
  next: string;
  children: React.ReactNode;
}) {
  return (
    <div className="ci ci-page">
      <ConsoleHeader current="dashboard" session={session} next={next} />
      <main className="ci-main" id="main">
        {children}
      </main>
      <SiteFooter />
    </div>
  );
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
      <Shell session={null} next={base}>
        <div className="ci-head">
          <div>
            <p className="ci-crumb">
              <Link href="/dashboard">Dashboard</Link>
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
      </Shell>
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
  const [result, upcoming] = await Promise.all([
    read<RepositoryPulls>(
      `${path}/pulls?limit=25${cursor ? `&cursor=${cursor}` : ""}${scope}`,
    ),
    cursor
      ? null
      : read<RepositoryScan>(
          `${path}/upcoming${scope ? `?${scope.slice(1)}` : ""}`,
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
    <Shell session={session} next={base}>
      <div className="ci-head">
        <div>
          <p className="ci-crumb">
            <Link href="/dashboard">Dashboard</Link>
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
    </Shell>
  );
}
