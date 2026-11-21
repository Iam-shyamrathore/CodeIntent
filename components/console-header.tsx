import Link from "next/link";
import "@/app/auth.css";
import { Brand } from "./brand";
import { AuthUser } from "./auth-user";
import type { Session } from "@/lib/session";

export function ConsoleHeader({
  current,
  session = null,
  next,
}: {
  current?: "setup" | "dashboard";
  session?: Session | null;
  /** Where "Sign in" returns to; defaults to the dashboard. */
  next?: string;
}) {
  return (
    <header className="collection-header console-header">
      <Brand />
      <nav aria-label="Workspace">
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
        <AuthUser session={session} next={next} />
      </nav>
    </header>
  );
}
