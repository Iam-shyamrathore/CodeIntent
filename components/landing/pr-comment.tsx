import { ArrowUpRight } from "lucide-react";
import {
  DEMO_PR,
  DEMO_REPORT,
  HTTPX_2879,
  HTTPX_3319,
  HTTPX_QUOTE_COMMIT,
} from "./links";
import { CommentTabs } from "./comment-tabs";
import { VerdictMark } from "./verdict-mark";

interface Row {
  where: string;
  target: string;
}

interface Comment {
  to: string;
  reason: string;
  rows: Row[];
  facts: React.ReactNode;
  report?: string;
}

const OPENAI: Comment = {
  to: "0.28.0",
  reason: "2 change(s) in httpx 0.28.0 break code you use, at 3 place(s).",
  rows: [
    {
      where: "src/openai/_base_client.py:1438",
      target: "httpx.AsyncClient(proxies=)",
    },
    {
      where: "src/openai/_base_client.py:857",
      target: "httpx.Client(proxies=)",
    },
    { where: "src/openai/cli/_cli.py:179", target: "httpx.Client(proxies=)" },
  ],
  facts: (
    <>
      0.28.0: no known advisories · 0.27.2: no known advisories ·{" "}
      <a href="https://github.com/encode/httpx/compare/0.27.2...0.28.0">
        upstream changes
      </a>
    </>
  ),
};

const DEMO: Comment = {
  to: "0.28.1",
  reason: "1 change(s) in httpx 0.28.1 break code you use, at 1 place(s).",
  rows: [{ where: "weather/client.py:12", target: "httpx.Client(proxies=)" }],
  facts: (
    <>
      Compared 4 of 4 use(s) in 1 file(s) · 0.28.1: no known advisories ·
      0.27.2: no known advisories ·{" "}
      <a href="https://github.com/encode/httpx/compare/0.27.2...0.28.1">
        upstream changes
      </a>
    </>
  ),
  report: DEMO_REPORT,
};

const Note = ({ n }: { n: number }) => (
  <span className="lp-note-ref" aria-label={`note ${n}`}>
    {n}
  </span>
);

function CommentCard({
  comment,
  annotate,
}: {
  comment: Comment;
  annotate: boolean;
}) {
  return (
    <article
      className="gh-comment"
      aria-label="CodeIntent pull request comment"
    >
      <header className="gh-comment-head">
        <span className="gh-avatar" aria-hidden="true">
          [<span>·</span>]
        </span>
        <span className="gh-author">codeintent-dependency-check</span>
        <span className="gh-bot">bot</span>
        <span className="gh-meta">commented</span>
      </header>
      <div className="gh-body">
        <h3 className="gh-h3">CodeIntent: Breaks you</h3>
        <h4 className="gh-h4">
          <VerdictMark kind="breaks" />
          Breaks you: <code>httpx</code> 0.27.2 → {comment.to}
        </h4>
        <p>{comment.reason}</p>
        <div className="gh-table-wrap" tabIndex={0} aria-label="Findings table">
          <table className="gh-table">
            <thead>
              <tr>
                <th scope="col">
                  <span className="sr-only">Severity</span>
                </th>
                <th scope="col">
                  Where in your code {annotate ? <Note n={1} /> : null}
                </th>
                <th scope="col">What changed</th>
                <th scope="col">
                  Use instead {annotate ? <Note n={2} /> : null}
                </th>
              </tr>
            </thead>
            <tbody>
              {comment.rows.map((row) => (
                <tr key={row.where}>
                  <td>Breaks</td>
                  <td>
                    <code className="gh-where">{row.where}</code>
                  </td>
                  <td>
                    <code>{row.target}</code> no longer accepts this argument
                  </td>
                  <td>
                    <code>proxy= or mounts=</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          <strong>Why:</strong> <code>proxies=</code> changed in{" "}
          <a href={HTTPX_3319}>
            #3319 Introduce new <code>SSLContext</code> API &amp; escalate
            deprecations.
          </a>
          , deprecated earlier in <a href={HTTPX_2879}>#2879</a>.{" "}
          {annotate ? <Note n={3} /> : null}
        </p>
        <blockquote>
          “The deprecated <code>proxies</code> argument has now been removed.” (
          <a href={HTTPX_QUOTE_COMMIT}>source</a>)
        </blockquote>
        <blockquote>
          httpx 0.27.2 says: “The &apos;proxies&apos; argument is now
          deprecated. Use &apos;proxy&apos; or &apos;mounts&apos; instead.”{" "}
          {annotate ? <Note n={4} /> : null}
        </blockquote>
        <p className="gh-facts">
          {comment.facts} {annotate ? <Note n={5} /> : null}
        </p>
        <p className="gh-sub">
          {comment.report ? (
            <>
              <a href={comment.report}>Full report</a> ·{" "}
            </>
          ) : null}
          Verdicts come from static analysis of both releases; CodeIntent never
          runs your code or the library, and never calls an upgrade safe.
        </p>
      </div>
    </article>
  );
}

const NOTES = [
  [
    "The exact line in your code",
    "Every call that breaks, by file and line. Not a package name and a changelog link.",
  ],
  [
    "The library’s own replacement",
    "Taken from the deprecation message the library shipped, never guessed.",
  ],
  [
    "Why upstream changed it",
    "The pull request that removed it and the one that deprecated it. The quote is checked word for word against GitHub.",
  ],
  [
    "What the old release already said",
    "httpx warned in 0.27.2. CodeIntent shows that warning beside the break.",
  ],
  [
    "Advisories and coverage",
    "OSV.dev advisories for both versions, and how many of your uses were compared.",
  ],
] as const;

export function CommentSection() {
  return (
    <section
      className="lp-section lp-comment"
      id="comment"
      aria-labelledby="comment-title"
    >
      <div className="lp-wrap">
        <div className="lp-section-head" data-reveal>
          <p className="lp-index">§ 01 — On the pull request</p>
          <h2 id="comment-title">
            One comment. The line that breaks, the fix, and the reason.
          </h2>
          <p className="lp-lede">
            On 28 November 2024 httpx 0.28.0 removed the <code>proxies=</code>{" "}
            argument. openai-python v1.54.4 accepted any httpx below 1.0 and
            still passed <code>proxies=</code>, so fresh installs broke. This is
            the comment CodeIntent writes for that upgrade.
          </p>
        </div>
        <div className="lp-comment-grid">
          <div className="lp-bezel lp-comment-frame" data-reveal>
            <div className="lp-bezel-core">
              <CommentTabs
                labels={[
                  "openai-python v1.54.4 → httpx 0.28.0",
                  "Live PR · codeintent-demo #1",
                ]}
                panels={[
                  <div key="openai">
                    <CommentCard comment={OPENAI} annotate />
                    <p className="lp-comment-caption">
                      openai-python at v1.54.4, checked against httpx 0.28.0,
                      the release that broke it. Rendered from CodeIntent’s
                      output for that commit.
                    </p>
                  </div>,
                  <div key="demo">
                    <CommentCard comment={DEMO} annotate={false} />
                    <p className="lp-comment-caption">
                      Posted by the App on a real Dependabot pull request.{" "}
                      <a href={DEMO_PR}>
                        Open it on GitHub{" "}
                        <ArrowUpRight size={13} aria-hidden="true" />
                      </a>
                    </p>
                  </div>,
                ]}
              />
            </div>
          </div>
          <ol className="lp-notes" data-reveal>
            {NOTES.map(([title, body], index) => (
              <li key={title}>
                <span className="lp-note-ref" aria-hidden="true">
                  {index + 1}
                </span>
                <div>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
