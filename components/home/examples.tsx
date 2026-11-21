import { Mark } from "@/components/brand";
import { PlaneMark } from "@/components/site/icons";
import { VerdictGlyph } from "@/components/verdict";
import { DEMO_PR } from "@/components/site/links";

/** The comment CodeIntent posted on the demo pull request, cut to its first finding. */
export function CommentCard() {
  return (
    <article
      className="ci-card ci-example-pr"
      data-leader-anchor=""
      aria-labelledby="example-pr-title"
    >
      <header className="ci-example-head">
        <Mark className="ci-example-avatar" />
        <span>
          <strong>codeintent</strong> on{" "}
          <a href={DEMO_PR}>codeintent-demo #1</a>
        </span>
      </header>
      <h2 id="example-pr-title" className="ci-example-verdict">
        <VerdictGlyph kind="breaks" />
        Breaks you
        <code translate="no">httpx 0.27.2 → 0.28.1</code>
      </h2>
      <dl className="ci-example-rows">
        <div>
          <dt>Your code</dt>
          <dd>
            <code translate="no">weather/client.py:12</code>
          </dd>
        </div>
        <div>
          <dt>Change</dt>
          <dd>
            <code translate="no">httpx.Client(proxies=)</code> removed
          </dd>
        </div>
        <div>
          <dt>Use</dt>
          <dd>
            <code translate="no">proxy=</code> or{" "}
            <code translate="no">mounts=</code>
          </dd>
        </div>
        <div>
          <dt>Why</dt>
          <dd>
            <a href="https://github.com/encode/httpx/pull/3319">
              encode/httpx#3319
            </a>{" "}
            removed it
          </dd>
        </div>
      </dl>
    </article>
  );
}

/** The alert the linked Telegram group got for the same pull request. */
export function AlertCard() {
  return (
    <article className="ci-card ci-example-tg" aria-labelledby="example-tg">
      <header className="ci-example-head">
        <PlaneMark size={14} className="ci-example-plane" />
        <span id="example-tg">
          <strong>CodeIntent alerts</strong> in your group
        </span>
      </header>
      <p>
        <strong>Breaks you</strong>: <code translate="no">httpx</code> 0.27.2 →
        0.28.1
      </p>
      <p className="ci-example-tg-where">
        <code translate="no">weather/client.py:12</code> ·{" "}
        <span className="ci-nowrap">codeintent-demo #1</span>
      </p>
    </article>
  );
}
