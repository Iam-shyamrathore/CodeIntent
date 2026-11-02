import "server-only";
export async function service(path: string, init: RequestInit = {}) {
  return fetch(
    `${process.env.CODEINTENT_API_URL || "http://127.0.0.1:8210"}${path}`,
    {
      ...init,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Api-Key": process.env.CODEINTENT_API_SECRET || "",
        ...init.headers,
      },
      signal: AbortSignal.timeout(120000),
    },
  );
}
