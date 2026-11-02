import Workbench from "@/components/workbench";
import {
  readStudy,
  emptyStudy,
  type Study,
  type Decision,
  type Source,
} from "@/lib/study";
import { service } from "@/lib/server-api";
import Link from "next/link";
export const dynamic = "force-dynamic";
export default async function Investigate({
  searchParams,
}: {
  searchParams: Promise<{ case?: string; repository?: string }>;
}) {
  const params = await searchParams;
  const repository = params.repository || "encode/httpx";
  let initial: Study | undefined, home: Study | undefined;
  if (repository === "encode/httpx") {
    initial = readStudy(params.case === "unknown" ? "unknown" : "rawurl");
    home = readStudy();
  }
  try {
    const response = await service("/repositories");
    if (response.ok) {
      const data = await response.json();
      const repo = data.repositories.find(
        (r: { name: string }) => r.name === repository,
      );
      if (repo?.ready_index) {
        // Saved reports retain their original snapshot. New questions use their displayed index.
        if (initial && initial.index_id === repo.ready_index) {
          const details = await service(`/indexes/${repo.ready_index}`).then(
            (r) => r.json(),
          );
          const attach = (study: Study) => {
            const ids = new Set(study.sources.map((s) => s.id));
            study.decisions = details.decisions.filter((d: Decision) =>
              ids.has(d.source_id),
            );
            const needed = new Set(
              study.decisions?.flatMap((d) =>
                d.citations.map((c) => c.source_id),
              ),
            );
            study.sources.push(
              ...details.decision_sources.filter(
                (s: Source) => needed.has(s.id) && !ids.has(s.id),
              ),
            );
          };
          attach(initial);
          if (home) attach(home);
        } else
          initial = emptyStudy(
            repo.name,
            repo.revision,
            repo.ready_index,
            repo.coverage,
          );
      }
    }
  } catch {
    /* Public saved examples are readable during a provider/service outage. */
  }
  if (!initial)
    return (
      <main className="credits-page">
        <h1>This repository has no ready index yet.</h1>
        <p>Check its import progress or choose another repository.</p>
        <Link className="text-link" href="/repositories">
          Open repositories →
        </Link>
      </main>
    );
  return (
    <Workbench key={repository} initial={initial} homeStudy={home || initial} />
  );
}
