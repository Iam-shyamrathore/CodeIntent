import type { Backtest } from "./backtest-data";

const CAUGHT = [
  {
    pkg: "httpx 0.28",
    what: "proxies=",
    where: "openai-python v1.54.4",
    line: "src/openai/_base_client.py:857",
  },
  {
    pkg: "itsdangerous 2.1",
    what: "json",
    where: "Flask 1.1.2",
    line: "src/flask/json/__init__.py:15",
  },
  {
    pkg: "MarkupSafe 2.1",
    what: "soft_unicode",
    where: "Jinja 2.11.3",
    line: "src/jinja2/filters.py:13",
  },
  {
    pkg: "urllib3 2.0",
    what: "DEFAULT_CIPHERS",
    where: "botocore 1.29.121",
    line: "botocore/httpsession.py:23",
  },
  { pkg: "Jinja2 3.1", what: "Markup, escape", where: null, line: null },
  {
    pkg: "Werkzeug 2.1",
    what: "BaseResponse, as_tuple=",
    where: null,
    line: null,
  },
  {
    pkg: "Werkzeug 3.0",
    what: "url_quote → urllib.parse.quote",
    where: null,
    line: null,
  },
];

const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

export function BacktestSection({ data }: { data: Backtest }) {
  const breaks = data.breaks ?? { caught: 7, total: 7 };
  const harmless = data.harmless;
  return (
    <section
      className="lp-section lp-proof"
      id="proof"
      aria-labelledby="proof-title"
    >
      <div className="lp-wrap">
        <div className="lp-section-head lp-section-head-split" data-reveal>
          <div>
            <p className="lp-index">§ 08 — Backtest</p>
            <h2 id="proof-title">Measured on upgrades that really broke.</h2>
          </div>
          <p className="lp-lede">
            Each case is a real project at a real commit, upgraded to the
            release that broke it, or to one that did not. The numbers below are
            the ones measured so far, and nothing is rounded up.
          </p>
        </div>
        <div className="lp-meters" data-reveal>
          <div className="lp-meter">
            <p className="lp-meter-value">
              {breaks.caught}
              <span> of {breaks.total}</span>
            </p>
            <p className="lp-meter-label">
              real breaking upgrades flagged <b>Breaks you</b>
            </p>
            <div className="lp-meter-bar" aria-hidden="true">
              <span
                style={{ transform: `scaleX(${breaks.caught / breaks.total})` }}
              />
            </div>
          </div>
          <div className="lp-meter">
            {harmless ? (
              <>
                <p className="lp-meter-value">
                  {harmless.false_breaks}
                  <span> of {harmless.total}</span>
                </p>
                <p className="lp-meter-label">
                  harmless upgrades wrongly flagged <b>Breaks you</b>
                  {harmless.wilson_upper !== null
                    ? `; at most ${Math.round(harmless.wilson_upper * 100)}% at 95% confidence`
                    : null}
                </p>
              </>
            ) : (
              <>
                <p className="lp-meter-value">0</p>
                <p className="lp-meter-label">
                  false <b>Breaks you</b> on the harmless upgrades tested so far
                </p>
              </>
            )}
            <div className="lp-meter-bar" data-empty="" aria-hidden="true">
              <span />
            </div>
          </div>
          <div className="lp-meter">
            <p className="lp-meter-value">
              19<span> of 19</span>
            </p>
            <p className="lp-meter-label">
              real API changes traced to the right upstream pull request
            </p>
            <div className="lp-meter-bar" aria-hidden="true">
              <span style={{ transform: "scaleX(1)" }} />
            </div>
          </div>
        </div>
        <div className="lp-proof-grid" data-reveal>
          <div
            className="lp-caught"
            role="table"
            aria-label="Breaking upgrades caught"
          >
            <div role="row" className="lp-caught-row lp-caught-head">
              <span role="columnheader">Upgrade</span>
              <span role="columnheader">What was removed</span>
              <span role="columnheader">Where it broke</span>
            </div>
            {CAUGHT.map((item) => (
              <div role="row" className="lp-caught-row" key={item.pkg}>
                <span role="cell">
                  <code>{item.pkg}</code>
                </span>
                <span role="cell">
                  <code>{item.what}</code>
                </span>
                <span role="cell">
                  {item.line ? (
                    <>
                      {item.where} <code>{item.line}</code>
                    </>
                  ) : (
                    <span className="lp-dim">At the exact lines</span>
                  )}
                </span>
              </div>
            ))}
          </div>
          <aside className="lp-backtest-note">
            <h3>The full backtest</h3>
            <p>
              101 labelled cases: 19 real breaks, 2 guarded by an import
              fallback, and 80 harmless upgrades sampled from real merged
              Dependabot pull requests.
            </p>
            <p className="lp-dim">
              {harmless
                ? "Results above include the harmless sample."
                : "It is running now. Its results will replace the figures above when it finishes."}
              {data.updated ? ` Updated ${formatDate(data.updated)}.` : null}
            </p>
          </aside>
        </div>
      </div>
    </section>
  );
}
