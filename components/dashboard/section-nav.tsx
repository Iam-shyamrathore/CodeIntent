"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

export type NavItem = {
  href: string;
  label: string;
  /** A count beside the label; `alarm` turns it red, as for anything that breaks. */
  count?: number;
  alarm?: boolean;
};
export type NavGroup = { label?: string; items: NavItem[] };

/** Repository pages live under /dashboard/owner/name and belong to Repositories. */
const SECTIONS = new Set([
  "pulls",
  "upcoming",
  "breaks",
  "impact",
  "ecosystem",
  "runs",
  "repositories",
  "alerts",
  "agents",
  "billing",
  "operations",
]);
function current(pathname: string) {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length < 2) return "/dashboard";
  if (segments.length === 2 && SECTIONS.has(segments[1]))
    return `/dashboard/${segments[1]}`;
  return "/dashboard/repositories";
}

/** The dashboard's section menu: a sidebar on wide screens, a scrolling row of tabs on narrow ones. */
export function SectionNav({ groups }: { groups: NavGroup[] }) {
  const active = current(usePathname());
  return (
    <nav className="ci-sections" aria-label="Dashboard">
      {groups.map((group, i) => (
        <div className="ci-sections-group" key={group.label || i}>
          {group.label && <p>{group.label}</p>}
          <ul>
            {group.items.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={item.href === active ? "page" : undefined}
                >
                  {item.label}
                  {item.count ? (
                    <span
                      className="ci-sections-count"
                      data-alarm={item.alarm ? "" : undefined}
                    >
                      <span className="sr-only">, </span>
                      {item.count}
                    </span>
                  ) : null}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}
