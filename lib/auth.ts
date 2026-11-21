import "server-only";
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { NextResponse } from "next/server";
import { signLabelled } from "./session";

/**
 * "Sign in with GitHub" through the Code Intent GitHub App's user authorization
 * (web application flow with state and PKCE). The user access token is used once,
 * server-side, to read who the user is and which installations they can access;
 * it is then revoked and never stored or sent to the browser.
 */

export const STATE_COOKIE = "ci_oauth";
/** The authorize round trip must finish within ten minutes. */
export const STATE_LIFETIME = 600;
export const DEFAULT_NEXT = "/dashboard";
const STATE_LABEL = "ci-oauth-state.v1";
const GITHUB_API = "https://api.github.com";

export function appSlug() {
  const slug = process.env.NEXT_PUBLIC_GITHUB_APP_SLUG?.trim() || "";
  return /^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$/i.test(slug)
    ? slug
    : "codeintent-dependency-check";
}
export function installUrl() {
  return `https://github.com/apps/${appSlug()}/installations/new`;
}

export type AuthConfig = {
  clientId: string;
  clientSecret: string;
  redirectUri: string;
};

/** The sign-in settings, or null when this deployment cannot offer GitHub sign-in. */
export function authConfig(): AuthConfig | null {
  const clientId = process.env.GITHUB_APP_CLIENT_ID?.trim() || "";
  const clientSecret = process.env.GITHUB_APP_CLIENT_SECRET?.trim() || "";
  const sessionSecret = process.env.CODEINTENT_SESSION_SECRET || "";
  const publicUrl = process.env.CODEINTENT_PUBLIC_URL?.trim() || "";
  if (
    !/^[A-Za-z0-9._-]{1,100}$/.test(clientId) ||
    !clientSecret ||
    sessionSecret.length < 32 ||
    !/^https?:\/\//.test(publicUrl)
  )
    return null;
  let origin: string;
  try {
    origin = new URL(publicUrl).origin;
  } catch {
    return null;
  }
  return {
    clientId,
    clientSecret,
    redirectUri: `${origin}/api/auth/callback`,
  };
}
export function signInConfigured() {
  return authConfig() !== null;
}

/**
 * A same-site path to return to after sign-in. Anything that is not a plain
 * absolute path on this site (protocol-relative, backslashes, schemes, control
 * characters, the auth routes themselves) falls back to the dashboard.
 */
export function safeNext(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 512 ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(value)
  )
    return DEFAULT_NEXT;
  try {
    const base = "https://codeintent.invalid";
    const url = new URL(value, base);
    if (url.origin !== base || url.pathname.startsWith("/api/"))
      return DEFAULT_NEXT;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return DEFAULT_NEXT;
  }
}

/** Hrefs for the sign-in button; `next` is checked again on the server. */
export function signInHref(next: string = DEFAULT_NEXT) {
  return `/api/auth/github?next=${encodeURIComponent(safeNext(next))}`;
}

type StateValue = {
  state: string;
  verifier: string;
  next: string;
  exp: number;
};

function random() {
  return randomBytes(32).toString("base64url");
}

/** A new state and PKCE verifier, and the signed cookie value that remembers them. */
export function newAuthorization(next: string) {
  const value: StateValue = {
    state: random(),
    verifier: random(),
    next: safeNext(next),
    exp: Math.floor(Date.now() / 1000) + STATE_LIFETIME,
  };
  const payload = Buffer.from(JSON.stringify(value)).toString("base64url");
  return {
    ...value,
    challenge: createHash("sha256").update(value.verifier).digest("base64url"),
    cookie: `${payload}.${signLabelled(STATE_LABEL, payload)}`,
  };
}

function equal(a: string, b: string) {
  // Hash first so lengths always match; the comparison itself is constant-time.
  return timingSafeEqual(
    createHash("sha256").update(a).digest(),
    createHash("sha256").update(b).digest(),
  );
}

/** The stored authorization if the cookie is authentic, unexpired and matches `state`. */
export function checkAuthorization(
  cookie: string | undefined,
  state: string | null,
): StateValue | null {
  try {
    if (!cookie || !state || state.length > 200) return null;
    const [payload, supplied, extra] = cookie.split(".");
    if (
      !payload ||
      !supplied ||
      extra !== undefined ||
      payload.length > 2000 ||
      !/^[a-f0-9]{64}$/.test(supplied) ||
      !equal(supplied, signLabelled(STATE_LABEL, payload))
    )
      return null;
    const value = JSON.parse(Buffer.from(payload, "base64url").toString());
    if (
      typeof value?.state !== "string" ||
      typeof value.verifier !== "string" ||
      typeof value.exp !== "number" ||
      value.exp <= Math.floor(Date.now() / 1000) ||
      !equal(value.state, state)
    )
      return null;
    return {
      state: value.state,
      verifier: value.verifier,
      next: safeNext(value.next),
      exp: value.exp,
    };
  } catch {
    return null;
  }
}

export function authorizeUrl(
  config: AuthConfig,
  authorization: { state: string; challenge: string },
) {
  const url = new URL("https://github.com/login/oauth/authorize");
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", config.redirectUri);
  url.searchParams.set("state", authorization.state);
  url.searchParams.set("code_challenge", authorization.challenge);
  url.searchParams.set("code_challenge_method", "S256");
  url.searchParams.set("allow_signup", "false");
  return url;
}

export class SignInError extends Error {}

/**
 * A 303 to a path on this site. The Location stays relative, so it always
 * resolves against the host the browser is on, never an internal host name.
 */
export function redirectTo(path: string) {
  return new NextResponse(null, {
    status: 303,
    headers: { Location: path, "Cache-Control": "no-store" },
  });
}

/** Exchanges the authorization code for a user access token. The token stays on the server. */
export async function exchangeCode(
  config: AuthConfig,
  code: string,
  verifier: string,
): Promise<string> {
  const response = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    cache: "no-store",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: config.clientId,
      client_secret: config.clientSecret,
      code,
      redirect_uri: config.redirectUri,
      code_verifier: verifier,
    }),
    signal: AbortSignal.timeout(10000),
  });
  const data = response.ok ? await response.json().catch(() => null) : null;
  // GitHub reports a bad or expired code as HTTP 200 with an `error` field.
  if (!data || typeof data.access_token !== "string" || data.error)
    throw new SignInError("token");
  return data.access_token;
}

async function github<T>(token: string, path: string): Promise<T> {
  const response = await fetch(`${GITHUB_API}${path}`, {
    cache: "no-store",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "code-intent",
    },
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) throw new SignInError(`github ${response.status}`);
  return (await response.json()) as T;
}

export type GitHubIdentity = {
  login: string;
  user: number;
  avatar: string | null;
  installations: number[];
};

/** Who the user is and which installations of this App they can access. */
export async function readIdentity(token: string): Promise<GitHubIdentity> {
  const user = await github<{
    id?: unknown;
    login?: unknown;
    avatar_url?: unknown;
  }>(token, "/user");
  if (
    typeof user.login !== "string" ||
    typeof user.id !== "number" ||
    !Number.isSafeInteger(user.id)
  )
    throw new SignInError("user");
  const installations: number[] = [];
  // Five pages of 100 covers any realistic account; ids beyond the session cap are dropped later.
  for (let page = 1; page <= 5; page++) {
    const data = await github<{
      total_count?: number;
      installations?: { id?: unknown }[];
    }>(token, `/user/installations?per_page=100&page=${page}`);
    const batch = Array.isArray(data.installations) ? data.installations : [];
    for (const item of batch)
      if (typeof item.id === "number" && Number.isSafeInteger(item.id))
        installations.push(item.id);
    if (batch.length < 100) break;
  }
  return {
    login: user.login,
    user: user.id,
    avatar: typeof user.avatar_url === "string" ? user.avatar_url : null,
    installations,
  };
}

/** Revokes the one-off user access token (DELETE /applications/{client_id}/token). Best effort. */
export async function revokeToken(config: AuthConfig, token: string) {
  try {
    await fetch(`${GITHUB_API}/applications/${config.clientId}/token`, {
      method: "DELETE",
      cache: "no-store",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Basic ${Buffer.from(`${config.clientId}:${config.clientSecret}`).toString("base64")}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "code-intent",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ access_token: token }),
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    // Not fatal: the token was never stored or sent anywhere, and GitHub expires it on its own.
  }
}
