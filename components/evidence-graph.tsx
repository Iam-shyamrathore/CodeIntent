"use client";
import {
  ReactFlow,
  Controls,
  Position,
  type Node,
  type Edge,
} from "@xyflow/react";
import type { Study } from "@/lib/study";
import "@xyflow/react/dist/style.css";
export default function EvidenceGraph({
  study,
  open,
}: {
  study: Study;
  open: (id: string) => void;
}) {
  const ids = new Set(study.paths.flatMap((p) => [p.source, p.target]));
  const cited = new Set(
    study.answer.claims.flatMap((c) => c.citations.map((r) => r.source_id)),
  );
  const columns: Record<string, number> = {
    pull_request: 1,
    issue: 0,
    comment: 0,
    review: 0,
    review_comment: 0,
    diff: 2,
    code: 2,
    commit: 2,
  };
  const perColumn = [0, 0, 0];
  const sources = [...study.sources]
    .filter((s) => ids.has(s.id))
    .sort(
      (a, b) =>
        Number(cited.has(b.id)) - Number(cited.has(a.id)) ||
        a.date.localeCompare(b.date),
    )
    .filter((s) => {
      const col = columns[s.kind] ?? 1;
      if (perColumn[col] >= 3) return false;
      perColumn[col]++;
      return true;
    });
  const counts = [0, 0, 0];
  const nodes: Node[] = sources.map((s) => {
    const col = columns[s.kind] ?? 1;
    return {
      id: s.id,
      position: { x: col * 330, y: counts[col]++ * 130 },
      data: {
        label: (
          <button
            className="graph-source nodrag nopan"
            onClick={() => open(s.id)}
            title={s.title}
          >
            <small>{s.kind.replaceAll("_", " ")}</small>
            <strong>{s.title}</strong>
            <span>{s.author}</span>
          </button>
        ),
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      style: { width: 250 },
      ariaLabel: `Inspect ${s.title}`,
    };
  });
  const available = new Set(nodes.map((n) => n.id));
  const edges: Edge[] = study.paths
    .filter((p) => available.has(p.source) && available.has(p.target))
    .map((p, i) => ({
      id: String(i),
      source: p.source,
      target: p.target,
      label: p.relation.toLowerCase().replaceAll("_", " "),
      type: "smoothstep",
      style: { stroke: "#9daab7" },
      labelStyle: { fontSize: 10, fill: "#566570" },
      labelBgStyle: { fill: "#f7f8f8" },
    }));
  if (!nodes.length) return null;
  return (
    <div
      className="evidence-graph"
      aria-label="Selected evidence relationships, up to three sources per column. The complete relationship list follows."
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodesDraggable={false}
        nodesConnectable={false}
        deleteKeyCode={null}
        fitView
        minZoom={0.25}
        maxZoom={1.5}
        onNodeClick={(_, node) => open(node.id)}
      >
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
