"use client";
import dynamic from "next/dynamic";
import type { RunGraph as Graph } from "@/lib/dashboard";

const RunGraph = dynamic(() => import("./run-graph").then((m) => m.RunGraph), {
  ssr: false,
  loading: () => <p className="ci-note">Drawing the graph…</p>,
});

export function RunGraphLazy({ graph }: { graph: Graph }) {
  return <RunGraph graph={graph} />;
}
