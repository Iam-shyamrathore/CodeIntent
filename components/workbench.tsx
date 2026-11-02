"use client";
import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
const EvidenceGraph = dynamic(() => import("./evidence-graph"), {
  ssr: false,
  loading: () => <p className="tab-description">Loading evidence graph…</p>,
});
import * as Tabs from "@radix-ui/react-tabs";
import {
  ArrowUp,
  ArrowUpRight,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  GitBranch,
  ChevronRight,
  Info,
  LoaderCircle,
  Check,
  Copy,
  Link2,
  Download,
} from "lucide-react";
import { Brand } from "./brand";
import { EvidenceInspector, SourceIcon, formatDate } from "./evidence";
import type { Study, Source, Citation } from "@/lib/study";

const questions = [
  "Why did HTTPX bring back URL.raw after removing RawURL? Was it a full rollback?",
  "Why was app= deprecated rather than immediately removed?",
  "Why did the team choose its internal ticketing software?",
];
export default function Workbench({
  initial,
  homeStudy,
}: {
  initial: Study;
  homeStudy: Study;
}) {
  const [study, setStudy] = useState(initial),
    [question, setQuestion] = useState(""),
    [pending, setPending] = useState(false),
    [pendingMessage, setPendingMessage] = useState(
      "Retrieving evidence and checking citations…",
    ),
    [error, setError] = useState(""),
    [rail, setRail] = useState(true),
    [info, setInfo] = useState(false),
    [copied, setCopied] = useState(false);
  const [selected, setSelected] = useState<{
    source: Source;
    citation?: Citation;
  } | null>(null);
  const [saved, setSaved] = useState(true);
  const [tab, setTab] = useState("answer");
  const input = useRef<HTMLTextAreaElement>(null);
  const evidenceOpener = useRef<HTMLElement | null>(null);
  const [recent, setRecent] = useState<{ id: string; question: string }[]>([]);
  const [shared, setShared] = useState(false);
  useEffect(() => {
    fetch(
      `/api/service/reports?repository=${encodeURIComponent(study.repository)}`,
    )
      .then((r) => r.json())
      .then((d) => setRecent(d.reports || []))
      .catch(() => {});
  }, [study.repository, study.report_id]);
  const isDemo = study.repository === "encode/httpx";
  const empty = study.answer.status === "empty";
  async function share() {
    if (!study.report_id) return;
    try {
      await navigator.clipboard.writeText(
        `${window.location.origin}/reports/${study.report_id}`,
      );
      setShared(true);
      setTimeout(() => setShared(false), 1800);
    } catch {
      setError("Copy is unavailable. Open the saved report link below.");
    }
  }
  function download() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(study, null, 2)], { type: "application/json" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `code-intent-${study.report_id || study.index_id}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  const open = (id: string, citation?: Citation) => {
    const source = study.sources.find((s) => s.id === id);
    if (source) {
      evidenceOpener.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      setSelected({ source, citation });
    }
  };
  const connectionLabel = (id: string) => {
    const source = study.sources.find((item) => item.id === id);
    if (!source) return "Related source";
    if (["comment", "review", "review_comment"].includes(source.kind)) {
      return `${source.author} · ${formatDate(source.date)}`;
    }
    return source.title;
  };
  async function ask(text = question) {
    if (text.trim().length < 8 || pending) return;
    setPending(true);
    setPendingMessage("Submitting investigation…");
    setError("");
    try {
      const response = await fetch("/api/investigate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: text,
          index_id: study.index_id,
          repository: study.repository,
        }),
      });
      let data = await response.json();
      if (!response.ok)
        throw new Error(
          data.detail || "The investigation could not be completed",
        );
      if (response.status === 202) {
        const jobId = data.job_id;
        const deadline = Date.now() + 240_000;
        while (true) {
          setPendingMessage(
            data.status === "running"
              ? "Retrieving evidence and checking citations…"
              : data.status === "retrying"
                ? "The evidence service is retrying this investigation…"
                : "Queued for investigation…",
          );
          await new Promise((resolve) => setTimeout(resolve, 1500));
          const poll = await fetch(`/api/service/questions/${jobId}`, {
            cache: "no-store",
          });
          data = await poll.json();
          if (!poll.ok || data.status === "failed")
            throw new Error(
              data.detail || "The investigation could not be completed",
            );
          if (data.status === "ready") {
            data = data.result;
            break;
          }
          if (Date.now() > deadline)
            throw new Error(
              "This investigation is still running. Its report will appear in your recent investigations when it finishes.",
            );
        }
      }
      setStudy(data);
      setSaved(false);
      setQuestion("");
      setTab("answer");
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "The investigation could not be completed",
      );
    } finally {
      setPending(false);
    }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(
        study.question +
          "\n\n" +
          study.answer.title +
          "\n\n" +
          study.answer.claims.map((c) => c.text).join("\n\n") +
          "\n\n" +
          study.answer.unknowns.map((t) => "Unknown: " + t).join("\n") +
          "\n\n" +
          study.answer.temporal_note +
          "\n\n" +
          study.repository +
          " @ " +
          study.revision +
          "\n\n" +
          study.sources
            .filter((s) =>
              study.answer.claims.some((c) =>
                c.citations.some((r) => r.source_id === s.id),
              ),
            )
            .map((s) => s.url)
            .join("\n"),
      );
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("Copy is unavailable in this browser");
    }
  }
  return (
    <div className={`workspace ${rail ? "" : "rail-collapsed"}`}>
      <aside className="repo-rail">
        <div className="rail-brand">
          <Brand small />
          <button
            className="icon-button"
            aria-label="Collapse sidebar"
            onClick={() => setRail(false)}
          >
            <PanelLeftClose size={17} />
          </button>
        </div>
        <button
          className="new-investigation"
          onClick={() => {
            setQuestion("");
            input.current?.focus();
          }}
        >
          <Plus size={16} /> New question
        </button>
        <div className="rail-repository">
          <GitBranch size={16} />
          <span>
            {study.repository.split("/")[0]} /{" "}
            <strong>{study.repository.split("/")[1]}</strong>
          </span>
        </div>
        <div className="rail-caption">Investigations</div>
        <div className="recent-questions">
          {isDemo &&
            questions.map((q, i) => (
              <button
                key={q}
                className={study.question === q ? "is-current" : ""}
                onClick={() =>
                  i === 0
                    ? (setStudy(homeStudy),
                      setSaved(true),
                      setTab("answer"),
                      setError(""))
                    : ask(q)
                }
                disabled={pending}
              >
                <span>
                  {i === 0
                    ? "The decision that came back"
                    : i === 1
                      ? "A gentler migration"
                      : "When the record is silent"}
                </span>
                <span>
                  {i === 0
                    ? "URL.raw"
                    : i === 1
                      ? "app= shortcut"
                      : "Evidence gap"}
                </span>
              </button>
            ))}
          {recent.map((r) => (
            <Link
              className="recent-report"
              key={r.id}
              href={`/reports/${r.id}`}
            >
              {r.question}
            </Link>
          ))}
          {!isDemo && !recent.length && (
            <p className="rail-empty">Your investigations will appear here.</p>
          )}
        </div>
        <div className="rail-bottom">
          <Link href="/repositories">
            Repositories <ArrowUpRight size={13} />
          </Link>
          <Link href="/credits">
            Sources & credits <ArrowUpRight size={13} />
          </Link>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="workspace-header">
          <div>
            {!rail && (
              <button
                className="icon-button"
                aria-label="Expand sidebar"
                onClick={() => setRail(true)}
              >
                <PanelLeftOpen size={17} />
              </button>
            )}
            <Link href="/repositories">Repositories</Link>
            <ChevronRight size={13} />
            <span>{study.repository.split("/")[1]}</span>
          </div>
          <div>
            <span className="revision">
              <GitBranch size={13} />
              {study.revision.slice(0, 7)}
            </span>
            <button
              className="coverage-button"
              aria-expanded={info}
              onClick={() => setInfo(!info)}
            >
              <Info size={15} /> Index details
            </button>
          </div>
        </header>
        {info && (
          <section className="coverage-panel">
            <strong>A deliberately bounded index</strong>
            <p>
              {study.coverage.scope}. Answers use this source collection and the
              displayed revision; full repository history has not been indexed.
            </p>
            <span>Index {study.index_id}</span>
            {!!study.coverage.excluded?.length && (
              <details>
                <summary>Collection limits and omissions</summary>
                <ul>
                  {study.coverage.excluded.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </details>
            )}
            {study.generated_at && (
              <p>
                Answer saved{" "}
                {new Date(study.generated_at).toLocaleString("en-GB", {
                  timeZone: "UTC",
                })}{" "}
                UTC{study.model ? ` · ${study.model}` : ""}
              </p>
            )}
          </section>
        )}
        <main className="investigation-main">
          <div className="investigation-label">
            <span>{study.repository}</span>
            <span>
              {empty
                ? "Ready for your first question"
                : saved || study.cached
                  ? "Saved investigation"
                  : "New investigation"}
            </span>
          </div>
          <h1>{study.question}</h1>
          <Tabs.Root
            value={tab}
            onValueChange={setTab}
            className="investigation-tabs"
          >
            <div className="answer-toolbar">
              <Tabs.List aria-label="Investigation view">
                <Tabs.Trigger value="answer">Answer</Tabs.Trigger>
                <Tabs.Trigger value="sources">
                  Sources <span>{study.sources.length}</span>
                </Tabs.Trigger>
                <Tabs.Trigger value="timeline">Timeline</Tabs.Trigger>
                <Tabs.Trigger value="connections">Connections</Tabs.Trigger>
              </Tabs.List>
              <div className="report-actions">
                {study.report_id && (
                  <button
                    className="icon-button"
                    aria-label="Copy share link"
                    onClick={share}
                  >
                    {shared ? <Check size={16} /> : <Link2 size={16} />}
                  </button>
                )}
                {!empty && (
                  <button
                    className="icon-button"
                    aria-label="Download investigation as JSON"
                    onClick={download}
                  >
                    <Download size={16} />
                  </button>
                )}
                <button
                  disabled={empty}
                  className="icon-button"
                  aria-label="Copy answer and source links"
                  onClick={copy}
                >
                  {copied ? <Check size={16} /> : <Copy size={16} />}
                </button>
              </div>
            </div>
            <Tabs.Content value="answer" className="answer-content">
              {!empty && (
                <div className="answer-status">
                  <span className={`status-marker ${study.answer.status}`} />
                  <span>
                    {study.answer.status === "supported"
                      ? "Supported by the record"
                      : study.answer.status === "insufficient"
                        ? "The record does not establish this"
                        : study.answer.status === "partial"
                          ? "Partly supported by the record"
                          : "Conflicting evidence"}
                  </span>
                  <span className="answer-duration">
                    {study.seconds}s · Vertex + graph
                  </span>
                </div>
              )}
              <h2>{inlineCode(study.answer.title.replace(/[.!]+$/, ""))}</h2>
              {empty && (
                <p className="empty-investigation">
                  Ask why an API changed, what motivated a design choice, or
                  whether a later decision replaced it. Each explanation will
                  point back to the captured record.
                </p>
              )}
              <div className="answer-claims">
                {study.answer.claims.map((claim, i) => (
                  <div className="answer-claim" key={i}>
                    <p>{inlineCode(claim.text)}</p>
                    {claim.support === "inferred" && (
                      <span className="inference-label">
                        Inference from the cited record
                      </span>
                    )}
                    <div className="claim-citations">
                      {claim.citations
                        .filter(
                          (c, j, all) =>
                            all.findIndex(
                              (other) => other.source_id === c.source_id,
                            ) === j,
                        )
                        .map((c, j) => {
                          const s = study.sources.find(
                            (s) => s.id === c.source_id,
                          );
                          return (
                            <button
                              key={j}
                              onClick={() => open(c.source_id, c)}
                              aria-label={`Inspect evidence: ${s?.title}`}
                            >
                              <SourceIcon kind={s?.kind || "comment"} />
                              <span>
                                {s?.kind === "pull_request"
                                  ? c.source_id.replace("pr-", "PR #")
                                  : s?.kind === "issue"
                                    ? c.source_id.replace("issue-", "Issue #")
                                    : s?.author || "Source"}
                              </span>
                              <ArrowUpRight size={12} />
                            </button>
                          );
                        })}
                    </div>
                  </div>
                ))}
              </div>
              {study.answer.unknowns.length > 0 && (
                <div className="unknowns">
                  <h3>What remains unknown</h3>
                  {study.answer.unknowns.map((t) => (
                    <p key={t}>{t}</p>
                  ))}
                </div>
              )}
              {!empty && (
                <div className="temporal-note">
                  <GitBranch size={16} />
                  <p>{study.answer.temporal_note}</p>
                </div>
              )}
              {!empty && (
                <p className="answer-limit">
                  Citations match captured passages. That check alone does not
                  establish that every interpretation is correct.
                </p>
              )}
              {study.report_id && (
                <Link
                  className="saved-report-link"
                  href={`/reports/${study.report_id}`}
                >
                  Saved investigation · open permanent link{" "}
                  <ArrowUpRight size={12} />
                </Link>
              )}
            </Tabs.Content>
            <Tabs.Content value="sources" className="sources-list">
              <p className="tab-description">
                The source passages retrieved for this investigation
              </p>
              {study.sources.map((s) => (
                <button
                  className="source-list-row"
                  key={s.id}
                  onClick={() => open(s.id)}
                >
                  <SourceIcon kind={s.kind} />
                  <span>
                    <strong>{s.title}</strong>
                    <small>
                      {s.author} · {formatDate(s.date)}
                    </small>
                  </span>
                  <ArrowUpRight size={16} />
                </button>
              ))}
            </Tabs.Content>
            <Tabs.Content value="timeline" className="decision-timeline">
              <p className="tab-description">
                Dated assertions from the indexed sources. A later date alone
                does not establish a replacement.
              </p>
              {study.decisions?.length ? (
                [...study.decisions]
                  .sort((a, b) => a.date.localeCompare(b.date))
                  .map((d) => (
                    <article key={d.id} className="decision-entry">
                      <div className="decision-date">
                        <time>{formatDate(d.date)}</time>
                        <span>
                          {d.outcome === "merged"
                            ? "Merged change"
                            : "Proposal"}
                        </span>
                      </div>
                      <div>
                        <h3>
                          {d.subject} <span>· {d.aspect}</span>
                        </h3>
                        <p>{d.summary}</p>
                        {d.status === "replaced_in_aspect" && (
                          <p className="decision-qualification">
                            A later recorded change replaces this aspect.
                          </p>
                        )}
                        {d.replacement && (
                          <p className="decision-qualification">
                            Qualified replacement · {d.replacement.aspect}.{" "}
                            {d.replacement.note}
                          </p>
                        )}
                        <button
                          className="text-link"
                          onClick={() =>
                            open(
                              d.citations[0]?.source_id || d.source_id,
                              d.citations[0],
                            )
                          }
                        >
                          Inspect supporting passage <ArrowUpRight size={12} />
                        </button>
                      </div>
                    </article>
                  ))
              ) : study.sources.length ? (
                [...study.sources]
                  .filter((s) =>
                    ["pull_request", "issue", "commit"].includes(s.kind),
                  )
                  .sort((a, b) => a.date.localeCompare(b.date))
                  .map((s) => (
                    <article className="decision-entry" key={s.id}>
                      <div className="decision-date">
                        <time>{formatDate(s.date)}</time>
                        <span>{s.kind.replaceAll("_", " ")}</span>
                      </div>
                      <div>
                        <h3>{s.title}</h3>
                        <p>{s.author}</p>
                        <button
                          className="text-link"
                          onClick={() => open(s.id)}
                        >
                          Inspect dated source <ArrowUpRight size={12} />
                        </button>
                      </div>
                    </article>
                  ))
              ) : (
                <p>
                  No dated decision evidence has been retrieved. Ask a question
                  to begin.
                </p>
              )}
            </Tabs.Content>
            <Tabs.Content value="connections" className="connections-list">
              {!!study.paths.length && (
                <EvidenceGraph study={study} open={open} />
              )}
              <p className="tab-description">
                Recorded relationships used to connect the source material
              </p>
              {study.paths.length ? (
                study.paths.map((p, i) => (
                  <div className="connection-row" key={i}>
                    <button onClick={() => open(p.source)}>
                      {connectionLabel(p.source)}
                    </button>
                    <span>
                      {p.relation.toLowerCase().replaceAll("_", " ")}{" "}
                      <ArrowRightSmall />
                    </span>
                    <button onClick={() => open(p.target)}>
                      {connectionLabel(p.target)}
                    </button>
                  </div>
                ))
              ) : (
                <p>
                  No explicit source relationships were retrieved for this
                  question.
                </p>
              )}
            </Tabs.Content>
          </Tabs.Root>
        </main>
        <div className="composer-wrap">
          {error && (
            <p className="request-error" role="alert">
              {error}
            </p>
          )}
          <form
            className="question-composer"
            onSubmit={(e) => {
              e.preventDefault();
              ask();
            }}
          >
            <label htmlFor="question" className="sr-only">
              Ask about the indexed repository history
            </label>
            <textarea
              ref={input}
              disabled={pending}
              id="question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask why. Follow a decision. Question the history."
              maxLength={800}
              rows={2}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask();
                }
              }}
            />
            <div className="composer-bottom">
              <span aria-live="polite">
                {pending
                  ? pendingMessage
                  : "Captured repository history · questions run live"}
              </span>
              <button
                className="send-button"
                disabled={pending || question.trim().length < 8}
                aria-label="Ask question"
              >
                {pending ? (
                  <LoaderCircle className="loading-icon" size={18} />
                ) : (
                  <ArrowUp size={18} />
                )}
              </button>
            </div>
          </form>
          <p className="composer-caption">
            Historical evidence, explicit limits.{" "}
            <button onClick={() => setInfo(true)}>See index coverage</button>
          </p>
        </div>
      </div>
      <EvidenceInspector
        open={!!selected}
        source={selected?.source}
        citation={selected?.citation}
        onClose={() => setSelected(null)}
        onReturnFocus={() => evidenceOpener.current?.focus()}
      />
    </div>
  );
}
function ArrowRightSmall() {
  return <span aria-hidden="true">→</span>;
}

function inlineCode(text: string) {
  return text
    .split(/(`[^`]+`)/g)
    .map((part, i) =>
      part.startsWith("`") && part.endsWith("`") ? (
        <code key={i}>{part.slice(1, -1)}</code>
      ) : (
        part
      ),
    );
}
