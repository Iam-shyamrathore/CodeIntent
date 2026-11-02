import fs from "node:fs";
import path from "node:path";

export interface Citation {
  source_id: string;
  quote: string;
  start?: number;
  end?: number;
}
export interface Claim {
  text: string;
  support: string;
  citations: Citation[];
}
export interface Source {
  id: string;
  title: string;
  body: string;
  kind: string;
  date: string;
  author: string;
  url: string;
  sha256?: string;
  retrieved_at?: string;
  merged_at?: string;
  path?: string;
}
export interface Study {
  question: string;
  answer: {
    title: string;
    status: string;
    claims: Claim[];
    unknowns: string[];
    temporal_note: string;
  };
  sources: Source[];
  paths: {
    source: string;
    target: string;
    relation: string;
    evidence: string;
  }[];
  repository: string;
  revision: string;
  index_id: string;
  seconds: number;
  mode: string;
  report_id?: string;
  cached?: boolean;
  generated_at?: string;
  model?: string;
  decisions?: Decision[];
  coverage: {
    scope: string;
    full_repository_history: boolean;
    excluded?: string[];
  };
}
export function readStudy(name: "rawurl" | "unknown" = "rawurl"): Study {
  return JSON.parse(
    fs.readFileSync(
      path.join(process.cwd(), `fixtures/studies/${name}.json`),
      "utf8",
    ),
  );
}

export interface Decision {
  id: string;
  subject: string;
  aspect: string;
  summary: string;
  action: string;
  source_id: string;
  date: string;
  outcome: string;
  status: string;
  citations: Citation[];
  paths: string[];
  replacement?: {
    decision_id: string;
    aspect: string;
    support: string;
    note: string;
  } | null;
}
export function emptyStudy(
  repository: string,
  revision: string,
  index: string,
  coverage: Study["coverage"],
): Study {
  return {
    repository,
    revision,
    index_id: index,
    coverage,
    question: "What would you like to understand?",
    answer: {
      title: "Start with a decision, a symbol, or a change",
      status: "empty",
      claims: [],
      unknowns: [],
      temporal_note: "",
    },
    sources: [],
    paths: [],
    seconds: 0,
    mode: "empty",
  };
}
