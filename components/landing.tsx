"use client";
import Link from "next/link";
import { useState, useRef } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  ChevronRight,
  GitCommitHorizontal,
  GitPullRequest,
  MessageSquare,
  CornerDownRight,
} from "lucide-react";
import { Brand } from "./brand";
import { EvidenceInspector } from "./evidence";
import type { Study, Source, Citation } from "@/lib/study";

export default function Landing({ study }: { study: Study }) {
  const [selected, setSelected] = useState<{
    source: Source;
    citation?: Citation;
  } | null>(null);
  const evidenceOpener = useRef<HTMLElement | null>(null);
  const lookup = (id: string) => study.sources.find((s) => s.id === id);
  const open = (id: string) => {
    const source = lookup(id);
    if (source) {
      evidenceOpener.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      const citation = study.answer.claims
        .flatMap((c) => c.citations)
        .find((c) => c.source_id === id);
      setSelected({ source, citation });
    }
  };
  const trail = [
    {
      id: "pr-2241",
      label: "A decision",
      value: "Remove RawURL",
      date: "May 2022",
      Icon: GitPullRequest,
    },
    {
      id: "issue-2462",
      label: "A consequence",
      value: "A dependency breaks",
      date: "November 2022",
      Icon: MessageSquare,
    },
    {
      id: "pr-2481",
      label: "A revision",
      value: "Restore URL.raw",
      date: "December 2022",
      Icon: GitCommitHorizontal,
    },
  ];
  return (
    <div className="landing">
      <header className="site-header">
        <Brand />
        <nav aria-label="Main navigation">
          <a href="#method">The method</a>
          <Link href="/repositories">Repositories</Link>
          <Link className="nav-action" href="/investigate">
            Open workbench <ArrowRight size={15} />
          </Link>
        </nav>
      </header>
      <main>
        <section className="hero">
          <div className="hero-intro">
            <h1>
              Know <span>why</span>
              <br />
              this code exists.
            </h1>
            <div className="hero-aside">
              <p>
                Code tells you what.
                <br />
                The history tells you why.
              </p>
              <p>
                Follow the decisions, discussions and changes behind a real
                repository.
              </p>
              <Link className="primary-button" href="/investigate">
                Follow the evidence <ArrowRight size={17} />
              </Link>
            </div>
          </div>
          <div className="investigation-preview">
            <div className="preview-heading">
              <span className="repo-name">
                encode / <strong>httpx</strong>
              </span>
              <span className="preview-caption">
                An actual decision, revisited
              </span>
              <span className="preview-revision">
                {study.revision.slice(0, 7)}
              </span>
            </div>
            <div className="preview-body">
              <div className="preview-question">
                <span className="question-corner">
                  <CornerDownRight size={18} />
                </span>
                <h2>
                  Why was <code>URL.raw</code>
                  <br />
                  removed, then brought back?
                </h2>
                <p>
                  The implementation had changed.
                  <br />
                  Its users still depended on it.
                </p>
                <Link className="text-link" href="/investigate">
                  Read the investigation <ArrowUpRight size={16} />
                </Link>
              </div>
              <div className="evidence-story">
                <div className="story-trail">
                  {trail.map(({ id, label, value, date, Icon }, i) => (
                    <div className="trail-step" key={id}>
                      <div className="trail-node">
                        <Icon size={18} strokeWidth={1.5} />
                      </div>
                      <button
                        onClick={() => open(id)}
                        className={`trail-content ${i === 2 ? "trail-current" : ""}`}
                      >
                        <span className="trail-meta">
                          {label}
                          <span>{date}</span>
                        </span>
                        <span className="trail-name">
                          {value}
                          <ArrowUpRight size={15} />
                        </span>
                      </button>
                    </div>
                  ))}
                </div>
                <div className="story-resolution">
                  <span className="resolution-symbol">↳</span>
                  <span>
                    A partial restoration.
                    <br />
                    <strong>A different decision.</strong>
                  </span>
                </div>
              </div>
            </div>
            <div className="preview-footer">
              <span>Code. Discussion. Decision.</span>
              <span>
                Every step opens its source <ChevronRight size={13} />
              </span>
            </div>
          </div>
        </section>
        <section id="method" className="method-section">
          <div className="section-margin">The method</div>
          <div className="method-copy">
            <h2>
              An answer is only as useful
              <br />
              as the path behind it.
            </h2>
            <div className="method-columns">
              <p>
                Start with a question. Find the code that matters, follow its
                changes into the discussion, and inspect the reason in the words
                of the people who were there.
              </p>
              <p>
                Decisions have a history, too. See when an approach changed,
                what replaced it, and where the available evidence stops.
              </p>
            </div>
          </div>
        </section>
        <section className="honesty-section">
          <div className="honesty-question">
            And when the reason
            <br />
            was never recorded?
          </div>
          <div>
            <p className="honesty-answer">
              “I can show you the implementation.
              <br />
              The indexed history doesn’t establish why.”
            </p>
            <p className="secondary-copy">
              Knowing where the record ends is part of the answer.
            </p>
            <Link className="text-link" href="/investigate?case=unknown">
              Explore an evidence gap <ArrowUpRight size={16} />
            </Link>
          </div>
        </section>
      </main>
      <footer className="site-footer">
        <Brand small />
        <span>Built around the record.</span>
        <div>
          <span>Public source history · HTTPX example</span>
          <a href="/credits">
            Sources & credits <ArrowUpRight size={13} />
          </a>
        </div>
      </footer>
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
