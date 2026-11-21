import Link from "next/link";
import { Brand } from "@/components/brand";
import { ActionLink } from "./buttons";
import { VerdictMark } from "./verdict-mark";
import {
  APP_URL,
  DEMO_PULLS,
  INSTALL_URL,
  MCP_DOCS,
  TELEGRAM_BOT,
} from "./links";

/** The verdict as a stamped inspection slip: the paper the bench in Fig. 1 produces. */
function VerdictSlip() {
  return (
    <div className="lp-slip" aria-hidden="true">
      <svg
        className="lp-slip-holes"
        viewBox="0 0 300 10"
        preserveAspectRatio="none"
      >
        {Array.from({ length: 24 }, (_, index) => (
          <circle key={index} cx={6.25 + index * 12.5} cy="5" r="2.2" />
        ))}
      </svg>
      <p className="lp-slip-head">
        <span>Inspection slip</span>
        <span>No. 0001</span>
      </p>
      <div className="lp-slip-stamp">
        <VerdictMark kind="breaks" size={18} />
        Breaks you
      </div>
      <dl className="lp-slip-fields">
        <div>
          <dt>Upgrade</dt>
          <dd>httpx 0.27.2 → 0.28.0</dd>
        </div>
        <div>
          <dt>Where</dt>
          <dd>src/openai/_base_client.py:857</dd>
        </div>
        <div>
          <dt>Use instead</dt>
          <dd>proxy= or mounts=</dd>
        </div>
        <div>
          <dt>Why</dt>
          <dd>encode/httpx#3319</dd>
        </div>
      </dl>
      <p className="lp-slip-foot">Static analysis · never run · never “safe”</p>
    </div>
  );
}

export function Closing() {
  return (
    <section className="lp-section lp-closing" aria-labelledby="closing-title">
      <div className="lp-wrap">
        <div className="lp-bezel lp-closing-shell" data-reveal>
          <div className="lp-bezel-core lp-closing-core">
            <div className="lp-closing-copy">
              <p className="lp-index">Install</p>
              <h2 id="closing-title">
                Put the next dependency pull request on the bench.
              </h2>
              <p className="lp-lede">
                Install the App on the repositories you choose. The next pull
                request that changes a Python dependency gets its check and
                comment.
              </p>
              <div className="lp-hero-actions">
                <ActionLink href={INSTALL_URL}>Install on GitHub</ActionLink>
                <ActionLink href={DEMO_PULLS} tone="quiet">
                  See it on a real PR
                </ActionLink>
              </div>
            </div>
            <VerdictSlip />
          </div>
        </div>
      </div>
    </section>
  );
}

export function SiteFooter() {
  return (
    <footer className="lp-footer">
      <div className="lp-wrap lp-footer-grid">
        <div className="lp-footer-brand">
          <Brand small />
          <p>
            Static analysis of both released versions. Never runs your code.
            Never calls an upgrade safe.
          </p>
        </div>
        <nav aria-label="Product" className="lp-footer-col">
          <h2>Product</h2>
          <Link href="/setup">Setup</Link>
          <Link href="/dashboard">Dashboard</Link>
          <a href={APP_URL}>GitHub App</a>
          <a href={DEMO_PULLS}>Demo pull requests</a>
        </nav>
        <nav aria-label="Integrations" className="lp-footer-col">
          <h2>Integrations</h2>
          <a href={MCP_DOCS}>MCP server docs</a>
          <a href={TELEGRAM_BOT}>Telegram bot</a>
        </nav>
        <nav aria-label="More" className="lp-footer-col">
          <h2>More</h2>
          <Link href="/credits">Credits</Link>
          <Link href="/investigate">Investigation workspace</Link>
        </nav>
      </div>
    </footer>
  );
}
