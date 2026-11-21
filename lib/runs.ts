import type { Break, RunKind, RunStatus, RunSummary } from "./dashboard";

export const KIND: Record<RunKind, string> = {
  pull: "Pull request check",
  scan: "Repository scan",
  mcp: "Agent call",
  agent: "Agent work",
};
export const STATUS: Record<RunStatus, string> = {
  running: "Running",
  succeeded: "Succeeded",
  partial: "Partly checked",
  failed: "Failed",
  skipped: "Nothing to do",
};
export const BREAK_STATUS: Record<Break["status"], string> = {
  open: "Open",
  fixed: "Fixed",
  merged: "Merged anyway",
  closed: "Closed unmerged",
};

/** What a failure category means and what to do about it. Categories are exception class names. */
const CAUSE: Record<string, string> = {
  GitHubAppError:
    "GitHub refused the App: it may have lost access to this repository, or hit a rate limit.",
  HTTPStatusError:
    "GitHub, PyPI or OSV.dev answered with an error. These are usually temporary.",
  ConnectError: "A service could not be reached. These are usually temporary.",
  ReadTimeout:
    "A service took too long to answer. These are usually temporary.",
  ConnectTimeout: "A service could not be reached in time.",
  ArtifactError:
    "A release file could not be downloaded or did not match its published checksum.",
  RateLimited: "GitHub's rate limit was reached; it resets within the hour.",
  ValueError: "The repository is larger than the 300 MB limit.",
  BrokenProcessPool:
    "The analysis ran out of memory or was stopped before it finished.",
  OperationalError: "The database was briefly unavailable.",
  "not-found": "The App can no longer read this repository.",
};

export function failure(run: RunSummary): {
  title: string;
  cause: string;
  next: string;
} | null {
  if (run.status !== "failed" && run.status !== "partial") return null;
  const unreadable = (run.summary?.unreadable as string[] | undefined) || [];
  if (run.status === "partial")
    return {
      title: "Partly checked",
      cause: unreadable.length
        ? `The release files of ${unreadable.join(", ")} could not be read (compiled-only packages, or a download that failed), so those upgrades say Not checked.`
        : "Some of the work could not be completed.",
      next: "Everything else in this run was checked normally.",
    };
  const category = (run.error || "").split(":")[0];
  const message =
    run.kind === "mcp" && run.error?.startsWith("ToolError: ")
      ? run.error.slice("ToolError: ".length)
      : null;
  return {
    title: run.failed_step
      ? `Failed at “${run.failed_step}”`
      : "Failed before its first step",
    cause:
      message ||
      CAUSE[category] ||
      `The step stopped with ${category || "an unexpected error"}.`,
    next:
      run.kind === "mcp"
        ? "The agent got this error back and can retry with corrected arguments."
        : run.kind === "agent"
          ? "Agent work is advice on top of the check; verdicts and alerts are unaffected. It is retried once."
          : run.final
            ? "It will not be retried automatically. Push a commit, or use Scan now, to run it again."
            : "It will be retried automatically within a few minutes.",
  };
}

export function duration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

export function runTitle(run: RunSummary): string {
  if (run.kind === "pull") return `${run.repository} ${run.subject}`;
  if (run.kind === "scan") return `${run.repository}, default branch`;
  return `${run.subject}${run.repository ? ` on ${run.repository}` : ""}`;
}

export function githubLine(
  repository: string,
  ref: string,
  file: string,
  line: number | null,
) {
  return `https://github.com/${repository}/blob/${ref}/${file
    .split("/")
    .map(encodeURIComponent)
    .join("/")}${line ? `#L${line}` : ""}`;
}
