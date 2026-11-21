"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

/** "Scan now": queues an upcoming-breakage scan, then refreshes the page to show its progress. */
export function ScanNow({
  repository,
  busy: running,
}: {
  repository: string;
  busy: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  async function scan() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repository }),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail);
      setMessage(
        value.status === "already-queued"
          ? "A scan is already queued."
          : "Scan queued. Results appear here in a minute or two.",
      );
      router.refresh();
    } catch (e) {
      setMessage(
        e instanceof Error && e.message
          ? e.message
          : "The scan could not be queued",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <span className="ci-scan-now">
      <button
        className="ci-btn-quiet"
        type="button"
        onClick={scan}
        disabled={busy || running}
      >
        {running ? "Scanning…" : busy ? "Queuing…" : "Scan now"}
      </button>
      <span role="status" aria-live="polite">
        {message}
      </span>
    </span>
  );
}
