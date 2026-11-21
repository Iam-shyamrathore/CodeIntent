import { ConsoleHeader } from "@/components/console-header";
import { SectionNav, type NavGroup } from "@/components/dashboard/section-nav";
import { SiteFooter } from "@/components/site/footer";
import {
  loadBreaks,
  loadContext,
  loadRecent,
  loadRuns,
  thisWeek,
} from "@/lib/workspaces";

/** Every dashboard section shares the header, the section menu and the footer. */
export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const context = await loadContext();
  const session = context.state === "signed-out" ? null : context.session;
  let groups: NavGroup[] | null = null;
  if (context.state === "ok") {
    const [recent, open, problems] = await Promise.all([
      loadRecent(),
      loadBreaks("open"),
      loadRuns("problems"),
    ]);
    const breaking = thisWeek(recent).filter(
      (p) => p.verdict === "breaks",
    ).length;
    const openBreaks = (open || []).filter(
      (b) => b.severity === "breaks",
    ).length;
    const upcoming = context.repos.reduce(
      (n, r) => n + (r.upcoming?.breaks || 0),
      0,
    );
    groups = [
      {
        items: [
          { href: "/dashboard", label: "Overview" },
          {
            href: "/dashboard/pulls",
            label: "Pull requests",
            count: breaking,
            alarm: true,
          },
          {
            href: "/dashboard/upcoming",
            label: "Before you upgrade",
            count: upcoming,
            alarm: true,
          },
          {
            href: "/dashboard/breaks",
            label: "Breaks",
            count: openBreaks,
            alarm: true,
          },
          {
            href: "/dashboard/repositories",
            label: "Repositories",
            count: context.repos.length,
          },
        ],
      },
      {
        label: "Graph",
        items: [
          { href: "/dashboard/ecosystem", label: "Ecosystem" },
          { href: "/dashboard/impact", label: "Impact" },
          {
            href: "/dashboard/runs",
            label: "Runs",
            count: problems?.length || 0,
            alarm: true,
          },
        ],
      },
      {
        label: "Connect",
        items: [
          { href: "/dashboard/alerts", label: "Alerts" },
          { href: "/dashboard/agents", label: "AI agents" },
        ],
      },
      {
        label: "Account",
        items: [
          { href: "/dashboard/billing", label: "Billing" },
          ...(context.session.kind === "operator"
            ? [{ href: "/dashboard/operations", label: "Operations" }]
            : []),
        ],
      },
    ];
  }
  return (
    <div className="ci ci-page">
      <ConsoleHeader current="dashboard" session={session} />
      {groups ? (
        <div className="ci-app">
          <SectionNav groups={groups} />
          <main className="ci-app-main" id="main">
            {children}
          </main>
        </div>
      ) : (
        <main className="ci-main" id="main">
          {children}
        </main>
      )}
      <SiteFooter />
    </div>
  );
}
