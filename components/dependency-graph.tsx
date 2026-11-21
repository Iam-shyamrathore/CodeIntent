"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import {
  ReactFlow,
  Controls,
  Position,
  MarkerType,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { DependencyTree } from "@/lib/dashboard";

const X = 230;
const Y = 54;

/** Depth from the repository: its direct dependencies are column 0, what they pull in follows. */
function depths(tree: DependencyTree): Map<string, number> {
  const depth = new Map<string, number>();
  const queue: string[] = [];
  for (const n of tree.nodes)
    if (n.direct) {
      depth.set(n.id, 0);
      queue.push(n.id);
    }
  const next = new Map<string, string[]>();
  for (const e of tree.edges)
    next.set(e.source, [...(next.get(e.source) || []), e.target]);
  while (queue.length) {
    const id = queue.shift()!;
    for (const child of next.get(id) || [])
      if (!depth.has(child)) {
        depth.set(child, depth.get(id)! + 1);
        queue.push(child);
      }
  }
  for (const n of tree.nodes) if (!depth.has(n.id)) depth.set(n.id, 1);
  return depth;
}

export function DependencyGraph({
  tree,
  base,
  exposed,
}: {
  tree: DependencyTree;
  /** The repository page's path, so "why" links can ask the server. */
  base: string;
  /** Packages with a known advisory on the locked version. */
  exposed: string[];
}) {
  const [picked, setPicked] = useState<string | null>(null);
  const risky = useMemo(() => new Set(exposed), [exposed]);
  const { nodes, edges } = useMemo(() => {
    const depth = depths(tree);
    const rows: number[] = [];
    const nodes: Node[] = [...tree.nodes]
      .sort(
        (a, b) =>
          depth.get(a.id)! - depth.get(b.id)! ||
          a.package.localeCompare(b.package),
      )
      .map((n) => {
        const col = Math.min(depth.get(n.id)!, 5);
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
                className="ci-gnode ci-dnode nodrag nopan"
                data-tone={
                  risky.has(n.package)
                    ? "breaks"
                    : n.direct
                      ? "direct"
                      : "plain"
                }
                onClick={() => setPicked(n.package)}
                title={n.id}
              >
                <strong>{n.package}</strong>
                <small>{n.version}</small>
              </button>
            ),
          },
          style: {
            padding: 0,
            border: 0,
            background: "transparent",
            width: 190,
          },
        };
      });
    const edges: Edge[] = tree.edges.map((e) => ({
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
      style: { stroke: "var(--edge-strong)" },
    }));
    return { nodes, edges };
  }, [tree, risky]);
  const direct = tree.nodes.filter((n) => n.direct).length;
  return (
    <div className="ci-rgraph">
      <div className="ci-rgraph-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          fitViewOptions={{ padding: 0.1 }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          minZoom={0.2}
        >
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <aside className="ci-rgraph-side" aria-live="polite">
        <p className="ci-crumb">Dependency graph</p>
        <h3>
          {tree.nodes.length} packages, {direct} declared
        </h3>
        <p className="ci-note">
          Left column: what this repository declares. Each step right is what
          those releases pull in, resolved from the public ecosystem graph. Red:
          a known advisory on the locked version.
        </p>
        {picked && (
          <p>
            <strong>{picked}</strong>
            <br />
            <Link
              href={`${base}?why=${encodeURIComponent(picked)}#dependencies`}
            >
              Why is it installed?
            </Link>
            {" · "}
            <Link
              href={`/dashboard/ecosystem?package=${encodeURIComponent(picked)}`}
            >
              Who else depends on it
            </Link>
          </p>
        )}
      </aside>
    </div>
  );
}
