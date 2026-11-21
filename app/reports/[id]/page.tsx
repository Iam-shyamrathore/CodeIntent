import { cache } from "react";
import { notFound } from "next/navigation";
import Workbench from "@/components/workbench";
import { service } from "@/lib/server-api";
import type { Study } from "@/lib/study";
export const dynamic = "force-dynamic";
const loadReport = cache(
  async (
    id: string,
  ): Promise<{ state: "ok" | "missing" | "unavailable"; study?: Study }> => {
    let response;
    try {
      response = await service(`/reports/${id}`);
    } catch {
      return { state: "unavailable" };
    }
    if (response.status === 404) return { state: "missing" };
    if (!response.ok) throw new Error("Could not load investigation");
    return { state: "ok", study: await response.json() };
  },
);
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!/^[a-f0-9-]{36}$/.test(id)) return {};
  const { study } = await loadReport(id);
  if (!study) return { title: "Saved investigation · Code Intent" };
  return {
    title: `${study.question} · Code Intent`,
    description: `${study.answer.title} — investigated against ${study.repository} @ ${study.revision.slice(0, 7)}. Every claim cites a captured passage.`,
  };
}
export default async function Report({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!/^[a-f0-9-]{36}$/.test(id)) notFound();
  const { state, study } = await loadReport(id);
  if (state === "unavailable")
    return (
      <main className="credits-page">
        <h1>The evidence service is unavailable</h1>
        <p>Your report remains saved. Try this link again shortly.</p>
        <a href="/repositories">Return to repositories</a>
      </main>
    );
  if (!study) notFound();
  return <Workbench initial={study} homeStudy={study} />;
}
