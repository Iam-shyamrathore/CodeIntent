import { after, type NextRequest } from "next/server";
import {
  authConfig,
  checkAuthorization,
  exchangeCode,
  readIdentity,
  redirectTo,
  revokeToken,
  STATE_COOKIE,
} from "@/lib/auth";
import {
  GITHUB_SESSION_COOKIE,
  GITHUB_SESSION_LIFETIME,
  makeGitHubSession,
  secureCookies,
} from "@/lib/session";

export const runtime = "nodejs";

function finish(path: string) {
  const response = redirectTo(path);
  // The state is single-use, whatever the outcome.
  response.cookies.set(STATE_COOKIE, "", { path: "/api/auth", maxAge: 0 });
  return response;
}

/** GitHub redirects here after authorization: check state, exchange the code, create the session. */
export async function GET(request: NextRequest) {
  const config = authConfig();
  if (!config) return finish("/dashboard?auth=not-configured");
  const params = request.nextUrl.searchParams;
  const authorization = checkAuthorization(
    request.cookies.get(STATE_COOKIE)?.value,
    params.get("state"),
  );
  if (!authorization) return finish("/dashboard?auth=state");
  if (params.get("error")) return finish("/dashboard?auth=denied");
  const code = params.get("code") || "";
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(code))
    return finish("/dashboard?auth=failed");
  let token = "";
  try {
    token = await exchangeCode(config, code, authorization.verifier);
    const identity = await readIdentity(token);
    const response = finish(authorization.next);
    response.cookies.set(GITHUB_SESSION_COOKIE, makeGitHubSession(identity), {
      httpOnly: true,
      secure: secureCookies(),
      sameSite: "lax",
      path: "/",
      maxAge: GITHUB_SESSION_LIFETIME,
    });
    return response;
  } catch {
    return finish("/dashboard?auth=failed");
  } finally {
    // Only the identity and installation ids are kept; the token itself is revoked.
    if (token) {
      const used = token;
      after(() => revokeToken(config, used));
    }
  }
}
