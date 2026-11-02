import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
const lifetime = 60 * 60 * 24;
function signature(payload: string) {
  const secret = process.env.CODEINTENT_SESSION_SECRET;
  if (!secret || secret.length < 32)
    throw new Error("Configure a session secret of at least 32 characters");
  return createHmac("sha256", secret).update(payload).digest("hex");
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
  return validateSession((await cookies()).get("ci_operator")?.value || "");
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
