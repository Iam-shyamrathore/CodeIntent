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

/** The verdict as words; the marker repeats it visually and is hidden from assistive technology. */
export function VerdictLabel({
  verdict,
  status,
  size = "regular",
}: {
  verdict: Verdict | null;
  status?: AnalysisStatus;
  size?: "regular" | "large";
}) {
  const kind = verdict || (status === "failed" ? "failed" : "pending");
  const text = verdict ? LABELS[verdict] : PENDING[status || "queued"];
  return (
    <span className={`verdict-label verdict-${kind} verdict-${size}`}>
      <span className="verdict-marker" aria-hidden="true" />
      {text}
    </span>
  );
}

export function PackageChanges({ packages }: { packages: PackageLine[] }) {
  if (!packages.length) return null;
  return (
    <ul className="package-changes" aria-label="Changed packages">
      {packages.map((p, i) => (
        <li key={`${p.package}-${i}`}>
          <code>{p.package}</code>
          <span>
            {p.start || "added"}
            <span aria-hidden="true"> → </span>
            <span className="sr-only"> to </span>
            {p.end || "removed"}
          </span>
          {p.verdict && packages.length > 1 && <em>{LABELS[p.verdict]}</em>}
        </li>
      ))}
    </ul>
  );
}
