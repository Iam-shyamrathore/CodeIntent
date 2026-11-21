import { MCP_DOCS, TELEGRAM_BOT } from "./links";
import { VerdictMark, type VerdictKind } from "./verdict-mark";

function CheckIllustration() {
  return (
    <div className="lp-ill lp-ill-check" aria-hidden="true">
      <div className="lp-ill-check-row" data-kind="breaks">
        <VerdictMark kind="breaks" />
        <span>CodeIntent dependency check</span>
        <em>failure</em>
      </div>
      <div className="lp-ill-check-row" data-kind="neutral">
        <span className="lp-ill-dot" />
        <span>tests / pytest</span>
        <em>success</em>
      </div>
      <div className="lp-ill-check-row" data-kind="neutral">
        <span className="lp-ill-dot" />
        <span>lint / ruff</span>
        <em>success</em>
      </div>
      <div className="lp-ill-merge">1 failing check</div>
    </div>
  );
}

function TelegramIllustration() {
  return (
    <div className="lp-ill lp-ill-chat" aria-hidden="true">
      <div className="lp-ill-bubble">
        <b>Breaks you: httpx 0.27.2 → 0.28.0</b>
        <span>httpx.Client(proxies=) no longer accepts this argument</span>
        <span>
          <code>src/openai/_base_client.py:857</code>
        </span>
        <span className="lp-ill-link">Upstream: #3319</span>
      </div>
      <div className="lp-ill-bubble lp-ill-bubble-me">/status</div>
    </div>
  );
}

function AgentIllustration() {
  return (
    <div className="lp-ill lp-ill-term" aria-hidden="true">
      <p>
        <span className="lp-ill-prompt">›</span> upgrade_brief httpx latest
      </p>
      <p className="lp-ill-dim">verdict: breaks</p>
      <p className="lp-ill-dim">steps:</p>
      <p>
        1. In weather/client.py:12, replace <mark>proxies=</mark> with proxy= or
        mounts=
      </p>
      <p>2. Change httpx==0.27.2 at requirements.txt:1</p>
    </div>
  );
}

function DashboardIllustration() {
  return (
    <div className="lp-ill lp-ill-dash" aria-hidden="true">
      <p className="lp-ill-dash-repo">Iam-shyamrathore/codeintent-demo</p>
      {[
        ["#1", "httpx 0.27.2 → 0.28.1", "breaks", "Breaks you"],
        [
          "#2",
          "requests 2.31.0 → 2.34.2",
          "no-known-impact",
          "No known impact",
        ],
      ].map(([pr, change, kind, label]) => (
        <div className="lp-ill-dash-row" key={pr} data-kind={kind}>
          <span className="lp-ill-dim">{pr}</span>
          <code>{change}</code>
          <span>
            <VerdictMark kind={kind as VerdictKind} /> {label}
          </span>
        </div>
      ))}
    </div>
  );
}

export function Surfaces() {
  return (
    <section className="lp-section" aria-labelledby="surfaces-title">
      <div className="lp-wrap">
        <div className="lp-section-head" data-reveal>
          <p className="lp-index">§ 07 — Where it shows up</p>
          <h2 id="surfaces-title">
            The same finding, wherever your team looks.
          </h2>
        </div>
        <div className="lp-bento" data-reveal>
          <article className="lp-bezel lp-bento-wide">
            <div className="lp-bezel-core lp-bento-core">
              <div className="lp-bento-copy">
                <h3>On the pull request</h3>
                <p>
                  One check and one comment, updated in place when the pull
                  request changes. Breaks you fails the check; the other
                  verdicts never block on their own.
                </p>
              </div>
              <CheckIllustration />
            </div>
          </article>
          <article className="lp-bezel">
            <div className="lp-bezel-core lp-bento-core">
              <div className="lp-bento-copy">
                <h3>In Telegram</h3>
                <p>
                  Link a chat to{" "}
                  <a href={TELEGRAM_BOT}>@codeintent_alerts_bot</a> and findings
                  arrive as they are posted. Ask <code>/status</code> or{" "}
                  <code>/why</code>.
                </p>
              </div>
              <TelegramIllustration />
            </div>
          </article>
          <article className="lp-bezel">
            <div className="lp-bezel-core lp-bento-core">
              <div className="lp-bento-copy">
                <h3>In your coding agent</h3>
                <p>
                  An <a href={MCP_DOCS}>MCP server</a> gives Claude Code,
                  Cursor, Codex or Devin the fix brief, so the agent writes the
                  change from facts rather than guesses.
                </p>
              </div>
              <AgentIllustration />
            </div>
          </article>
          <article className="lp-bezel lp-bento-wide">
            <div className="lp-bezel-core lp-bento-core">
              <div className="lp-bento-copy">
                <h3>On the dashboard</h3>
                <p>
                  Set-up, every checked pull request, and the upcoming breakage
                  for each dependency, before its upgrade is proposed.
                </p>
              </div>
              <DashboardIllustration />
            </div>
          </article>
        </div>
      </div>
    </section>
  );
}
