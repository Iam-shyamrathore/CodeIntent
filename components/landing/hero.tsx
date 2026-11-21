import { ActionLink } from "./buttons";
import { DEMO_PR, DEMO_PULLS, INSTALL_URL } from "./links";
import { VerdictMark } from "./verdict-mark";

function PullRequestPlate() {
  return (
    <figure className="lp-pr" aria-labelledby="hero-pr-caption">
      <div className="lp-bezel">
        <div className="lp-bezel-core lp-pr-core">
          <div className="lp-pr-title">
            <span className="lp-pr-state">Open</span>
            <p>
              Bump httpx from 0.27.2 to 0.28.1 <span>#1</span>
            </p>
          </div>
          <p className="lp-pr-by">
            <b>dependabot</b> wants to merge 1 commit into <code>main</code>
          </p>
          <div className="lp-diff" aria-label="requirements.txt diff">
            <div className="lp-diff-file">requirements.txt</div>
            <pre>
              <span data-line="del">
                <i>1</i>-httpx==0.27.2
              </span>
              <span data-line="add">
                <i>1</i>+httpx==0.28.1
              </span>
              <span>
                <i>2</i> requests==2.31.0
              </span>
            </pre>
          </div>
          <div className="lp-checks">
            <p className="lp-checks-head">
              <VerdictMark kind="breaks" />
              <span>
                <b>Some checks were not successful</b>
                <span>1 failing check</span>
              </span>
            </p>
            <p className="lp-check-row">
              <span className="lp-check-name">CodeIntent dependency check</span>
              <span className="lp-check-title">
                Breaks you: httpx 0.27.2 → 0.28.1
              </span>
            </p>
          </div>
          <div className="lp-pr-finding">
            <p className="lp-pr-finding-where">
              <code>weather/client.py:12</code>
            </p>
            <pre
              className="lp-code"
              aria-label="weather/client.py, lines 12 to 15"
            >
              <span>
                <i>12</i> return httpx.Client(
              </span>
              <span>
                <i>13</i> timeout=httpx.Timeout(10.0),
              </span>
              <span data-mark="">
                <i>14</i> <mark>proxies=</mark>
                {'{"https://": proxy} if proxy else None,'}
              </span>
              <span>
                <i>15</i> )
              </span>
            </pre>
            <p className="lp-pr-fix">
              Use <code>proxy=</code> or <code>mounts=</code> instead
            </p>
          </div>
        </div>
      </div>
      <figcaption id="hero-pr-caption">
        A real Dependabot pull request on the demo repository.{" "}
        <a href={DEMO_PR}>See it on GitHub</a>
      </figcaption>
    </figure>
  );
}

export function Hero() {
  return (
    <section className="lp-hero" aria-labelledby="hero-title">
      <div className="lp-wrap lp-hero-grid">
        <div className="lp-hero-copy">
          <p className="lp-eyebrow">
            <span>CodeIntent Dependency Check</span>
            <span aria-hidden="true">/</span>
            <span>A GitHub App for Python</span>
          </p>
          <h1 id="hero-title">
            Know what a dependency upgrade breaks, <em>before you merge it.</em>
          </h1>
          <p className="lp-hero-lede">
            On every pull request that changes a Python dependency, CodeIntent
            compares both released versions against the code your repository
            actually has. It posts one check and one comment: the file and line
            that breaks, what changed, what to use instead, and why upstream
            changed it.
          </p>
          <div className="lp-hero-actions">
            <ActionLink href={INSTALL_URL}>Install on GitHub</ActionLink>
            <ActionLink href={DEMO_PULLS} tone="quiet">
              See it on a real PR
            </ActionLink>
          </div>
          <dl className="lp-hero-facts">
            <div>
              <dt>Real breaking upgrades flagged</dt>
              <dd>7 of 7</dd>
            </div>
            <div>
              <dt>Upstream pull requests found</dt>
              <dd>19 of 19</dd>
            </div>
            <div>
              <dt>Models deciding the verdict</dt>
              <dd>None</dd>
            </div>
          </dl>
        </div>
        <PullRequestPlate />
      </div>
    </section>
  );
}
