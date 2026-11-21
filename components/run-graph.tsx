"use client";
import { useMemo, useState } from "react";
import {
  ReactFlow,
  Controls,
  Position,
  MarkerType,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GraphNode, RunGraph as Graph } from "@/lib/dashboard";

/** Left to right: the run, what it looked at, what it checked, what it found, and why. */
const COLUMN: Record<string, number> = {
  AgentToken: 0,
  Run: 0,
  Step: 1,
  Repository: 1,
  PullRequestFor: 1,
  Upgrade: 2,
  Release: 3,
  Finding: 3,
  CodeLine: 4,
  APIChange: 4,
  Advisory: 4,
  PullRequest: 5,
};
const CAPTION: Record<string, string> = {
  Run: "Run",
  Step: "Step",
  Repository: "Repository",
  Upgrade: "Upgrade",
  Release: "Release",
  Finding: "Finding",
  CodeLine: "Your code",
  APIChange: "What changed",
  Advisory: "Advisory",
  PullRequest: "Upstream PR",
  AgentToken: "Agent",
};
const X = 250;
const Y = 86;

function tone(node: GraphNode): string {
  const p = node.props;
  if (node.label === "Finding" && p.severity === "breaks") return "breaks";
  if (node.label === "Upgrade" && p.verdict === "breaks") return "breaks";
  if (node.label === "Step" && p.status === "failed") return "breaks";
  if (node.label === "Run" && p.status === "failed") return "breaks";
  if (node.label === "Advisory") return "warn";
  return "plain";
}

function column(node: GraphNode, forPull: Set<string>): number {
  if (node.label === "PullRequest" && forPull.has(node.id))
    return COLUMN.PullRequestFor;
  return COLUMN[node.label] ?? 3;
}

export function RunGraph({ graph }: { graph: Graph }) {
  const [picked, setPicked] = useState<GraphNode | null>(null);
  const { nodes, edges } = useMemo(() => {
    const forPull = new Set(
      graph.edges.filter((e) => e.type === "FOR_PULL").map((e) => e.target),
    );
    // Steps make a tall column; keep failed ones and the last few.
    const steps = graph.nodes
      .filter((n) => n.label === "Step")
      .sort((a, b) => Number(a.props.seq) - Number(b.props.seq));
    const hidden = new Set(
      steps
        .filter((s, i) => s.props.status !== "failed" && i < steps.length - 3)
        .map((s) => s.id),
    );
    const shown = graph.nodes.filter((n) => !hidden.has(n.id));
    const rows: number[] = [];
    const nodes: Node[] = shown.map((n) => {
      const col = column(n, forPull);
      rows[col] = (rows[col] || 0) + 1;
      return {
        id: n.id,
        position: { x: col * X, y: (rows[col] - 1) * Y },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          label: (
            <button
              type="button"
              className="ci-gnode nodrag nopan"
              data-tone={tone(n)}
              onClick={() => setPicked(n)}
              title={n.name}
            >
              <small>{CAPTION[n.label] || n.label}</small>
              <strong>{n.name}</strong>
            </button>
          ),
        },
        style: { padding: 0, border: 0, background: "transparent", width: 210 },
      };
    });
    const ids = new Set(shown.map((n) => n.id));
    const edges: Edge[] = graph.edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({
        id: `${e.source}-${e.type}-${e.target}`,
        source: e.source,
        target: e.target,
        label: e.type.toLowerCase().replaceAll("_", " "),
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
        style: { stroke: "var(--edge-strong)" },
        labelStyle: { fill: "var(--ash)", fontSize: 10 },
        labelBgStyle: { fill: "var(--carbon)" },
      }));
    return { nodes, edges };
  }, [graph]);
  return (
    <div className="ci-rgraph">
      <div className="ci-rgraph-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          minZoom={0.3}
        >
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <aside className="ci-rgraph-side" aria-live="polite">
        {picked ? (
          <>
            <p className="ci-crumb">{CAPTION[picked.label] || picked.label}</p>
            <h3>{picked.name}</h3>
            <dl>
              {Object.entries(picked.props)
                .filter(([k]) => k !== "name")
                .map(([k, v]) => (
                  <div key={k}>
                    <dt>{k.replaceAll("_", " ")}</dt>
                    <dd>
                      {typeof v === "string" && /^https?:\/\//.test(v) ? (
                        <a href={v}>{v.replace(/^https?:\/\//, "")}</a>
                      ) : (
                        <span className={k === "code" ? "ci-gcode" : undefined}>
                          {String(v)}
                        </span>
                      )}
                    </dd>
                  </div>
                ))}
            </dl>
          </>
        ) : (
          <p className="ci-note">
            Select a node to see what the graph holds for it. This is the same
            data the Neo4j workspace graph answers impact questions from.
          </p>
        )}
      </aside>
    </div>
  );
}
