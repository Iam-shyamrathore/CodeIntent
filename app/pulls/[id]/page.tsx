import { cache } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ConsoleHeader } from "@/components/console-header";
import { OperatorSignIn } from "@/components/operator-access";
import { PullReport } from "@/components/pull-report";
import { isOperator } from "@/lib/session";
import { read, UUID, type PullDetail } from "@/lib/dashboard";

type Props = { params: Promise<{ id: string }> };

const loadPull = cache((id: string) => read<PullDetail>(`/app/pulls/${id}`));

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const robots = { index: false, follow: false };
  if (!UUID.test(id)) return { robots };
  const result = await loadPull(id);
  // Titles of private pull requests stay out of metadata, which link previews can read.
  if (result.state !== "ok" || result.data.private)
    return { title: "Dependency verdict · Code Intent", robots };
  const pull = result.data;
  return {
    title: `#${pull.number} ${pull.title || ""} · ${pull.repository} · Code Intent`,
    description: `Dependency upgrade verdict for ${pull.repository} pull request #${pull.number}.`,
    robots,
  };
}

export default async function PullPage({ params }: Props) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const [result, operator] = await Promise.all([loadPull(id), isOperator()]);
  if (result.state === "missing") notFound();
  if (result.state === "unavailable")
    return (
      <div className="repository-page">
        <ConsoleHeader operator={operator} />
        <main className="collection-main" id="main">
          <h1 className="console-title">The verdict service is unavailable</h1>
          <p role="alert" className="request-error collection-error">
            The verdict on the pull request itself is unaffected. Try this link
            again shortly.
          </p>
        </main>
      </div>
    );
  const pull = result.data;
  // Public repositories: the report is readable by link, like the comment that points here.
  // Private repositories: operator only until GitHub sign-in can check repository access.
  if (pull.private && !operator)
    return (
      <div className="repository-page">
        <ConsoleHeader operator={operator} />
        <main className="collection-main" id="main">
          <div className="collection-intro">
            <div>
              <p className="collection-breadcrumb">Dependency verdict</p>
              <h1>This report belongs to a private repository.</h1>
              <p>
                Sign in with the workspace key to read it. The verdict and its
                findings are also on the pull request on GitHub.
              </p>
            </div>
          </div>
          <OperatorSignIn purpose="Operator access is required for reports on private repositories." />
        </main>
      </div>
    );
  const [owner, name] = pull.repository.split("/");
  return (
    <div className="repository-page">
      <ConsoleHeader operator={operator} />
      <main className="collection-main report-main" id="main">
        {operator && (
          <p className="report-back">
            <Link
              className="text-link"
              href={`/dashboard/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`}
            >
              ← All dependency pull requests in {pull.repository}
            </Link>
          </p>
        )}
        <PullReport pull={pull} />
      </main>
    </div>
  );
}
