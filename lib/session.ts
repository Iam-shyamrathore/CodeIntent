import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

/** Operator ("workspace key") sessions: the original admin fallback, cookie `ci_operator`. */
const lifetime = 60 * 60 * 24;
/** GitHub sign-in sessions last as long as a GitHub App user access token: 8 hours. */
export const GITHUB_SESSION_LIFETIME = 60 * 60 * 8;
export const GITHUB_SESSION_COOKIE = "ci_session";
export const OPERATOR_COOKIE = "ci_operator";
/** At most this many installation ids are kept in the cookie, keeping it well under 4 KB. */
export const MAX_SESSION_INSTALLATIONS = 100;

function secret() {
  const value = process.env.CODEINTENT_SESSION_SECRET;
  if (!value || value.length < 32)
    throw new Error("Configure a session secret of at least 32 characters");
  return value;
}
function signature(payload: string) {
  return createHmac("sha256", secret()).update(payload).digest("hex");
}
/** Signatures for each signed value get their own label, so one kind can never pass as another. */
export function signLabelled(label: string, payload: string) {
  return createHmac("sha256", secret())
    .update(`${label}\n${payload}`)
    .digest("hex");
}
function sameSignature(supplied: string, expected: string) {
  return (
    /^[a-f0-9]{64}$/.test(supplied) &&
    timingSafeEqual(Buffer.from(supplied), Buffer.from(expected))
  );
}

export function makeSession() {
  const payload = String(Math.floor(Date.now() / 1000) + lifetime);
  return `${payload}.${signature(payload)}`;
}
export function validateSession(value: string) {
  try {
    const [payload, supplied] = value.split(".");
    if (
      !payload ||
      !supplied ||
      !/^\d+$/.test(payload) ||
      !/^[a-f0-9]{64}$/.test(supplied)
    )
      return false;
    const expiry = Number(payload),
      now = Math.floor(Date.now() / 1000);
    if (expiry <= now || expiry > now + lifetime) return false;
    return timingSafeEqual(
      Buffer.from(supplied),
      Buffer.from(signature(payload)),
    );
  } catch {
    return false;
  }
}
export async function isOperator() {
  return validateSession((await cookies()).get(OPERATOR_COOKIE)?.value || "");
}

export type GitHubSession = {
  kind: "github";
  login: string;
  /** GitHub user id; logins can be renamed, ids cannot. */
  user: number;
  avatar: string | null;
  /** Installations of the App this user could access at sign-in (GET /user/installations). */
  installations: number[];
  issued_at: number;
  expires_at: number;
};
export type Session = { kind: "operator" } | GitHubSession;

const GITHUB_LABEL = "ci-github-session.v1";
const LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;
const AVATAR =
  /^https:\/\/avatars\.githubusercontent\.com\/[A-Za-z0-9/._?=&%-]{1,300}$/;

function validId(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

/** A signed, expiring GitHub session value. It carries no GitHub token. */
export function makeGitHubSession(input: {
  login: string;
  user: number;
  avatar: string | null;
  installations: number[];
}) {
  const now = Math.floor(Date.now() / 1000);
  const body: GitHubSession = {
    kind: "github",
    login: input.login,
    user: input.user,
    avatar: input.avatar && AVATAR.test(input.avatar) ? input.avatar : null,
    installations: [...new Set(input.installations.filter(validId))]
      .sort((a, b) => a - b)
      .slice(0, MAX_SESSION_INSTALLATIONS),
    issued_at: now,
    expires_at: now + GITHUB_SESSION_LIFETIME,
  };
  const payload = Buffer.from(JSON.stringify(body)).toString("base64url");
  return `${payload}.${signLabelled(GITHUB_LABEL, payload)}`;
}

export function readGitHubSession(value: string): GitHubSession | null {
  try {
    const [payload, supplied, extra] = value.split(".");
    if (
      !payload ||
      !supplied ||
      extra !== undefined ||
      payload.length > 3000 ||
      !/^[A-Za-z0-9_-]+$/.test(payload) ||
      !sameSignature(supplied, signLabelled(GITHUB_LABEL, payload))
    )
      return null;
    const body = JSON.parse(Buffer.from(payload, "base64url").toString());
    const now = Math.floor(Date.now() / 1000);
    if (
      body?.kind !== "github" ||
      typeof body.login !== "string" ||
      !LOGIN.test(body.login) ||
      !validId(body.user) ||
      !Array.isArray(body.installations) ||
      !body.installations.every(validId) ||
      body.installations.length > MAX_SESSION_INSTALLATIONS ||
      typeof body.issued_at !== "number" ||
      typeof body.expires_at !== "number" ||
      body.expires_at <= now ||
      body.expires_at > body.issued_at + GITHUB_SESSION_LIFETIME ||
      body.issued_at > now + 60
    )
      return null;
    return {
      kind: "github",
      login: body.login,
      user: body.user,
      avatar:
        typeof body.avatar === "string" && AVATAR.test(body.avatar)
          ? body.avatar
          : null,
      installations: body.installations,
      issued_at: body.issued_at,
      expires_at: body.expires_at,
    };
  } catch {
    return null;
  }
}

/** The current session. A valid operator session wins, since it sees every installation. */
export async function getSession(): Promise<Session | null> {
  const store = await cookies();
  if (validateSession(store.get(OPERATOR_COOKIE)?.value || ""))
    return { kind: "operator" };
  return readGitHubSession(store.get(GITHUB_SESSION_COOKIE)?.value || "");
}

/** Whether a session may read or act on one installation. Operators may act on all. */
export function canAccessInstallation(
  session: Session | null,
  installation: number,
) {
  if (!session) return false;
  return (
    session.kind === "operator" || session.installations.includes(installation)
  );
}

/** `installations=…` query for backend reads scoped to a GitHub session; empty for operators. */
export function installationQuery(session: GitHubSession) {
  const query = new URLSearchParams();
  for (const id of session.installations)
    query.append("installations", String(id));
  return query.toString();
}

/** Secure cookies whenever the public origin is HTTPS (always the case in production). */
export function secureCookies() {
  return (
    process.env.NODE_ENV === "production" &&
    (process.env.CODEINTENT_PUBLIC_URL || "").startsWith("https://")
  );
}

export function allowedOrigin(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    const allowed = new Set([
      new URL(request.url).host,
      request.headers.get("host"),
    ]);
    if (process.env.CODEINTENT_PUBLIC_URL)
      allowed.add(new URL(process.env.CODEINTENT_PUBLIC_URL).host);
    return allowed.has(new URL(origin).host);
  } catch {
    return false;
  }
}
