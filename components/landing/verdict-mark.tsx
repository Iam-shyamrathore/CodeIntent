export type VerdictKind =
  "breaks" | "needs-change" | "not-checked" | "no-known-impact";

export const VERDICT_LABEL: Record<VerdictKind, string> = {
  breaks: "Breaks you",
  "needs-change": "Needs a change",
  "not-checked": "Not checked",
  "no-known-impact": "No known impact",
};

/** One drawn mark per verdict, so a verdict never depends on colour alone. There is no tick. */
export function VerdictMark({
  kind,
  size = 14,
}: {
  kind: VerdictKind;
  size?: number;
}) {
  return (
    <svg
      className="lp-mark"
      data-kind={kind}
      width={size}
      height={size}
      viewBox="0 0 14 14"
      aria-hidden="true"
      focusable="false"
    >
      {kind === "breaks" ? (
        <>
          <rect x="1.5" y="1.5" width="11" height="11" rx="1.5" />
          <path d="M4.6 4.6l4.8 4.8M9.4 4.6l-4.8 4.8" />
        </>
      ) : kind === "needs-change" ? (
        <>
          <path d="M7 1.8l5.6 10H1.4z" />
          <path d="M7 5.6v3" />
          <circle cx="7" cy="10.2" r="0.35" />
        </>
      ) : kind === "not-checked" ? (
        <>
          <circle cx="7" cy="7" r="5.4" strokeDasharray="2 1.6" />
          <path d="M5.4 5.6a1.7 1.7 0 113 1.1c-.6.4-1.4.7-1.4 1.6" />
          <circle cx="7" cy="10.2" r="0.35" />
        </>
      ) : (
        <>
          <circle cx="7" cy="7" r="5.4" />
          <path d="M4.4 7h5.2" />
        </>
      )}
    </svg>
  );
}
