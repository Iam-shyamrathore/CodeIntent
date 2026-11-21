import Link from "next/link";
import { Brand } from "./brand";
import { OperatorSignOut } from "./operator-access";

export function ConsoleHeader({
  current,
  operator,
}: {
  current?: "setup" | "dashboard";
  operator?: boolean;
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
        {operator && <OperatorSignOut />}
      </nav>
    </header>
  );
}
