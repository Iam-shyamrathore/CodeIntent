import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowRight, ArrowUpRight } from "lucide-react";
import { ConsoleHeader } from "@/components/console-header";
import { OperatorSignIn } from "@/components/operator-access";
import { PackageChanges, VerdictLabel } from "@/components/verdict";
import { isOperator } from "@/lib/session";
import {
  formatDate,
  GITHUB_NAME,
  pullUrl,
  read,
  type RepositoryPulls,
} from "@/lib/dashboard";

type Props = {
  params: Promise<{ owner: string; name: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

export async function generateMetadata({ params }: Props) {
  const { owner, name } = await params;
  return { title: `${owner}/${name} · Dashboard · Code Intent` };
}

export default async function RepositoryDashboard({
  params,
  searchParams,
}: Props) {
  const [{ owner, name }, query, operator] = await Promise.all([
    params,
    searchParams,
    isOperator(),
  ]);
  if (!GITHUB_NAME.test(owner) || !GITHUB_NAME.test(name)) notFound();
  if (!operator)
    return (
      <div className="repository-page">
        <ConsoleHeader current="dashboard" />
        <main className="collection-main" id="main">
          <div className="collection-intro">
            <div>
              <p className="collection-breadcrumb">
                Workspace / Dashboard / {owner}/{name}
              </p>
              <h1>Dependency pull requests</h1>
            </div>
          </div>
          <OperatorSignIn purpose="Operator access is required to see this repository’s pull requests." />
        </main>
      </div>
    );
  const cursor =
    typeof query.cursor === "string" &&
    /^[A-Za-z0-9_-]{1,200}$/.test(query.cursor)
      ? query.cursor
      : "";
  const result = await read<RepositoryPulls>(
    `/app/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/pulls?limit=25${cursor ? `&cursor=${cursor}` : ""}`,
  );
  if (result.state === "missing") notFound();
  const base = `/dashboard/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`;
  return (
    <div className="repository-page">
      <ConsoleHeader current="dashboard" operator />
      <main className="collection-main" id="main">
        <div className="collection-intro">
          <div>
            <p className="collection-breadcrumb">
              <Link href="/dashboard">Workspace / Dashboard</Link> / {owner}/
              {name}
            </p>
            <h1 className="console-title">
              {result.state === "ok"
                ? result.data.repository.full_name
                : `${owner}/${name}`}
            </h1>
            <p>
              Recent pull requests that change Python dependencies, newest
              first.
            </p>
          </div>
        </div>
        {result.state === "unavailable" ? (
          <p role="alert" className="request-error collection-error">
            The verdict service is unavailable. Verdicts on GitHub are
            unaffected; try this page again shortly.
          </p>
        ) : (
          <section aria-labelledby="pulls-heading" className="console-section">
            <div className="section-line">
              <h2 id="pulls-heading">
                {cursor ? "Older pull requests" : "Dependency pull requests"}
              </h2>
              <span>
                <a
                  className="external-link"
                  href={`https://github.com/${result.data.repository.full_name}/pulls`}
                >
                  Open on GitHub <ArrowUpRight size={13} aria-hidden="true" />
                </a>
              </span>
            </div>
            {result.data.pulls.length === 0 ? (
              <div className="console-empty">
                <p>
                  {cursor
                    ? "There are no older pull requests."
                    : "No dependency pull request has been analysed here yet. Open one, or wait for Dependabot or Renovate."}
                </p>
              </div>
            ) : (
              <ul className="console-list">
                {result.data.pulls.map((pull) => (
                  <li key={pull.id} className="pull-row">
                    <div className="pull-row-main">
                      <h3>
                        <Link href={`/pulls/${pull.id}`}>
                          <span className="pull-number">#{pull.number}</span>{" "}
                          {pull.title || "Untitled pull request"}
                        </Link>
                      </h3>
                      <PackageChanges packages={pull.packages} />
                      <p className="pull-meta">
                        <time dateTime={pull.created_at}>
                          {formatDate(pull.created_at)}
                        </time>{" "}
                        · <code>{pull.head_sha.slice(0, 7)}</code> ·{" "}
                        <a href={pullUrl(pull.repository, pull.number)}>
                          Pull request on GitHub
                          <ArrowUpRight size={12} aria-hidden="true" />
                        </a>
                      </p>
                    </div>
                    <div className="row-verdict">
                      <VerdictLabel
                        verdict={pull.verdict}
                        status={pull.status}
                      />
                      {pull.verdict && (
                        <Link className="text-link" href={`/pulls/${pull.id}`}>
                          Report <ArrowRight size={14} aria-hidden="true" />
                        </Link>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <nav className="console-pager" aria-label="Pages">
              {cursor && (
                <Link className="text-link" href={base}>
                  <ArrowLeft size={14} aria-hidden="true" /> Newest
                </Link>
              )}
              {result.data.next_cursor && (
                <Link
                  className="text-link"
                  href={`${base}?cursor=${result.data.next_cursor}`}
                >
                  Older pull requests{" "}
                  <ArrowRight size={14} aria-hidden="true" />
                </Link>
              )}
            </nav>
          </section>
        )}
      </main>
    </div>
  );
}
