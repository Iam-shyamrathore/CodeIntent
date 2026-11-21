import { ArrowUpRight } from "lucide-react";
import type { ReactNode } from "react";

/** A link styled as a button, with its arrow nested in its own small plate. */
export function ActionLink({
  href,
  children,
  tone = "primary",
}: {
  href: string;
  children: ReactNode;
  tone?: "primary" | "quiet";
}) {
  return (
    <a className="lp-action" data-tone={tone} href={href}>
      <span>{children}</span>
      <span className="lp-action-icon" aria-hidden="true">
        <ArrowUpRight size={15} strokeWidth={1.6} />
      </span>
    </a>
  );
}
