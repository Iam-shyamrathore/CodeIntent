import { NextResponse } from "next/server";
import { service } from "@/lib/server-api";
import {
  allowedOrigin,
  canAccessInstallation,
  getSession,
} from "@/lib/session";
export const runtime = "nodejs";

const headers = { "Cache-Control": "no-store" };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** The public MCP endpoint: the API's own origin, since the API serves /mcp. */
function endpoint() {
  const base = (
    process.env.CODEINTENT_MCP_URL ||
    process.env.CODEINTENT_API_URL ||
    ""
  ).replace(/\/$/, "");
  return base.endsWith("/mcp") ? base : `${base}/mcp`;
}

async function parse(
  request: Request,
): Promise<
  | { ok: true; installation: number; id?: string }
  | { ok: false; response: NextResponse }
> {
  const fail = (detail: string, status: number) => ({
    ok: false as const,
    response: NextResponse.json({ detail }, { status, headers }),
  });
  if (!allowedOrigin(request)) return fail("Origin is not allowed", 403);
  const session = await getSession();
  if (!session) return fail("Sign in with GitHub to manage agent tokens", 403);
  let body: { installation?: unknown; id?: unknown };
  try {
    if (Number(request.headers.get("content-length") || 0) > 1024)
      throw new Error();
    body = await request.json();
  } catch {
    return fail("Invalid request", 400);
  }
  const { installation, id } = body;
  if (
    typeof installation !== "number" ||
    !Number.isSafeInteger(installation) ||
    installation < 1 ||
    (id !== undefined && (typeof id !== "string" || !UUID.test(id)))
  )
    return fail("Invalid request", 400);
  // Installations outside the session look exactly like ones that do not exist.
  if (!canAccessInstallation(session, installation))
    return fail("This installation no longer exists", 404);
  return { ok: true, installation, id: id as string | undefined };
}

/** Creates a token for one installation in the caller's session; it is returned once. */
export async function POST(request: Request) {
  const parsed = await parse(request);
  if (!parsed.ok) return parsed.response;
  try {
    const response = await service(
      `/app/installations/${parsed.installation}/mcp-tokens`,
      { method: "POST" },
    );
    const data = await response.json();
    if (!response.ok)
      return NextResponse.json(
        {
          detail:
            response.status === 409
              ? data.detail
              : response.status === 404
                ? "This installation no longer exists"
                : "A token could not be created",
        },
        { status: response.status, headers },
      );
    return NextResponse.json(
      { ...data, endpoint: endpoint() },
      { status: 201, headers },
    );
  } catch {
    return NextResponse.json(
      { detail: "The verdict service is unavailable. Try again shortly." },
      { status: 503, headers },
    );
  }
}

/** Revokes one token of an installation in the caller's session. */
export async function DELETE(request: Request) {
  const parsed = await parse(request);
  if (!parsed.ok) return parsed.response;
  if (!parsed.id)
    return NextResponse.json(
      { detail: "Invalid request" },
      { status: 400, headers },
    );
  try {
    const response = await service(
      `/app/installations/${parsed.installation}/mcp-tokens/${parsed.id}`,
      { method: "DELETE" },
    );
    return new NextResponse(null, {
      status: response.status === 204 ? 204 : response.status,
      headers,
    });
  } catch {
    return NextResponse.json(
      { detail: "The verdict service is unavailable. Try again shortly." },
      { status: 503, headers },
    );
  }
}
