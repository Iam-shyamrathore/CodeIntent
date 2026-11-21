"use client";
import dynamic from "next/dynamic";
import type { DependencyTree } from "@/lib/dashboard";

const DependencyGraph = dynamic(
  () => import("./dependency-graph").then((m) => m.DependencyGraph),
  {
    ssr: false,
    loading: () => <p className="ci-note">Drawing the dependency graph…</p>,
  },
);

export function DependencyGraphLazy(props: {
  tree: DependencyTree;
  base: string;
  exposed: string[];
}) {
  return <DependencyGraph {...props} />;
}
