import "server-only";
import { service } from "./server-api";

export type Verdict =
  "breaks" | "not-checked" | "needs-change" | "no-known-impact";
export type Location = { file: string; line?: number; column?: number };
export type Change = {
  kind:
    | "removed"
    | "parameter-removed"
    | "parameter-required"
    | "parameter-moved"
    | "default-changed"
    | "deprecated";
  symbol: string;
  parameter?: string | null;
  detail: string;
  message?: string | null;
  message_version?: string | null;
  replacement?: string | null;
  replacement_source?: "message" | "message-unverified" | "signature" | null;
  before?: Location | null;
  after?: Location | null;
};
export type Finding = {
  severity: "breaks" | "needs-change";
  guarded?: boolean;
  change: Change;
  locations: Location[];
};
export type Unchecked = {
  reason: string;
  detail: string;
  location: Location;
  symbol?: string | null;
};
export type Coverage = {
  files: number;
  usages: number;
  checked: number;
  unchecked: number;
  unchanged_unchecked: number;
  upstream_changes: number;
};
export type ReleasePoint = {
  version: string;
  published?: string | null;
  yanked?: boolean;
  tag?: string | null;
  commit?: string | null;
};
export type ReleaseRange = {
  package: string;
  repository?: string | null;
  start: ReleasePoint;
  end: ReleasePoint;
  not_located?: string | null;
};
export type Advisory = {
  id: string;
  aliases?: string[];
  summary?: string | null;
  severity?: string | null;
  fixed?: string | null;
  withdrawn?: boolean;
  url: string;
};
export type AdvisoryCheck = {
  package: string;
  version: string;
  status: "advisories" | "none-known" | "not-checked";
  advisories?: Advisory[];
  detail?: string | null;
};
export type UpstreamQuote = {
  text: string;
  source_url: string;
  source_kind: string;
};
/** The upstream pull request behind one change (codeintent/upgrades/upstream.py). */
export type UpstreamDecision = {
  change_key: { symbol: string; parameter?: string | null; kind: string };
  pr_number?: number | null;
  pr_title?: string | null;
  pr_url?: string | null;
  quotes?: UpstreamQuote[];
  deprecation?: {
    pr_number?: number | null;
    pr_title?: string | null;
    pr_url?: string | null;
  } | null;
  reversal?: string | null;
  not_found?: string | null;
};
export type UpgradeVerdict = {
  package: string;
  start: string;
  end: string;
  verdict: Verdict;
  label: string;
  reason: string;
  findings?: Finding[];
  unchecked?: Unchecked[];
  limits?: Unchecked[];
  coverage?: Coverage | null;
  release?: ReleaseRange | null;
  advisories?: AdvisoryCheck[];
  decisions?: UpstreamDecision[];
};
export type PackageLine = {
  package: string | null;
  start: string | null;
  end: string | null;
  verdict: Verdict | null;
  label: string | null;
};
export type AnalysisStatus =
  | "queued"
  | "running"
  | "retrying"
  | "diffed"
  | "skipped"
  | "analysed"
  | "reported"
  | "failed";
export type PullSummary = {
  id: string;
  installation_id: number;
  repository: string;
  number: number;
  title: string | null;
  head_sha: string;
  status: AnalysisStatus;
  verdict: Verdict | null;
  packages: PackageLine[];
  error: string | null;
  created_at: string;
  updated_at: string;
};
export type ManifestChange = {
  name: string;
  file: string;
  old?: { specifier?: string; locked_version?: string | null };
  new?: { specifier?: string; locked_version?: string | null };
};
export type PullDetail = PullSummary & {
  base_sha: string;
  account_login: string;
  private: boolean;
  diff: {
    files?: string[];
    added?: unknown[];
    removed?: unknown[];
    changed?: ManifestChange[];
    issues?: { reason: string; detail: string; location: Location }[];
  } | null;
  verdicts: UpgradeVerdict[];
};
export type Installation = {
  id: number;
  account_login: string;
  account_type: string;
  suspended: boolean;
  repositories: number;
  analyses: number;
};
export type InstalledRepository = {
  repository_id: number;
  full_name: string;
  private: boolean;
  analyses: number;
  verdict_counts: Record<Verdict, number>;
  last_analysis: {
    id: string;
    number: number;
    title: string | null;
    status: AnalysisStatus;
    verdict: Verdict | null;
    created_at: string;
  } | null;
  /** The newest analysis that reached a verdict; may be older than last_analysis. */
  last_verdict: {
    id: string;
    number: number;
    title: string | null;
    verdict: Verdict;
    created_at: string;
  } | null;
};
export type RepositoryPulls = {
  repository: {
    full_name: string;
    private: boolean;
    installation_id: number;
    account_login: string;
  };
  pulls: PullSummary[];
  next_cursor: string | null;
};

export type Loaded<T> =
  { state: "ok"; data: T } | { state: "missing" } | { state: "unavailable" };

/** Server-side read from the service API; network and 5xx failures become "unavailable". */
export async function read<T>(path: string): Promise<Loaded<T>> {
  try {
    const response = await service(path);
    if (response.status === 404) return { state: "missing" };
    if (!response.ok) return { state: "unavailable" };
    return { state: "ok", data: (await response.json()) as T };
  } catch {
    return { state: "unavailable" };
  }
}

export const VERDICT_ORDER: Verdict[] = [
  "breaks",
  "not-checked",
  "needs-change",
  "no-known-impact",
];
export const LABELS: Record<Verdict, string> = {
  breaks: "Breaks you",
  "needs-change": "Needs a change",
  "not-checked": "Not checked",
  "no-known-impact": "No known impact",
};
export const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const GITHUB_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;

export function formatDate(value: string) {
  return new Date(value).toLocaleDateString("en-GB", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function pullUrl(repository: string, number: number) {
  return `https://github.com/${repository}/pull/${number}`;
}

/** `httpx._client.Client` as users import it: `httpx.Client`. Mirrors `_target` in codeintent/upgrades/report.py. */
export function publicSymbol(symbol: string): string {
  return symbol
    .split(".")
    .filter(
      (part, index) =>
        index === 0 || !part.startsWith("_") || part.startsWith("__"),
    )
    .join(".");
}
