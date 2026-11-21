import { VerdictMark } from "./verdict-mark";

const CASES = [
  {
    pkg: "httpx",
    warn: "0.26",
    warnWhat: "proxies= deprecated",
    broke: "0.28.0",
    brokeWhat: "proxies= removed",
  },
  {
    pkg: "itsdangerous",
    warn: "2.0",
    warnWhat: "json deprecated",
    broke: "2.1",
    brokeWhat: "json removed",
  },
  {
    pkg: "MarkupSafe",
    warn: "2.0",
    warnWhat: "soft_unicode deprecated",
    broke: "2.1",
    brokeWhat: "soft_unicode removed",
  },
];

export function EarlyWarning() {
  return (
    <section className="lp-section lp-early" aria-labelledby="early-title">
      <div className="lp-wrap">
        <div className="lp-section-head lp-section-head-split" data-reveal>
          <div>
            <p className="lp-index">§ 05 — Early warning</p>
            <h2 id="early-title">It warned a release before the break.</h2>
          </div>
          <p className="lp-lede">
            Libraries usually deprecate before they remove. On the upgrade
            before each of these breaks, CodeIntent already reported Needs a
            change, at the line that would later break.
          </p>
        </div>
        <ol className="lp-early-list" data-reveal>
          {CASES.map((item) => (
            <li key={item.pkg} className="lp-bezel">
              <div className="lp-bezel-core lp-early-core">
                <p className="lp-early-pkg">
                  <code>{item.pkg}</code>
                </p>
                <div className="lp-early-track" aria-hidden="true">
                  <span />
                </div>
                <div className="lp-early-step" data-kind="needs-change">
                  <p className="lp-early-version">{item.warn}</p>
                  <p className="lp-early-verdict">
                    <VerdictMark kind="needs-change" /> Needs a change
                  </p>
                  <p className="lp-early-what">{item.warnWhat}</p>
                </div>
                <div className="lp-early-step" data-kind="breaks">
                  <p className="lp-early-version">{item.broke}</p>
                  <p className="lp-early-verdict">
                    <VerdictMark kind="breaks" /> Breaks you
                  </p>
                  <p className="lp-early-what">{item.brokeWhat}</p>
                </div>
              </div>
            </li>
          ))}
        </ol>
        <div className="lp-upcoming" data-reveal>
          <div className="lp-upcoming-copy">
            <h3>Upcoming breakage</h3>
            <p>
              The dashboard keeps the same list for every dependency you have:
              what will break on its next upgrade, before any pull request
              exists.
            </p>
          </div>
          <div
            className="lp-upcoming-table"
            role="table"
            aria-label="Upcoming breakage example"
          >
            <div role="row" className="lp-upcoming-row lp-upcoming-head">
              <span role="columnheader">Dependency</span>
              <span role="columnheader">Next upgrade</span>
              <span role="columnheader">Verdict</span>
              <span role="columnheader">Where</span>
            </div>
            <div role="row" className="lp-upcoming-row">
              <span role="cell">
                <code>httpx</code> 0.27.2
              </span>
              <span role="cell">0.28.1</span>
              <span
                role="cell"
                className="lp-upcoming-verdict"
                data-kind="breaks"
              >
                <VerdictMark kind="breaks" /> Breaks you
              </span>
              <span role="cell">
                <code>weather/client.py:12</code>
              </span>
            </div>
            <div role="row" className="lp-upcoming-row">
              <span role="cell">
                <code>requests</code> 2.31.0
              </span>
              <span role="cell">2.34.2</span>
              <span
                role="cell"
                className="lp-upcoming-verdict"
                data-kind="no-known-impact"
              >
                <VerdictMark kind="no-known-impact" /> No known impact
              </span>
              <span role="cell">3 advisories cleared</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
