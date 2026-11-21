import type { Traced } from "@/lib/dashboard";

function Names({ items, limit = 4 }: { items: string[]; limit?: number }) {
  return (
    <>
      {items.slice(0, limit).map((name, i) => (
        <span key={name}>
          {i > 0 && ", "}
          <code translate="no">{name}</code>
        </span>
      ))}
      {items.length > limit && ` and ${items.length - limit} more`}
    </>
  );
}

/** From the workspace graph: where each upgraded package reaches the code, and what its broken lines take down. */
export function Trace({ graph }: { graph: Record<string, Traced> }) {
  const packages = Object.entries(graph).filter(
    ([, t]) =>
      t.reach.uses > 0 || t.reach.through.length > 0 || t.blast.length > 0,
  );
  if (packages.length === 0) return null;
  return (
    <section aria-labelledby="trace" className="ci-run-section">
      <div className="ci-tile-head">
        <h2 id="trace" className="ci-section-title">
          Traced through your code
        </h2>
        <span className="ci-row-meta">Neo4j</span>
      </div>
      {packages.map(([name, t]) => (
        <article key={name} className="ci-tile ci-trace">
          <h3>
            <code translate="no">{name}</code>
          </h3>
          {t.reach.uses > 0 && (
            <p>
              Used {t.reach.uses} time{t.reach.uses === 1 ? "" : "s"} in{" "}
              {t.reach.files.length} file{t.reach.files.length === 1 ? "" : "s"}
              : <Names items={t.reach.files} />.
            </p>
          )}
          {t.reach.through.length > 0 && (
            <ul className="ci-trace-chains" aria-label="Pulled in through">
              {t.reach.through.slice(0, 4).map((c) => (
                <li key={c.via}>
                  {c.chain.map((step, i) => (
                    <span key={step}>
                      {i > 0 && <span aria-hidden="true"> → </span>}
                      <code translate="no">{step.split("@")[0]}</code>
                    </span>
                  ))}
                  {c.uses > 0 && (
                    <span className="ci-row-meta">
                      {" "}
                      · {c.uses} use{c.uses === 1 ? "" : "s"} of {c.via}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {t.blast
            .filter((b) => b.function || b.importers.length > 0)
            .map((b) => (
              <div key={`${b.file}:${b.line}`} className="ci-trace-blast">
                <p>
                  <code translate="no">
                    {b.file}:{b.line}
                  </code>
                  {b.function && (
                    <>
                      {" "}
                      in <code translate="no">{b.function}()</code>
                    </>
                  )}
                </p>
                <dl className="ci-facts">
                  {b.callers.length > 0 && (
                    <div>
                      <dt>Called by</dt>
                      <dd>
                        <Names
                          items={b.callers.map(
                            (c) =>
                              `${c.function}()${c.depth > 1 ? ` · ${c.depth} calls away` : ""}`,
                          )}
                        />
                      </dd>
                    </div>
                  )}
                  {b.entry_points.length > 0 && (
                    <div>
                      <dt>Reached from</dt>
                      <dd>
                        <Names
                          items={[
                            ...new Set(
                              b.entry_points.map((e) =>
                                e.name === "script" ? e.file : e.name,
                              ),
                            ),
                          ]}
                        />
                      </dd>
                    </div>
                  )}
                  {b.importers.length > 0 && (
                    <div>
                      <dt>Imported by</dt>
                      <dd>
                        <Names items={b.importers.map((i) => i.file)} />
                      </dd>
                    </div>
                  )}
                  {b.tests.length > 0 && (
                    <div>
                      <dt>Tests to run</dt>
                      <dd>
                        <Names items={b.tests} />
                      </dd>
                    </div>
                  )}
                </dl>
              </div>
            ))}
        </article>
      ))}
    </section>
  );
}
