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
  /** Latest upcoming-breakage scan of the default branch, if any. */
  upcoming: {
    status: ScanStatus;
    scanned_at: string | null;
    breaks: number;
    needs_change: number;
    advisories: number;
  } | null;
};
export type ScanStatus = "queued" | "running" | "done" | "skipped" | "failed";
/** One direct dependency against its latest release (codeintent/upgrades/upcoming.py). */
export type UpcomingItem = {
  package: string;
  current: string | null;
  latest: string | null;
  status: "compared" | "current" | "not-locked" | "not-on-pypi" | "unreadable";
  location: Location;
  verdict: UpgradeVerdict | null;
  detail: string | null;
  advisories: AdvisoryCheck | null;
  /** Folder of the declaring project, relative to the repository root. */
  project?: string;
  specifier?: string;
  pins?: { kind: string; clause: string }[];
  allows_latest?: boolean | null;
  lift?: "can-be-lifted" | "keep" | "unknown" | null;
  lift_reason?: string | null;
  origin?: PinOrigin | null;
  origin_detail?: string | null;
};
export type PinOrigin = {
  commit: string;
  commit_url?: string | null;
  date?: string | null;
  author?: string | null;
  message: string;
  pr_number?: number | null;
  pr_title?: string | null;
  pr_url?: string | null;
};
export type RepositoryScan = {
  repository: string;
  scan: {
    status: ScanStatus;
    ref: string | null;
    head_sha: string | null;
    error: string | null;
    scanned_at: string | null;
    updated_at: string;
    items: UpcomingItem[];
  } | null;
};
export type UpcomingFinding = {
  repository: string;
  project: string;
  package: string;
  specifier: string;
  lift: "can-be-lifted" | "keep" | "unknown" | null;
  current: string | null;
  latest: string | null;
  verdict: Verdict | null;
  label: string | null;
  reason: string | null;
  places: number;
  advisories: string[];
  scanned_at: string | null;
};
export type UpcomingSummary = {
  totals: { repositories: number; scanned: number; pending: number };
  findings: UpcomingFinding[];
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

/** Operator view of the deployment (codeintent/ops.py). */
export type Ops = {
  at: string;
  worker: { live: number; last_heartbeat: string | null; stalled: boolean };
  queue: {
    waiting: Record<string, number>;
    running: Record<string, number>;
    oldest_waiting: string | null;
    failed_24h: Record<string, number>;
  };
  webhooks_24h: Record<string, number>;
  analyses_24h: Record<string, number>;
  scans: Record<string, number>;
  telegram: { chats: number; alerts_24h: number };
  mcp: { active: number; used_24h: number };
};

export type RunKind = "pull" | "scan" | "mcp";
export type RunStatus =
  "running" | "succeeded" | "partial" | "failed" | "skipped";
export type RunSummary = {
  id: string;
  installation_id: number | null;
  kind: RunKind;
  repository: string | null;
  ref: string | null;
  subject: string;
  status: RunStatus;
  failed_step: string | null;
  error: string | null;
  attempt: number;
  final: boolean;
  analysis_id: string | null;
  summary: Record<string, unknown> | null;
  started_at: string;
  finished_at: string | null;
  duration_ms: number;
};
export type RunStep = {
  seq: number;
  name: string;
  status: "ok" | "failed" | "skipped";
  started_at: string;
  duration_ms: number;
  detail: string | null;
};
export type Place = { file: string; line: number | null; code: string | null };
export type Break = {
  installation_id?: number;
  repository: string;
  source: "pull" | "scan";
  pull_number: number;
  key: string;
  severity: "breaks" | "needs-change";
  package: string;
  start_version: string;
  end_version: string;
  change: Change & { guarded?: boolean };
  decision: UpstreamDecision | null;
  places: Place[];
  status: "open" | "fixed" | "merged" | "closed";
  analysis_id?: string | null;
  first_run?: string | null;
  last_run?: string | null;
  first_seen: string;
  last_seen: string;
  resolved_at: string | null;
  pull_title?: string | null;
};
export type RunDetail = RunSummary & {
  input: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  steps: RunStep[];
  attempts: RunSummary[];
  breaks: Break[];
};
export type GraphNode = {
  id: string;
  label: string;
  name: string;
  props: Record<string, string | number | boolean>;
};
export type GraphEdge = { source: string; target: string; type: string };
export type RunGraph = {
  projected: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
};
export type ImpactLine = {
  installation_id: number;
  repository: string;
  file: string;
  line: number | null;
  code: string | null;
  symbol: string;
  kind: string;
  parameter: string | null;
  version: string;
  replacement: string | null;
  change: string;
  locked: string | null;
  confirmed: boolean;
};
export type Impact = {
  package: string;
  version: string | null;
  repositories: string[];
  lines: ImpactLine[];
};

export type Loaded<T> =
  { state: "ok"; data: T } | { state: "missing" } | { state: "unavailable" };

/** Server-side read from the service API; network and 5xx failures become "unavailable". */
export async function read<T>(
  path: string,
  init?: RequestInit,
): Promise<Loaded<T>> {
  try {
    const response = await service(path, init);
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
