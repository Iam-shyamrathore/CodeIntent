import { NextResponse } from "next/server";
import { redirectTo } from "@/lib/auth";
import {
  allowedOrigin,
  GITHUB_SESSION_COOKIE,
  OPERATOR_COOKIE,
} from "@/lib/session";

export const runtime = "nodejs";

/** Signs out of both GitHub and operator sessions. POST only, from this site's own pages. */
export async function POST(request: Request) {
  if (!allowedOrigin(request))
    return NextResponse.json(
      { detail: "Origin is not allowed" },
      { status: 403 },
    );
  // Plain form posts get a redirect; fetch callers asking for JSON get JSON.
  const response = request.headers.get("accept")?.includes("application/json")
    ? NextResponse.json({ signed_in: false })
    : redirectTo("/dashboard");
  response.headers.set("Cache-Control", "no-store");
  response.cookies.set(GITHUB_SESSION_COOKIE, "", { path: "/", maxAge: 0 });
  response.cookies.set(OPERATOR_COOKIE, "", { path: "/", maxAge: 0 });
  return response;
}
