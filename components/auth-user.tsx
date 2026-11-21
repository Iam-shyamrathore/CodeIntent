import type { Session } from "@/lib/session";
import { signInConfigured, signInHref } from "@/lib/auth";

function avatarUrl(avatar: string) {
  try {
    const url = new URL(avatar);
    url.searchParams.set("s", "56");
    return url.toString();
  } catch {
    return null;
  }
}

/** Header identity: avatar and login (or "Operator") with a POST sign-out form. */
export function AuthUser({
  session,
  next = "/dashboard",
}: {
  session: Session | null;
  next?: string;
}) {
  if (!session)
    return signInConfigured() ? (
      <a className="ci-nav-signin" href={signInHref(next)}>
        Sign in
      </a>
    ) : null;
  const avatar =
    session.kind === "github" && session.avatar
      ? avatarUrl(session.avatar)
      : null;
  const name = session.kind === "github" ? session.login : "Operator";
  return (
    <div className="ci-nav-user">
      <span className="ci-nav-identity" title={`Signed in as ${name}`}>
        {avatar ? (
          // A small fixed-size avatar from GitHub's CDN; next/image adds nothing here.
          <img src={avatar} alt="" width={24} height={24} />
        ) : (
          <span className="ci-nav-initial" aria-hidden="true">
            {name.slice(0, 1).toUpperCase()}
          </span>
        )}
        <span className="ci-nav-login">{name}</span>
      </span>
      <form method="post" action="/api/auth/logout">
        <button className="ci-nav-signout" type="submit">
          Sign out
        </button>
      </form>
    </div>
  );
}
