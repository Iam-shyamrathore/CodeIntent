"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowRight } from "@/components/site/icons";
import { DOC_ORDER, DOCS } from "@/lib/docs";

export function DocsNav() {
  const pathname = usePathname();
  return (
    <nav className="ci-sections ci-docs-nav" aria-label="Docs">
      {DOCS.map((group) => (
        <div className="ci-sections-group" key={group.group}>
          <p>{group.group}</p>
          <ul>
            {group.pages.map((page) => (
              <li key={page.href}>
                <Link
                  href={page.href}
                  aria-current={page.href === pathname ? "page" : undefined}
                >
                  {page.title}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

/** Previous and next page, in sidebar order. */
export function DocsPager() {
  const pathname = usePathname();
  const i = DOC_ORDER.findIndex((p) => p.href === pathname);
  if (i < 0) return null;
  const prev = DOC_ORDER[i - 1],
    next = DOC_ORDER[i + 1];
  return (
    <nav className="ci-docs-pager" aria-label="Docs pages">
      {prev ? (
        <Link href={prev.href} rel="prev">
          <span>Previous</span>
          {prev.title}
        </Link>
      ) : (
        <span />
      )}
      {next && (
        <Link href={next.href} rel="next" data-next="">
          <span>Next</span>
          {next.title} <ArrowRight size={12} />
        </Link>
      )}
    </nav>
  );
}
