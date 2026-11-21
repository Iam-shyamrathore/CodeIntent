import type { AnalysisStatus, PackageLine, Verdict } from "@/lib/dashboard";
import { LABELS } from "@/lib/dashboard";

const PENDING: Record<AnalysisStatus, string> = {
  queued: "Waiting to analyse",
  running: "Analysing",
  retrying: "Retrying analysis",
  diffed: "Verdict pending",
  analysed: "Verdict pending",
  reported: "Verdict pending",
  skipped: "No Python dependency change",
  failed: "Analysis failed",
};

type Kind = Verdict | "pending" | "failed";

/** Which of the 3×3 dots are lit, row by row: each verdict has its own dot-matrix shape. */
const SHAPES: Record<Kind, string> = {
  breaks: "111111111",
  "needs-change": "101010101",
  "not-checked": "111101111",
  "no-known-impact": "000010000",
  pending: "000111000",
  failed: "101010101",
};

/** The verdict's dot-matrix glyph; decorative, the words beside it carry the meaning. */
export function VerdictGlyph({ kind }: { kind: Kind }) {
  const shape = SHAPES[kind];
  return (
    <svg
      className="ci-glyph"
      viewBox="0 0 12 12"
      aria-hidden="true"
      focusable="false"
    >
      {[...shape].map((on, i) => (
        <circle
          key={i}
          cx={2 + (i % 3) * 4}
          cy={2 + Math.floor(i / 3) * 4}
          r={on === "1" ? 1.55 : 0.6}
          className={on === "1" ? "on" : "off"}
        />
      ))}
    </svg>
  );
}

/** The verdict as words, with its glyph. */
export function VerdictLabel({
  verdict,
  status,
  size = "regular",
}: {
  verdict: Verdict | null;
  status?: AnalysisStatus;
  size?: "regular" | "large";
}) {
  const kind: Kind = verdict || (status === "failed" ? "failed" : "pending");
  const text = verdict ? LABELS[verdict] : PENDING[status || "queued"];
  return (
    <span className={`ci-verdict ci-verdict-${kind} ci-verdict-${size}`}>
      <VerdictGlyph kind={kind} />
      {text}
    </span>
  );
}

export function PackageChanges({ packages }: { packages: PackageLine[] }) {
  if (!packages.length) return null;
  return (
    <ul className="ci-packages" aria-label="Changed packages">
      {packages.map((p, i) => (
        <li key={`${p.package}-${i}`}>
          <code translate="no">{p.package}</code>
          <code>
            {p.start || "added"}
            <span aria-hidden="true"> → </span>
            <span className="sr-only"> to </span>
            {p.end || "removed"}
          </code>
          {p.verdict && packages.length > 1 && (
            <span className="ci-packages-verdict">{LABELS[p.verdict]}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
