import { NextResponse } from "next/server";
import { service } from "@/lib/server-api";
import {
  allowedOrigin,
  canAccessInstallation,
  getSession,
} from "@/lib/session";
export const runtime = "nodejs";
/** Creates a one-time Telegram link code for one installation in the caller's session. */
export async function POST(request: Request) {
  if (!allowedOrigin(request))
    return NextResponse.json(
      { detail: "Origin is not allowed" },
      { status: 403 },
    );
  const session = await getSession();
  if (!session)
    return NextResponse.json(
      { detail: "Sign in with GitHub to connect Telegram" },
      { status: 403 },
    );
  let installation: unknown;
  try {
    if (Number(request.headers.get("content-length") || 0) > 1024)
      throw new Error();
    ({ installation } = await request.json());
  } catch {
    return NextResponse.json({ detail: "Invalid request" }, { status: 400 });
  }
  if (
    typeof installation !== "number" ||
    !Number.isSafeInteger(installation) ||
    installation < 1
  )
    return NextResponse.json(
      { detail: "Invalid installation" },
      { status: 400 },
    );
  // Installations outside the session look exactly like ones that do not exist.
  if (!canAccessInstallation(session, installation))
    return NextResponse.json(
      { detail: "This installation no longer exists" },
      { status: 404, headers: { "Cache-Control": "no-store" } },
    );
  try {
    const response = await service(
      `/app/installations/${installation}/telegram-code`,
      { method: "POST" },
    );
    const data = await response.json();
    if (!response.ok)
      return NextResponse.json(
        {
          detail:
            response.status === 404
              ? "This installation no longer exists"
              : response.status === 503
                ? "Telegram is not configured on this deployment yet"
                : "A link code could not be created",
        },
        { status: response.status, headers: { "Cache-Control": "no-store" } },
      );
    return NextResponse.json(
      {
        code: data.code,
        expires_at: data.expires_at,
        deep_link: data.deep_link,
        group_link: data.group_link,
        bot_username: data.bot_username,
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { detail: "The verdict service is unavailable. Try again shortly." },
      { status: 503 },
    );
  }
}
