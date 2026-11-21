import { cache } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { ConsoleHeader } from "@/components/console-header";
import { SignInPanel } from "@/components/auth-panel";
import { PullReport } from "@/components/pull-report";
import { SiteFooter } from "@/components/site/footer";
import { canAccessInstallation, getSession, type Session } from "@/lib/session";
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
    return { title: "Dependency verdict · CodeIntent", robots };
  const pull = result.data;
  return {
    title: `#${pull.number} ${pull.title || ""} · ${pull.repository} · CodeIntent`,
    description: `Dependency upgrade verdict for ${pull.repository} pull request #${pull.number}.`,
    robots,
  };
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
      <ConsoleHeader session={session} next={next} />
      <main className="ci-main" id="main">
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}

export default async function PullPage({ params }: Props) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const [result, session] = await Promise.all([loadPull(id), getSession()]);
  const next = `/pulls/${id}`;
  if (result.state === "unavailable")
    return (
      <Shell session={session} next={next}>
        <h1 className="ci-title">The verdict service is unavailable</h1>
        <p role="alert" className="ci-intro">
          The verdict on the pull request itself is unaffected. Try this link
          again shortly.
        </p>
      </Shell>
    );
  // Public repositories: the report is readable by link, like the comment that points here.
  // Private repositories: only for sessions that include the repository's installation.
  const pull = result.state === "ok" ? result.data : null;
  const readable =
    pull !== null &&
    (!pull.private || canAccessInstallation(session, pull.installation_id));
  // Signed in without access, or no such report: "not found" either way, so nothing leaks.
  if (!readable && session) notFound();
  // Signed out: one prompt for private and unknown reports alike.
  if (!readable || !pull)
    return (
      <Shell session={session} next={next}>
        <div className="ci-head">
          <div>
            <p className="ci-crumb">Dependency verdict</p>
            <h1 className="ci-title">Sign in to read this report</h1>
            <p className="ci-intro">
              Reports on private repositories are shown to people with access to
              the repository’s installation of the GitHub App. The verdict and
              its findings are also on the pull request on GitHub.
            </p>
          </div>
        </div>
        <SignInPanel
          next={next}
          title="Sign in with GitHub"
          body="Use the GitHub account you open the pull request with."
          operatorPurpose="For the deployment operator: the workspace key opens every report."
        />
      </Shell>
    );
  const [owner, name] = pull.repository.split("/");
  const crumb = canAccessInstallation(session, pull.installation_id) ? (
    <>
      <Link href="/dashboard">Dashboard</Link>
      <span aria-hidden="true">/</span>
      <Link
        href={`/dashboard/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`}
      >
        {pull.repository}
      </Link>
      <span aria-hidden="true">/</span>
    </>
  ) : (
    <>
      <span>{pull.repository}</span>
      <span aria-hidden="true">/</span>
    </>
  );
  return (
    <Shell session={session} next={next}>
      <PullReport pull={pull} crumb={crumb} />
    </Shell>
  );
}
