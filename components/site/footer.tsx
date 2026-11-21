import Link from "next/link";

/** One quiet line: the limit of the verdicts, and the older investigation tools. */
export function SiteFooter() {
  return (
    <footer className="ci-footer">
      <p>
        Static analysis of both releases. CodeIntent never runs your code, and
        “No known impact” is not a guarantee.
      </p>
      <nav aria-label="More">
        <Link href="/docs">Docs</Link>
        <Link href="/pricing">Pricing</Link>
        <Link href="/investigate">Investigations</Link>
        <Link href="/repositories">Repositories</Link>
        <Link href="/credits">Credits</Link>
      </nav>
    </footer>
  );
}
