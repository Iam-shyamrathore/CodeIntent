import { LockKeyhole, LogOut } from "lucide-react";
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
      <a className="auth-header-link" href={signInHref(next)}>
        Sign in
      </a>
    ) : null;
  const avatar =
    session.kind === "github" && session.avatar
      ? avatarUrl(session.avatar)
      : null;
  return (
    <div className="auth-user">
      {session.kind === "github" ? (
        <span className="auth-identity" title={`Signed in as ${session.login}`}>
          {avatar ? (
            // A small fixed-size avatar from GitHub's CDN; next/image adds nothing here.
            <img src={avatar} alt="" width={28} height={28} />
          ) : (
            <span className="auth-avatar-fallback" aria-hidden="true">
              {session.login.slice(0, 1).toUpperCase()}
            </span>
          )}
          <span className="auth-login">{session.login}</span>
        </span>
      ) : (
        <span className="auth-identity auth-operator-badge">
          <LockKeyhole size={14} aria-hidden="true" />
          <span className="auth-login">Operator</span>
        </span>
      )}
      <form method="post" action="/api/auth/logout">
        <button className="quiet-button" type="submit">
          <LogOut size={14} aria-hidden="true" />
          Sign out
        </button>
      </form>
    </div>
  );
}
