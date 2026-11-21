import Link from "next/link";
import { notFound } from "next/navigation";
import { SignInPanel } from "@/components/auth-panel";
import { BreakCard } from "@/components/break-card";
import { ConsoleHeader } from "@/components/console-header";
import { RunGraphLazy } from "@/components/run-graph-lazy";
import { SiteFooter } from "@/components/site/footer";
import { ArrowOut } from "@/components/site/icons";
import {
  formatDate,
  pullUrl,
  read,
  UUID,
  type RunDetail,
  type RunGraph,
} from "@/lib/dashboard";
import { duration, failure, KIND, runTitle, STATUS } from "@/lib/runs";
import {
  canAccessInstallation,
  getSession,
  installationQuery,
  type Session,
} from "@/lib/session";

type Props = { params: Promise<{ id: string }> };

export const metadata = {
  title: "Run · CodeIntent",
  robots: { index: false, follow: false },
};

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

function time(value: string) {
  return new Date(value).toLocaleString("en-GB", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default async function RunPage({ params }: Props) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const session = await getSession();
  const next = `/runs/${id}`;
  if (!session)
    return (
      <Shell session={null} next={next}>
        <h1 className="ci-title">Run report</h1>
        <SignInPanel
          next={next}
          title="Sign in to see this run"
          body="Runs are shown to people with access to the repository’s installation of the GitHub App."
          operatorPurpose="For the deployment operator: the workspace key shows every run."
        />
      </Shell>
    );
  if (session.kind === "github" && session.installations.length === 0)
    notFound();
  const scope =
    session.kind === "github" ? `?${installationQuery(session)}` : "";
  const [result, drawn] = await Promise.all([
    read<RunDetail>(`/app/runs/${id}${scope}`),
    read<RunGraph>(`/app/runs/${id}/graph${scope}`),
  ]);
  if (
    result.state === "missing" ||
    (result.state === "ok" &&
      result.data.installation_id !== null &&
      !canAccessInstallation(session, result.data.installation_id))
  )
    notFound();
  if (result.state !== "ok")
    return (
      <Shell session={session} next={next}>
        <h1 className="ci-title">The verdict service is unavailable</h1>
        <p className="ci-alert" role="alert">
          Try this page again shortly.
        </p>
      </Shell>
    );
  const run = result.data;
  const problem = failure(run);
  const input = run.input || {};
  const mcpResult = run.kind === "mcp" ? run.result : null;
  const steps = (mcpResult?.steps as string[] | undefined) || [];
  return (
    <Shell session={session} next={next}>
      <div className="ci-head">
        <div>
          <p className="ci-crumb">
            <Link href="/dashboard">Dashboard</Link>
            <span aria-hidden="true">/</span>
            {KIND[run.kind]}
          </p>
          <h1 className="ci-title">{runTitle(run)}</h1>
          <p className="ci-run-meta">
            <span className="ci-run-status" data-status={run.status}>
              {STATUS[run.status]}
            </span>
            <span>
              <time dateTime={run.started_at}>{time(run.started_at)}</time> UTC
            </span>
            <span>{duration(run.duration_ms)}</span>
            {run.attempt > 1 && <span>attempt {run.attempt}</span>}
            {run.ref && <code translate="no">{run.ref.slice(0, 12)}</code>}
          </p>
        </div>
        <span className="ci-run-links">
          {run.analysis_id && (
            <Link className="ci-link" href={`/pulls/${run.analysis_id}`}>
              Pull request report
            </Link>
          )}
          {run.kind === "pull" && run.repository && (
            <a
              className="ci-link"
              href={pullUrl(run.repository, Number(run.subject.slice(1)))}
            >
              On GitHub <ArrowOut />
            </a>
          )}
        </span>
      </div>

      {problem && (
        <section
          className="ci-failure"
          data-status={run.status}
          aria-labelledby="failure"
        >
          <h2 id="failure">{problem.title}</h2>
          <p>{problem.cause}</p>
          <p className="ci-note">{problem.next}</p>
          {run.error && (
            <p className="ci-note">
              Category: <code translate="no">{run.error.split(":")[0]}</code>
            </p>
          )}
        </section>
      )}

      <div className="ci-run-grid">
        <section className="ci-tile" aria-labelledby="steps">
          <h2 id="steps">Steps</h2>
          {run.steps.length === 0 ? (
            <p className="ci-note">No step was recorded.</p>
          ) : (
            <ol className="ci-steps-list">
              {run.steps.map((s) => (
                <li key={s.seq} data-status={s.status}>
                  <span className="ci-step-dot" aria-hidden="true" />
                  <span className="ci-step-name">
                    {s.name}
                    {s.detail && <small>{s.detail}</small>}
                  </span>
                  <span className="ci-row-meta">
                    {s.status === "failed"
                      ? "failed"
                      : s.status === "skipped"
                        ? "skipped"
                        : duration(s.duration_ms)}
                  </span>
                </li>
              ))}
            </ol>
          )}
          {run.attempts.length > 1 && (
            <p className="ci-note">
              Attempts:{" "}
              {run.attempts.map((a, i) => (
                <span key={a.id}>
                  {i > 0 && " · "}
                  {a.id === run.id ? (
                    <strong>
                      {a.attempt}: {STATUS[a.status]}
                    </strong>
                  ) : (
                    <Link href={`/runs/${a.id}`}>
                      {a.attempt}: {STATUS[a.status]}
                    </Link>
                  )}
                </span>
              ))}
            </p>
          )}
        </section>

        {run.kind === "mcp" && (
          <section className="ci-tile" aria-labelledby="asked">
            <h2 id="asked">What the agent asked</h2>
            <dl className="ci-facts">
              {Object.entries(input).map(([k, v]) => (
                <div key={k}>
                  <dt>{k.replaceAll("_", " ")}</dt>
                  <dd>
                    <code translate="no">{String(v ?? "—")}</code>
                  </dd>
                </div>
              ))}
            </dl>
            {steps.length > 0 && (
              <>
                <h3>Steps it was given</h3>
                <ol className="ci-agent-steps">
                  {steps.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
              </>
            )}
          </section>
        )}
      </div>

      {run.breaks.length > 0 && (
        <section aria-labelledby="breaks" className="ci-run-section">
          <h2 id="breaks" className="ci-section-title">
            What it found
          </h2>
          {run.breaks.map((b) => (
            <BreakCard key={`${b.source}-${b.pull_number}-${b.key}`} item={b} />
          ))}
        </section>
      )}

      <section aria-labelledby="graph" className="ci-run-section">
        <div className="ci-tile-head">
          <h2 id="graph" className="ci-section-title">
            In the workspace graph
          </h2>
          <span className="ci-row-meta">Neo4j</span>
        </div>
        {drawn.state !== "ok" ? (
          <p className="ci-note" role="status">
            The workspace graph is unavailable right now.
          </p>
        ) : !drawn.data.projected ? (
          <p className="ci-note" role="status">
            This run is being added to the graph; refresh in a minute.
          </p>
        ) : (
          <RunGraphLazy graph={drawn.data} />
        )}
      </section>

      {mcpResult && (
        <details className="ci-fold ci-run-section">
          <summary>Full result returned to the agent</summary>
          <pre className="ci-json">
            <code>{JSON.stringify(mcpResult, null, 2)}</code>
          </pre>
        </details>
      )}
      <p className="ci-note ci-run-section">
        Started {formatDate(run.started_at)}
        {run.finished_at && `, finished ${time(run.finished_at)} UTC`}.
      </p>
    </Shell>
  );
}
