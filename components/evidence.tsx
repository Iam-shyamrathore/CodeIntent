"use client";
import { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowUpRight,
  FileCode2,
  GitPullRequest,
  MessageSquare,
  X,
  ChevronRight,
} from "lucide-react";
import type { Source, Citation } from "@/lib/study";

export function SourceIcon({ kind }: { kind: string }) {
  const Icon =
    kind === "pull_request"
      ? GitPullRequest
      : kind === "code" || kind === "diff"
        ? FileCode2
        : MessageSquare;
  return <Icon size={16} strokeWidth={1.5} aria-hidden="true" />;
}
export function formatDate(date: string) {
  return new Date(date).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function EvidenceInspector({
  source,
  citation,
  open,
  onClose,
  onReturnFocus,
}: {
  source?: Source;
  citation?: Citation;
  open: boolean;
  onClose: () => void;
  onReturnFocus: () => void;
}) {
  const [expandedId, setExpandedId] = useState("");
  const expanded = !!source && expandedId === source.id;
  const body = source?.body || "";
  const at = citation
    ? citation.start !== undefined &&
      body.slice(citation.start, citation.end) === citation.quote
      ? citation.start
      : body.indexOf(citation.quote)
    : -1;
  const before = at >= 0 ? body.slice(Math.max(0, at - 200), at) : "";
  const after =
    at >= 0
      ? body.slice(
          at + citation!.quote.length,
          at + citation!.quote.length + 400,
        )
      : body.slice(0, 600);
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        if (!value) {
          onClose();
          setExpandedId("");
        }
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="source-overlay" />
        <Dialog.Content
          className="source-drawer"
          aria-describedby="source-description"
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            onReturnFocus();
          }}
        >
          <div className="drawer-top">
            <span>Evidence inspector</span>
            <Dialog.Close className="icon-button" aria-label="Close evidence">
              <X size={18} />
            </Dialog.Close>
          </div>
          <div className="source-type">
            <SourceIcon kind={source?.kind || "comment"} />
            {source?.kind.replaceAll("_", " ")}
          </div>
          <Dialog.Title className="source-title">{source?.title}</Dialog.Title>
          <Dialog.Description id="source-description" className="source-meta">
            {source?.author} · {source ? formatDate(source.date) : ""}
          </Dialog.Description>
          <div className="source-excerpt">
            <span>{before}</span>
            {citation && <mark>{citation.quote}</mark>}
            <span>{after}</span>
          </div>
          {citation?.start !== undefined && (
            <p className="source-meta">
              Snapshot characters {citation.start}–{citation.end} · exact
              passage
            </p>
          )}
          <a
            className="text-link"
            href={source?.url}
            target="_blank"
            rel="noreferrer"
          >
            Open original on GitHub <ArrowUpRight size={16} />
          </a>
          <div className="source-context">
            {source?.retrieved_at && (
              <p>
                Captured{" "}
                {new Date(source.retrieved_at).toLocaleString("en-GB", {
                  timeZone: "UTC",
                })}{" "}
                UTC
              </p>
            )}
            {source?.sha256 && (
              <p className="source-hash" title={source.sha256}>
                SHA-256 {source.sha256.slice(0, 16)}…
              </p>
            )}
            <p>
              This is a captured source passage. Its historical date is separate
              from the revision currently indexed.
            </p>
          </div>
          <button
            className="context-toggle"
            aria-expanded={expanded}
            onClick={() => setExpandedId(expanded ? "" : source?.id || "")}
          >
            {" "}
            {expanded ? "Hide" : "Read"} captured context{" "}
            <ChevronRight size={15} />
          </button>
          {expanded && <pre className="full-source">{body}</pre>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
