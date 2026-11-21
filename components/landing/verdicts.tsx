import { VerdictMark, VERDICT_LABEL, type VerdictKind } from "./verdict-mark";

const ROWS: {
  kind: VerdictKind;
  rule: string;
  example: string;
  check: string;
}[] = [
  {
    kind: "breaks",
    rule: "Something your code uses was removed, or an argument it passes no longer works, and the use is not behind an import fallback.",
    example:
      "httpx 0.28.0 removed proxies=, and weather/client.py:12 passes it.",
    check: "failure",
  },
  {
    kind: "needs-change",
    rule: "A deprecation, a removal your code guards with a fallback, or a changed literal default. It works today, and it is on a clock.",
    example: "httpx 0.26 deprecated proxies=. The same code still ran.",
    check: "neutral",
  },
  {
    kind: "not-checked",
    rule: "A use the analysis could not follow statically touches part of the library that changed. It says so and names the line rather than guessing.",
    example:
      "A call that forwards **kwargs into a function whose signature changed.",
    check: "neutral",
  },
  {
    kind: "no-known-impact",
    rule: "Everything your code uses was compared in both releases and nothing relevant changed. This is a statement about what was compared, not a promise.",
    example: "requests 2.31.0 → 2.34.2 on the demo repository.",
    check: "success",
  },
];

export function Verdicts() {
  return (
    <section
      className="lp-section"
      id="verdicts"
      aria-labelledby="verdicts-title"
    >
      <div className="lp-wrap">
        <div className="lp-section-head" data-reveal>
          <p className="lp-index">§ 03 — Verdicts</p>
          <h2 id="verdicts-title">Four verdicts. None of them is “safe”.</h2>
          <p className="lp-lede">
            Each upgrade gets exactly one, decided by fixed rules over the
            comparison. The pull request check reflects it, so a branch
            protection rule can block a merge on Breaks you alone.
          </p>
        </div>
        <div
          className="lp-ledger"
          role="table"
          aria-label="The four verdicts"
          data-reveal
        >
          <div className="lp-ledger-row lp-ledger-head" role="row">
            <span role="columnheader">Verdict</span>
            <span role="columnheader">Rule</span>
            <span role="columnheader">Example</span>
            <span role="columnheader">Check</span>
          </div>
          {ROWS.map((row) => (
            <div
              className="lp-ledger-row"
              role="row"
              key={row.kind}
              data-kind={row.kind}
            >
              <span role="cell" className="lp-ledger-verdict">
                <VerdictMark kind={row.kind} size={16} />
                {VERDICT_LABEL[row.kind]}
              </span>
              <span role="cell">{row.rule}</span>
              <span role="cell" className="lp-ledger-example">
                {row.example}
              </span>
              <span role="cell" className="lp-ledger-check">
                <code>{row.check}</code>
              </span>
            </div>
          ))}
        </div>
        <aside className="lp-never" data-reveal aria-labelledby="never-title">
          <div className="lp-never-glyph" aria-hidden="true">
            <VerdictMark kind="no-known-impact" size={40} />
          </div>
          <div>
            <h3 id="never-title">Why there is no tick</h3>
            <p>
              Static analysis can show that nothing your code uses changed. It
              cannot show that the new release behaves the same at run time. So
              the best result is <b>No known impact</b>, drawn as a level line,
              and every comment ends by saying CodeIntent never calls an upgrade
              safe.
            </p>
          </div>
        </aside>
      </div>
    </section>
  );
}
