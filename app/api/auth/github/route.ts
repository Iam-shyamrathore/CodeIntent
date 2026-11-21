import { NextResponse, type NextRequest } from "next/server";
import {
  authConfig,
  authorizeUrl,
  newAuthorization,
  redirectTo,
  STATE_COOKIE,
  STATE_LIFETIME,
} from "@/lib/auth";
import { secureCookies } from "@/lib/session";

export const runtime = "nodejs";

/** Starts "Sign in with GitHub": remembers a random state and PKCE verifier, then goes to GitHub. */
export async function GET(request: NextRequest) {
  const config = authConfig();
  if (!config) return redirectTo("/dashboard?auth=not-configured");
  const authorization = newAuthorization(
    request.nextUrl.searchParams.get("next") || "",
  );
  const response = NextResponse.redirect(
    authorizeUrl(config, authorization),
    303,
  );
  response.headers.set("Cache-Control", "no-store");
  // Lax, so the cookie comes back on GitHub's top-level redirect to the callback.
  response.cookies.set(STATE_COOKIE, authorization.cookie, {
    httpOnly: true,
    secure: secureCookies(),
    sameSite: "lax",
    path: "/api/auth",
    maxAge: STATE_LIFETIME,
  });
  return response;
}
