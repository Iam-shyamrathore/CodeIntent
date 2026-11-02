import { NextResponse } from "next/server";
import { createHash } from "node:crypto";
import { service } from "@/lib/server-api";
import { allowedOrigin, isOperator } from "@/lib/session";
export const runtime = "nodejs";
export const maxDuration = 120;
type Context = { params: Promise<{ path: string[] }> };
async function handle(request: Request, context: Context) {
  const { path } = await context.params;
  const route = path.join("/");
  const read =
    /^(repositories|reports|reports\/[a-f0-9-]{36}|indexes\/[a-f0-9]{24}|imports\/[a-f0-9-]{36}|ready)$/.test(
      route,
    );
  const write =
    /^(investigate|imports|imports\/[a-f0-9-]{36}\/(retry|cancel))$/.test(
      route,
    );
  if (
    (request.method === "GET" && !read) ||
    (request.method === "POST" && !write)
  )
    return NextResponse.json({ detail: "Route not found" }, { status: 404 });
  if (request.method === "POST" && !allowedOrigin(request))
    return NextResponse.json(
      { detail: "Origin is not allowed" },
      { status: 403 },
    );
  const admin = route === "imports" || /\/(retry|cancel)$/.test(route);
  if (admin && !(await isOperator()))
    return NextResponse.json(
      { detail: "Sign in to manage repository imports" },
      { status: 403 },
    );
  try {
    const url = new URL(request.url),
      query = new URLSearchParams();
    for (const key of ["repository", "after"]) {
      const v = url.searchParams.get(key);
      if (v) query.set(key, v);
    }
    const ip =
      request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
      "anonymous";
    const client = createHash("sha256")
      .update(ip + (process.env.CODEINTENT_API_SECRET || ""))
      .digest("hex");
    const body = request.method === "POST" ? await request.text() : undefined;
    if (body && Buffer.byteLength(body) > 8192)
      return NextResponse.json(
        { detail: "Request is too large" },
        { status: 413 },
      );
    const response = await service(
      `/${route}${query.size ? "?" + query : ""}`,
      {
        method: request.method,
        body,
        headers: {
          "X-Client-Key": client,
          ...(admin
            ? { "X-Operator-Key": process.env.CODEINTENT_OPERATOR_TOKEN || "" }
            : {}),
        },
      },
    );
    const data = await response.json();
    // FastAPI validation details are structured; keep the browser contract readable.
    if (Array.isArray(data.detail))
      data.detail = data.detail.map((d: { msg: string }) => d.msg).join(". ");
    return NextResponse.json(data, {
      status: response.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      {
        detail:
          "The evidence service is unavailable. Saved examples remain available; try again shortly.",
      },
      { status: 503 },
    );
  }
}
export const GET = handle;
export const POST = handle;
