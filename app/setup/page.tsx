import Link from "next/link";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { ConsoleHeader } from "@/components/console-header";

export const metadata = {
  title: "Set up · Code Intent",
  description:
    "Install the Code Intent GitHub App to get a dependency upgrade verdict on every pull request that changes Python dependencies.",
};

const steps = [
  {
    title: "Install the GitHub App",
    body: "Choose which repositories Code Intent may read. It sees only the repositories you select, and you can change the selection on GitHub at any time.",
  },
  {
    title: "Open or wait for a dependency pull request",
    body: "Any pull request that changes requirements, pyproject.toml, uv.lock, poetry.lock, setup.cfg or setup.py. Dependabot and Renovate pull requests count.",
  },
  {
    title: "Read the check and the comment",
    body: "Each changed package gets a verdict, the exact lines in your code it affects, and the library’s own words about the change. The comment links to the full report.",
  },
];

export default function Setup() {
  const slug = process.env.NEXT_PUBLIC_GITHUB_APP_SLUG?.trim() || "";
  const valid = /^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$/i.test(slug);
  return (
    <div className="repository-page">
      <ConsoleHeader current="setup" />
      <main className="collection-main" id="main">
        <div className="collection-intro">
          <div>
            <p className="collection-breadcrumb">Workspace / Setup</p>
            <h1>A verdict on every dependency upgrade.</h1>
            <p>
              Code Intent compares the two releases against the code you
              actually call, and says what breaks, what needs a change, and what
              it could not check.
            </p>
          </div>
        </div>

        <section aria-labelledby="steps-heading" className="console-section">
          <div className="section-line">
            <h2 id="steps-heading">Three steps</h2>
            <span>Once per account</span>
          </div>
          <ol className="setup-steps">
            {steps.map((step, i) => (
              <li key={step.title} className="verify-step">
                <span className="step-no">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section
          aria-labelledby="install-heading"
          className="console-section install-panel"
        >
          <h2 id="install-heading">Install on GitHub</h2>
          {valid ? (
            <>
              <p>
                GitHub asks you to pick an account and the repositories to
                include. Verdicts start with the next dependency pull request.
              </p>
              <a
                className="primary-button"
                href={`https://github.com/apps/${slug}/installations/new`}
              >
                Install on GitHub <ArrowUpRight size={17} aria-hidden="true" />
              </a>
            </>
          ) : (
            <div className="console-notice" role="status">
              <strong>App not registered yet</strong>
              <p>
                This deployment has no GitHub App configured, so there is
                nothing to install. The operator sets{" "}
                <code>NEXT_PUBLIC_GITHUB_APP_SLUG</code> after registering the
                App, then rebuilds the site.
              </p>
            </div>
          )}
          <Link className="text-link" href="/dashboard">
            Open the dashboard <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </section>

        <section
          aria-labelledby="telegram-heading"
          className="console-section upcoming-panel"
        >
          <div className="section-line">
            <h2 id="telegram-heading">Telegram notifications</h2>
            <span>Optional</span>
          </div>
          <p>
            Link a Telegram chat, private or group, to hear about a “Breaks you”
            or “Needs a change” verdict, or an upgrade to a version with known
            advisories, without watching GitHub. Each pull request alerts each
            linked chat once.
          </p>
          <ol className="telegram-steps">
            <li>
              Open the <Link href="/dashboard">dashboard</Link>, signed in as
              the workspace operator, and choose{" "}
              <strong>Connect Telegram</strong> under the account. You get a
              one-time code valid for 15 minutes.
            </li>
            <li>
              Open the bot from the link shown next to the code and press{" "}
              <strong>Start</strong>, or add the bot to a group and send{" "}
              <code>/link CODE</code> there.
            </li>
            <li>
              In the chat, <code>/status</code> lists the repositories with
              their latest verdict and the newest breaking pull requests;{" "}
              <code>/why httpx</code> shows the lines a package upgrade affects,
              what to use instead and the upstream pull request behind it.{" "}
              <code>/unlink</code> stops alerts.
            </li>
          </ol>
        </section>

        <p className="collection-footnote">
          “No known impact” means every use that could be followed was compared
          in both releases and nothing relevant changed. It is never a promise
          that an upgrade is free of risk.
        </p>
      </main>
    </div>
  );
}
