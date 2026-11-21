import Link from "next/link";
import { Brand } from "@/components/brand";
import { ActionLink } from "./buttons";
import { INSTALL_URL } from "./links";

export function SiteHeader() {
  return (
    <header className="lp-header">
      <div className="lp-wrap lp-header-row">
        <Brand />
        <nav aria-label="Main navigation" className="lp-nav">
          <a href="#how">How it works</a>
          <a href="#verdicts">Verdicts</a>
          <a href="#proof">Proof</a>
          <a href="#security">Security</a>
          <Link href="/setup">Set up</Link>
        </nav>
        <ActionLink href={INSTALL_URL}>Install on GitHub</ActionLink>
      </div>
    </header>
  );
}
