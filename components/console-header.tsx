import Link from "next/link";
import "@/app/site.css";
import { Brand } from "./brand";
import { AuthUser } from "./auth-user";
import type { Session } from "@/lib/session";

/** The floating pill nav shared by every product page. */
export function ConsoleHeader({
  current,
  session,
  next,
}: {
  current?: "setup" | "dashboard" | "docs" | "pricing";
  /** Omit on static pages: no sign-in state is shown there. */
  session?: Session | null;
  /** Where "Sign in" returns to; defaults to the dashboard. */
  next?: string;
}) {
  return (
    <header className="ci-nav-wrap">
      <a className="ci-skip" href="#main">
        Skip to content
      </a>
      <nav className="ci-nav" aria-label="Main">
        <Brand small />
        <div className="ci-nav-links">
          <Link
            href="/setup"
            aria-current={current === "setup" ? "page" : undefined}
          >
            Setup
          </Link>
          <Link
            href="/dashboard"
            aria-current={current === "dashboard" ? "page" : undefined}
          >
            Dashboard
          </Link>
          <Link
            href="/docs"
            aria-current={current === "docs" ? "page" : undefined}
          >
            Docs
          </Link>
          <Link
            className="ci-nav-pricing"
            href="/pricing"
            aria-current={current === "pricing" ? "page" : undefined}
          >
            Pricing
          </Link>
        </div>
        {session !== undefined && <AuthUser session={session} next={next} />}
      </nav>
    </header>
  );
}
