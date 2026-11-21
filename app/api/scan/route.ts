import { NextResponse } from "next/server";
import { GITHUB_NAME } from "@/lib/dashboard";
import { service } from "@/lib/server-api";
import { allowedOrigin, getSession, installationQuery } from "@/lib/session";
export const runtime = "nodejs";
/** Queues an upcoming-breakage scan of one repository in the caller's installations. */
export async function POST(request: Request) {
  const headers = { "Cache-Control": "no-store" };
  if (!allowedOrigin(request))
    return NextResponse.json(
      { detail: "Origin is not allowed" },
      { status: 403, headers },
    );
  const session = await getSession();
  if (!session)
    return NextResponse.json(
      { detail: "Sign in with GitHub to scan a repository" },
      { status: 403, headers },
    );
  let repository: unknown;
  try {
    if (Number(request.headers.get("content-length") || 0) > 1024)
      throw new Error();
    ({ repository } = await request.json());
  } catch {
    return NextResponse.json(
      { detail: "Invalid request" },
      { status: 400, headers },
    );
  }
  const [owner, name, extra] =
    typeof repository === "string" ? repository.split("/") : [];
  if (
    !owner ||
    !name ||
    extra !== undefined ||
    !GITHUB_NAME.test(owner) ||
    !GITHUB_NAME.test(name)
  )
    return NextResponse.json(
      { detail: "Invalid repository" },
      { status: 400, headers },
    );
  if (session.kind === "github" && session.installations.length === 0)
    return NextResponse.json(
      { detail: "Repository not found" },
      { status: 404, headers },
    );
  const scope =
    session.kind === "github" ? `?${installationQuery(session)}` : "";
  try {
    const response = await service(
      `/app/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/scan${scope}`,
      { method: "POST" },
    );
    if (!response.ok)
      return NextResponse.json(
        {
          detail:
            response.status === 404
              ? "Repository not found"
              : "The scan could not be queued",
        },
        { status: response.status === 404 ? 404 : 502, headers },
      );
    return NextResponse.json(await response.json(), { status: 202, headers });
  } catch {
    return NextResponse.json(
      { detail: "The verdict service is unavailable. Try again shortly." },
      { status: 503, headers },
    );
  }
}
