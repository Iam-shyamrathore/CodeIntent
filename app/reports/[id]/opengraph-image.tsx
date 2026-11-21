import { ImageResponse } from "next/og";

export const alt = "A Code Intent saved investigation";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

async function loadReport(id: string) {
  try {
    const response = await fetch(
      `${process.env.CODEINTENT_API_URL || "http://127.0.0.1:8210"}/reports/${id}`,
      {
        headers: { "X-Api-Key": process.env.CODEINTENT_API_SECRET || "" },
        signal: AbortSignal.timeout(8000),
      },
    );
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

export default async function Image({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const study = /^[a-f0-9-]{36}$/.test(id) ? await loadReport(id) : null;
  const question = study?.question || "Know why this code exists";
  const detail = study
    ? `${study.repository} @ ${String(study.revision).slice(0, 7)} · ${study.answer?.claims?.length ?? 0} verified claims`
    : "Evidence-backed code investigations";

  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        background: "#0a0d11",
        color: "#e9edf2",
        padding: "72px 80px",
        fontFamily: "sans-serif",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          fontSize: 30,
          letterSpacing: -0.5,
          color: "#e9edf2",
        }}
      >
        <span style={{ color: "#7ea3f0", marginRight: 14, fontSize: 34 }}>
          [·]
        </span>
        code intent
        <span style={{ color: "#7ea3f0" }}>.</span>
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          fontSize: 56,
          lineHeight: 1.2,
          letterSpacing: -2,
          maxWidth: 1000,
        }}
      >
        <span
          style={{
            display: "-webkit-box",
            WebkitBoxOrient: "vertical",
            WebkitLineClamp: 3,
            overflow: "hidden",
          }}
        >
          {question}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontSize: 24,
          color: "#9ba8b5",
        }}
      >
        <span>{detail}</span>
        <span style={{ color: "#e9d8a6" }}>Every claim cites its source.</span>
      </div>
    </div>,
    { ...size },
  );
}
