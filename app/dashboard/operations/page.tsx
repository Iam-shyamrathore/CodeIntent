import { notFound } from "next/navigation";
import { DashboardGate, OpsTile, PageHead } from "@/components/dashboard/tiles";
import { read, type Ops } from "@/lib/dashboard";
import { loadContext } from "@/lib/workspaces";

export const metadata = { title: "Operations · CodeIntent" };

export default async function Operations() {
  const context = await loadContext();
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/operations" />;
  if (context.session.kind !== "operator") notFound();
  const ops = await read<Ops>("/app/ops", {
    headers: { "X-Operator-Key": process.env.CODEINTENT_OPERATOR_TOKEN || "" },
  });
  return (
    <>
      <PageHead
        title="Operations"
        intro="Worker health, the job queue and usage across the deployment."
      />
      <div className="ci-bento">
        <OpsTile ops={ops.state === "ok" ? ops.data : null} />
      </div>
    </>
  );
}
