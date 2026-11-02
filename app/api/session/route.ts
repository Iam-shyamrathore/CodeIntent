import { NextResponse } from "next/server";
import { timingSafeEqual, createHash } from "node:crypto";
import { allowedOrigin, isOperator, makeSession } from "@/lib/session";
export async function GET() {
  return NextResponse.json(
    { operator: await isOperator() },
    { headers: { "Cache-Control": "no-store" } },
  );
}
const attempts = new Map<string, { count: number; reset: number }>();
export async function POST(request: Request) {
  if (!allowedOrigin(request))
    return NextResponse.json(
      { detail: "Origin is not allowed" },
      { status: 403 },
    );
  const ip = request.headers.get("x-forwarded-for") || "anonymous",
    now = Date.now();
  const record = attempts.get(ip);
  if (record && record.reset > now && record.count >= 5)
    return NextResponse.json(
      { detail: "Too many attempts. Wait ten minutes." },
      { status: 429 },
    );
  if (attempts.size > 10000)
    for (const [key, value] of attempts)
      if (value.reset <= now) attempts.delete(key);
  attempts.set(ip, {
    count: record && record.reset > now ? record.count + 1 : 1,
    reset: record && record.reset > now ? record.reset : now + 600000,
  });
  try {
    if (Number(request.headers.get("content-length") || 0) > 4096)
      throw new Error();
    const { token } = await request.json(),
      expected = process.env.CODEINTENT_OPERATOR_TOKEN;
    if (
      !expected ||
      expected.length < 32 ||
      typeof token !== "string" ||
      token.length > 512 ||
      !timingSafeEqual(
        createHash("sha256").update(token).digest(),
        createHash("sha256").update(expected).digest(),
      )
    ) {
      return NextResponse.json(
        { detail: "The workspace key was not accepted" },
        { status: 401 },
      );
    }
    const response = NextResponse.json({ operator: true });
    response.cookies.set("ci_operator", makeSession(), {
      httpOnly: true,
      sameSite: "strict",
      secure:
        process.env.CODEINTENT_PUBLIC_URL?.startsWith("https://") || false,
      path: "/",
      maxAge: 86400,
    });
    attempts.delete(ip);
    return response;
  } catch {
    return NextResponse.json(
      { detail: "Enter the workspace key" },
      { status: 400 },
    );
  }
}
export async function DELETE(request: Request) {
  if (!allowedOrigin(request))
    return NextResponse.json(
      { detail: "Origin is not allowed" },
      { status: 403 },
    );
  const response = NextResponse.json({ operator: false });
  response.cookies.set("ci_operator", "", { path: "/", maxAge: 0 });
  return response;
}
