import Link from "next/link";
import type { AgentReview, AgentTrace } from "@/lib/dashboard";
import { duration } from "@/lib/runs";

const ASSESSMENT = {
  "likely-breaks": "Likely breaks",
  "likely-fine": "Likely fine",
  unclear: "Unclear",
} as const;

/** What CodeIntent's agents added to a pull request check, always shown apart from the verdict. */
export function AgentReviewSection({ review }: { review: AgentReview }) {
  const upgrades = review.result.upgrades.filter(
    (u) =>
      (u.patches?.length || 0) +
        (u.assessments?.length || 0) +
        (u.behaviour?.length || 0) >
      0,
  );
  return (
    <section aria-labelledby="agent-review" className="ci-run-section">
      <div className="ci-tile-head">
        <h2 id="agent-review" className="ci-section-title">
          Agent review
        </h2>
        <span className="ci-row-meta">
          {review.model} · not part of the verdict
          {review.agent_run && (
            <>
              {" · "}
              <Link href={`/runs/${review.agent_run}`}>
                what the agents did
              </Link>
            </>
          )}
        </span>
      </div>
      {upgrades.length === 0 && (
        <p className="ci-note">The agents had nothing to add to this check.</p>
      )}
      {upgrades.map((u) => (
        <article key={u.package} className="ci-tile ci-trace">
          <h3>
            <code translate="no">{u.package}</code> {u.start} → {u.end}
          </h3>
          {u.patches?.map((p) => (
            <div key={`${p.file}:${p.line}`} className="ci-trace-blast">
              <p>
                Suggested fix for{" "}
                <code translate="no">
                  {p.file}:{p.line}
                </code>{" "}
                <span
                  className="ci-agent-check"
                  data-verified={p.verified ? "yes" : "no"}
                >
                  {p.verified
                    ? "CodeIntent re-analysed the edit: break no longer found"
                    : "CodeIntent still finds the break with this edit"}
                </span>
              </p>
              <pre className="ci-break-code ci-diff">
                <code translate="no">
                  {p.before
                    .replace(/\n+$/, "")
                    .split("\n")
                    .map((l) => `- ${l}`)
                    .join("\n")}
                  {"\n"}
                  {p.after
                    .replace(/\n+$/, "")
                    .split("\n")
                    .map((l) => `+ ${l}`)
                    .join("\n")}
                </code>
              </pre>
              <p className="ci-note">{p.explanation}</p>
            </div>
          ))}
          {u.assessments?.map((a) => (
            <div key={`${a.file}:${a.line}`} className="ci-trace-blast">
              <p>
                <code translate="no">
                  {a.file}:{a.line}
                </code>{" "}
                (could not be followed statically):{" "}
                <strong>{ASSESSMENT[a.assessment]}</strong>. {a.reason}
              </p>
              {a.evidence.map((e, i) => (
                <blockquote key={i} className="ci-note">
                  <code translate="no">
                    {e.file}:{e.line}
                  </code>{" "}
                  {e.quote}
                </blockquote>
              ))}
              {a.check && <p className="ci-note">Check: {a.check}</p>}
            </div>
          ))}
          {u.behaviour && u.behaviour.length > 0 && (
            <div className="ci-trace-blast">
              <p>
                Behaviour changes in the release notes that touch code you use:
              </p>
              <ul className="ci-trace-chains">
                {u.behaviour.map((c, i) => (
                  <li key={i}>
                    <code translate="no">{c.symbol}</code> (
                    {c.severity === "likely-breaks"
                      ? "likely breaks"
                      : "review"}
                    , {c.version}): {c.what_changed} {c.why_it_matters}
                    <q>{c.quote}</q>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </article>
      ))}
    </section>
  );
}

/** Each agent of an agent run: model, prompt version, turns, tool calls and how it ended. */
export function AgentTraces({ traces }: { traces: AgentTrace[] }) {
  if (!traces.length) return null;
  return (
    <section aria-labelledby="agents" className="ci-run-section">
      <h2 id="agents" className="ci-section-title">
        What each agent did
      </h2>
      <div className="ci-tile">
        <div className="ci-scroll">
          <table className="ci-findings">
            <thead>
              <tr>
                <th scope="col">Agent</th>
                <th scope="col">Model</th>
                <th scope="col">Turns</th>
                <th scope="col">Tools used</th>
                <th scope="col">Tokens</th>
                <th scope="col">Time</th>
                <th scope="col">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((t, i) => {
                const used = Object.entries(
                  t.calls.reduce<Record<string, number>>((n, c) => {
                    n[c.tool] = (n[c.tool] || 0) + 1;
                    return n;
                  }, {}),
                );
                return (
                  <tr key={i}>
                    <td>{t.agent}</td>
                    <td>
                      {t.model}
                      <small className="ci-row-meta">
                        {" "}
                        · prompt {t.prompt}
                      </small>
                    </td>
                    <td>{t.turns}</td>
                    <td>
                      {used.length
                        ? used.map(([tool, n]) => `${tool} ×${n}`).join(", ")
                        : "—"}
                    </td>
                    <td>{t.tokens.toLocaleString("en")}</td>
                    <td>{duration(t.ms)}</td>
                    <td>
                      {t.outcome}
                      {t.rejected.length > 0 && (
                        <small className="ci-row-meta">
                          {" "}
                          · {t.rejected.length} answer
                          {t.rejected.length === 1 ? "" : "s"} sent back
                        </small>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
