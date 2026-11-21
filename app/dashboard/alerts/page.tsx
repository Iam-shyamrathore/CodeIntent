import Link from "next/link";
import {
  DashboardGate,
  PageHead,
  TelegramTile,
} from "@/components/dashboard/tiles";
import { loadContext } from "@/lib/workspaces";

export const metadata = { title: "Alerts · CodeIntent" };

const SENT = [
  "A pull request breaks your code or needs a change",
  "A new release would break code you use",
  "A pin can be lifted because the release it blocks changes nothing you use",
  "A version you run has a known advisory",
];
const COMMANDS: [string, string][] = [
  ["/status", "Repositories and the newest breaking pull requests"],
  ["/why package", "The latest verdict for a package"],
  ["/unlink", "Stop alerts in this chat"],
];

export default async function Alerts() {
  const context = await loadContext();
  if (context.state !== "ok")
    return <DashboardGate gate={context} next="/dashboard/alerts" />;
  return (
    <>
      <PageHead
        title="Alerts"
        intro="Push findings to the Telegram group your team already reads. Each finding is sent once."
      />
      <div className="ci-bento">
        <TelegramTile workspaces={context.workspaces} />
        <section className="ci-tile ci-tile-explain" aria-labelledby="sent">
          <h2 id="sent">What the group gets</h2>
          <ul className="ci-plain-list">
            {SENT.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <h2>Commands in the chat</h2>
          <dl className="ci-commands">
            {COMMANDS.map(([c, d]) => (
              <div key={c}>
                <dt>
                  <code>{c}</code>
                </dt>
                <dd>{d}</dd>
              </div>
            ))}
          </dl>
          <p className="ci-tile-note">
            <Link className="ci-link" href="/docs/telegram">
              Telegram docs
            </Link>
          </p>
        </section>
      </div>
    </>
  );
}
