import { OperatorSignIn } from "./operator-access";
import { ArrowOut, GitHubMark } from "./site/icons";
import { installUrl, signInConfigured, signInHref } from "@/lib/auth";

const NOTICES: Record<string, string> = {
  state:
    "That sign-in link was not started here or has expired. Start again from this page.",
  denied: "GitHub sign-in was cancelled.",
  failed:
    "GitHub did not confirm the sign-in. Try again; if it keeps failing, the App’s client secret or callback URL may need updating.",
  "not-configured": "GitHub sign-in is not configured on this deployment yet.",
};

/** Message for `?auth=…` after an unsuccessful sign-in round trip. */
export function AuthNotice({ code }: { code?: string | string[] }) {
  const text = typeof code === "string" ? NOTICES[code] : undefined;
  if (!text) return null;
  return (
    <p role="alert" className="ci-alert">
      {text}
    </p>
  );
}

/** A plain link: the route sets the state cookie and redirects to GitHub. */
export function GitHubSignInButton({
  next,
  label = "Sign in with GitHub",
  quiet = false,
}: {
  next: string;
  label?: string;
  /** A secondary button instead of the primary one. */
  quiet?: boolean;
}) {
  if (!signInConfigured())
    return (
      <span className="ci-btn" aria-disabled="true">
        <GitHubMark />
        Sign-in not configured
      </span>
    );
  return (
    <a className={quiet ? "ci-btn-quiet" : "ci-btn"} href={signInHref(next)}>
      <GitHubMark />
      {label}
    </a>
  );
}

/** Signed-out state for dashboard pages and private reports. */
export function SignInPanel({
  next,
  title,
  body,
  operatorPurpose,
}: {
  next: string;
  title: string;
  body: string;
  operatorPurpose: string;
}) {
  const configured = signInConfigured();
  return (
    <section className="ci-signin" aria-labelledby="sign-in-heading">
      <h2 id="sign-in-heading">{title}</h2>
      <p>{body}</p>
      <GitHubSignInButton next={next} />
      {configured ? (
        <p className="ci-fine">
          GitHub asks you to authorize CodeIntent once. It reads who you are and
          which installations of the App you can access; nothing else is kept.
        </p>
      ) : (
        <p className="ci-fine" role="status">
          Sign-in is not configured. The operator sets{" "}
          <code>GITHUB_APP_CLIENT_ID</code> and{" "}
          <code>GITHUB_APP_CLIENT_SECRET</code> from the GitHub App’s settings,
          with <code>CODEINTENT_PUBLIC_URL</code>
          <code>/api/auth/callback</code> as its callback URL.
        </p>
      )}
      <details className="ci-operator">
        <summary>Operator access</summary>
        <OperatorSignIn purpose={operatorPurpose} />
      </details>
    </section>
  );
}

/** Signed in, but GitHub reports no installation of the App this user can access. */
export function NoInstallations({ next }: { next: string }) {
  return (
    <section className="ci-signin" aria-labelledby="empty-heading">
      <h2 id="empty-heading">Install the App to get started</h2>
      <p>
        No installation of CodeIntent is yours yet. Install it on an account you
        manage and pick the repositories to check. If it is already installed,
        ask an owner of that account for access to one of its repositories, then
        sign in again.
      </p>
      <div className="ci-tg-actions">
        <a className="ci-btn" href={installUrl()}>
          <GitHubMark />
          Install on GitHub
          <ArrowOut />
        </a>
        <GitHubSignInButton next={next} label="Sign in again" quiet />
      </div>
    </section>
  );
}
