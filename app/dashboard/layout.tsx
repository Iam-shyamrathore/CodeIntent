import { ConsoleHeader } from "@/components/console-header";
import { SectionNav, type NavGroup } from "@/components/dashboard/section-nav";
import { SiteFooter } from "@/components/site/footer";
import { loadContext, loadRecent, thisWeek } from "@/lib/workspaces";

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
    const breaking = thisWeek(await loadRecent()).filter(
      (p) => p.verdict === "breaks",
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
            href: "/dashboard/repositories",
            label: "Repositories",
            count: context.repos.length,
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
