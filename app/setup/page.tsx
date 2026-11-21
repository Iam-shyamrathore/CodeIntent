import Link from "next/link";
import { GitHubSignInButton } from "@/components/auth-panel";
import { ConsoleHeader } from "@/components/console-header";
import { SiteFooter } from "@/components/site/footer";
import { ArrowOut, ArrowRight, GitHubMark } from "@/components/site/icons";
import { DEMO_PR, TELEGRAM_BOT } from "@/components/site/links";
import { TelegramConnect } from "@/components/telegram-connect";
import { installUrl } from "@/lib/auth";
import { read, type Installation } from "@/lib/dashboard";
import {
  canAccessInstallation,
  getSession,
  installationQuery,
  type Session,
} from "@/lib/session";
import type { TelegramLinks } from "@/lib/telegram";

export const metadata = {
  title: "Set up · CodeIntent",
  description:
    "Three steps: install the GitHub App, connect your Telegram group, and CodeIntent checks every Python dependency pull request.",
};

type Account = Installation & { telegram: TelegramLinks | null };
type State = "done" | "next" | "later";
const STATE_TEXT: Record<State, string> = {
  done: "Done",
  next: "Next",
  later: "After step 1",
};

/** What the session can see: its installations and their Telegram links. Null when unknown. */
async function loadAccounts(session: Session): Promise<Account[] | null> {
  if (session.kind === "github" && session.installations.length === 0)
    return [];
  const result = await read<{ installations: Installation[] }>(
    session.kind === "github"
      ? `/app/installations?${installationQuery(session)}`
      : "/app/installations",
  );
  if (result.state !== "ok") return null;
  return Promise.all(
    result.data.installations
      .filter((i) => canAccessInstallation(session, i.id))
      .map(async (i) => {
        const telegram = await read<TelegramLinks>(
          `/app/installations/${i.id}/telegram`,
        );
        return {
          ...i,
          telegram: telegram.state === "ok" ? telegram.data : null,
        };
      }),
  );
}

export default async function Setup() {
  const session = await getSession();
  const accounts = session ? await loadAccounts(session) : null;
  const installed =
    session?.kind === "operator"
      ? (accounts?.length ?? 0) > 0
      : (session?.installations.length ?? 0) > 0;
  const linked = (accounts || []).filter(
    (a) => (a.telegram?.chats.length ?? 0) > 0,
  );
  const analysed = (accounts || []).reduce((n, a) => n + a.analyses, 0);
  const install = installUrl();

  const step1: State = installed ? "done" : "next";
  const step2: State =
    linked.length > 0 ? "done" : installed ? "next" : "later";
  const step3: State = analysed > 0 ? "done" : "later";

  return (
    <div className="ci ci-page">
      <ConsoleHeader current="setup" session={session} next="/setup" />
      <main className="ci-main" id="main">
        <div className="ci-head">
          <div>
            <h1 className="ci-title">Set up in three steps</h1>
            <p className="ci-intro">
              {session
                ? "Your progress is saved on GitHub and in Telegram; this page reads it back."
                : "Once per GitHub account. Sign in at step 2 to see your progress here."}
            </p>
          </div>
        </div>
        <ol className="ci-setup">
          <li data-state={step1}>
            <div className="ci-setup-top">
              <span className="ci-num" aria-hidden="true">
                1
              </span>
              <span className="ci-state">{STATE_TEXT[step1]}</span>
            </div>
            <h2>Install on GitHub</h2>
            <p>
              Pick the account and the repositories CodeIntent may read. It sees
              only those, and you can change the selection on GitHub at any
              time.
            </p>
            <div className="ci-setup-body">
              {installed ? (
                <>
                  <p>
                    Installed on{" "}
                    {(accounts || []).map((a) => a.account_login).join(", ") ||
                      "your account"}
                    .
                  </p>
                  <a className="ci-btn-quiet" href={install}>
                    Add repositories <ArrowOut />
                  </a>
                </>
              ) : (
                <a className="ci-btn" href={install}>
                  <GitHubMark />
                  Install on GitHub
                </a>
              )}
            </div>
          </li>

          <li data-state={step2} id="telegram">
            <div className="ci-setup-top">
              <span className="ci-num" aria-hidden="true">
                2
              </span>
              <span className="ci-state">
                {step2 === "later" && !session ? "Sign in" : STATE_TEXT[step2]}
              </span>
            </div>
            <h2>Connect your Telegram group</h2>
            <p>
              <a className="ci-link" href={TELEGRAM_BOT}>
                @codeintent_alerts_bot
              </a>{" "}
              posts when a pull request breaks your code, needs a change, or
              moves to a version with known advisories.
            </p>
            <div className="ci-setup-body">
              {!session ? (
                <GitHubSignInButton next="/setup#telegram" quiet />
              ) : !installed ? (
                <p>Install the App first; the link is per GitHub account.</p>
              ) : accounts === null ? (
                <p role="status">
                  Telegram links could not be loaded. Try again shortly.
                </p>
              ) : (
                accounts.map((a) => {
                  const chats = a.telegram?.chats || [];
                  if (a.telegram === null)
                    return (
                      <p key={a.id} role="status">
                        Links for {a.account_login} could not be loaded.
                      </p>
                    );
                  if (!a.telegram.configured)
                    return (
                      <p key={a.id}>
                        Telegram is not configured on this deployment.
                      </p>
                    );
                  if (chats.length)
                    return (
                      <p key={a.id} className="ci-tg-status" data-on="">
                        <span>
                          {chats
                            .map((c) => c.title || "Telegram chat")
                            .join(", ")}{" "}
                          <small>· {a.account_login}</small>
                        </span>
                      </p>
                    );
                  return (
                    <TelegramConnect
                      key={a.id}
                      installation={a.id}
                      account={a.account_login}
                    />
                  );
                })
              )}
            </div>
          </li>

          <li data-state={step3}>
            <div className="ci-setup-top">
              <span className="ci-num" aria-hidden="true">
                3
              </span>
              <span className="ci-state">
                {step3 === "done" ? "Working" : "Automatic"}
              </span>
            </div>
            <h2>Open or wait for a dependency PR</h2>
            <p>
              CodeIntent adds one check and one comment to every pull request
              that changes a Python dependency, Dependabot and Renovate
              included. Nothing to configure.
            </p>
            <div className="ci-setup-body">
              {analysed > 0 && (
                <p>
                  {analysed} dependency pull request{analysed === 1 ? "" : "s"}{" "}
                  checked so far.
                </p>
              )}
              <a className="ci-link" href={DEMO_PR}>
                See it on a real pull request <ArrowOut />
              </a>
              {session && (
                <Link className="ci-link" href="/dashboard">
                  Open the dashboard <ArrowRight />
                </Link>
              )}
            </div>
          </li>
        </ol>

        <div className="ci-setup-extra">
          <section aria-labelledby="files">
            <h2 id="files">What counts as a dependency pull request</h2>
            <p>
              Any change to <code>requirements*.txt</code>,{" "}
              <code>pyproject.toml</code>, <code>uv.lock</code>,{" "}
              <code>poetry.lock</code>, <code>setup.cfg</code> or{" "}
              <code>setup.py</code>.
            </p>
          </section>
          <section aria-labelledby="commands">
            <h2 id="commands">In the Telegram group</h2>
            <ul>
              <li>
                <code>/status</code> lists your repositories and their latest
                verdict.
              </li>
              <li>
                <code>/why httpx</code> shows the lines an upgrade affects and
                what to use instead.
              </li>
              <li>
                <code>/unlink</code> stops alerts in that chat.
              </li>
            </ul>
          </section>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
