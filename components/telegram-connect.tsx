"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowOut, PlaneMark } from "./site/icons";
import type { TelegramCode } from "@/lib/telegram";

/** "Connect Telegram": asks the server for a one-time code and shows how to use it. */
export function TelegramConnect({
  installation,
  account,
  label = "Connect Telegram",
  primary = false,
}: {
  installation: number;
  account: string;
  label?: string;
  primary?: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [code, setCode] = useState<TelegramCode | null>(null);
  async function create() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/telegram-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ installation }),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail);
      setCode(value as TelegramCode);
    } catch (e) {
      setError(
        e instanceof Error && e.message
          ? e.message
          : "A link code could not be created",
      );
    } finally {
      setBusy(false);
    }
  }
  const expires = code
    ? new Date(code.expires_at).toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";
  return (
    <div className="ci-tg-connect">
      {code ? (
        <div className="ci-tg-code" aria-live="polite">
          <p>
            Code for {account} · valid until{" "}
            <time dateTime={code.expires_at}>{expires}</time>
          </p>
          <code className="ci-tg-code-value" translate="no">
            {code.code}
          </code>
          <div className="ci-tg-actions">
            <a className="ci-btn" href={code.group_link}>
              <PlaneMark />
              Add to a group
            </a>
            <a className="ci-btn-quiet" href={code.deep_link}>
              Private chat <ArrowOut />
            </a>
          </div>
          <p>
            Bot already in the group? Send{" "}
            <code translate="no">/link {code.code}</code>
          </p>
          <div className="ci-tg-actions">
            <button
              className="ci-btn-quiet"
              onClick={() => router.refresh()}
              type="button"
            >
              I linked it
            </button>
            <button
              className="ci-btn-quiet"
              onClick={create}
              disabled={busy}
              type="button"
            >
              New code
            </button>
          </div>
        </div>
      ) : (
        <button
          className={primary ? "ci-btn" : "ci-btn-quiet"}
          onClick={create}
          disabled={busy}
          type="button"
        >
          <PlaneMark size={primary ? 16 : 14} />
          {busy ? "Creating a code…" : label}
        </button>
      )}
      <p role="alert" className="ci-error">
        {error}
      </p>
    </div>
  );
}
