import { notFound } from "next/navigation";
import Workbench from "@/components/workbench";
import { service } from "@/lib/server-api";
export const dynamic = "force-dynamic";
export const metadata = { title: "Saved investigation · Code Intent" };
export default async function Report({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!/^[a-f0-9-]{36}$/.test(id)) notFound();
  let response;
  try {
    response = await service(`/reports/${id}`);
  } catch {
    return (
      <main className="credits-page">
        <h1>The evidence service is unavailable</h1>
        <p>Your report remains saved. Try this link again shortly.</p>
        <a href="/repositories">Return to repositories</a>
      </main>
    );
  }
  if (response.status === 404) notFound();
  if (!response.ok) throw new Error("Could not load investigation");
  const study = await response.json();
  return <Workbench initial={study} homeStudy={study} />;
}
