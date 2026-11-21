import Link from "next/link";
import { BookOpen } from "lucide-react";
import {
  AlertKindsTile,
  DashboardGate,
  PageHead,
  TelegramTile,
} from "@/components/dashboard/tiles";
import { loadContext } from "@/lib/workspaces";

export const metadata = { title: "Alerts · CodeIntent" };

export default async function Alerts() {
  const context = await loadContext();
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/alerts" />;
  return (
    <>
      <PageHead
        title="Alerts"
        intro="Findings in your team’s Telegram group."
        action={
          <Link className="ci-btn-quiet" href="/docs/telegram">
            <BookOpen size={15} strokeWidth={1.5} aria-hidden="true" />
            Docs
          </Link>
        }
      />
      <div className="ci-bento">
        <TelegramTile workspaces={context.workspaces} />
        <AlertKindsTile />
      </div>
    </>
  );
}
