import Link from "next/link";
import { DashboardGate, PageHead } from "@/components/dashboard/tiles";
import { ArrowRight } from "@/components/site/icons";
import { BILLING_LIVE, PLANS } from "@/lib/plans";
import { loadContext } from "@/lib/workspaces";

export const metadata = { title: "Billing · CodeIntent" };

export default async function Billing() {
  const context = await loadContext();
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/billing" />;
  const { workspaces, repos } = context;
  const plan = PLANS[0];
  const usage: [string, number, string][] = [
    ["Repositories watched", repos.length, "/dashboard/repositories"],
    [
      "Pull requests checked",
      repos.reduce((n, r) => n + r.analyses, 0),
      "/dashboard/pulls",
    ],
    [
      "Private repositories",
      repos.filter((r) => r.private).length,
      "/dashboard/repositories",
    ],
    [
      "Agent tokens",
      workspaces.reduce((n, w) => n + (w.agents?.length || 0), 0),
      "/dashboard/agents",
    ],
  ];
  return (
    <>
      <PageHead
        title="Billing"
        intro="Your plan, what you use, and how you pay."
      />
      {!BILLING_LIVE && (
        <p className="ci-notice" role="status">
          Billing is not live yet. Every feature is free during the beta and
          nothing is charged.
        </p>
      )}
      <div className="ci-bento">
        <section className="ci-tile ci-tile-plan" aria-labelledby="plan">
          <h2 id="plan">Plan</h2>
          <p className="ci-plan-now">
            <strong>{BILLING_LIVE ? plan.name : "Beta"}</strong>
            <span>{BILLING_LIVE ? plan.cadence : "Free, all features"}</span>
          </p>
          <Link className="ci-btn-quiet" href="/pricing">
            Compare plans <ArrowRight />
          </Link>
        </section>

        <section className="ci-tile ci-tile-usage" aria-labelledby="usage">
          <div className="ci-tile-head">
            <h2 id="usage">Usage</h2>
            <span className="ci-row-meta">All time</span>
          </div>
          <dl className="ci-usage">
            {usage.map(([label, value, href]) => (
              <div key={label}>
                <dt>
                  <Link href={href}>{label}</Link>
                </dt>
                <dd className="ci-num">{value}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="ci-tile ci-tile-pay" aria-labelledby="payment">
          <h2 id="payment">Payment method</h2>
          <p className="ci-note">No card on file.</p>
          <button type="button" className="ci-btn-quiet" disabled>
            Add a card
          </button>
          <p className="ci-tile-note">Available when paid plans launch.</p>
        </section>

        <section
          className="ci-tile ci-tile-invoices"
          aria-labelledby="invoices"
        >
          <h2 id="invoices">Invoices</h2>
          <p className="ci-note">
            No invoices. You have not been charged for anything.
          </p>
        </section>
      </div>
    </>
  );
}
