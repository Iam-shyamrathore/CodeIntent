"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowUpRight, LoaderCircle, RefreshCw, Send } from "lucide-react";
import type { TelegramCode } from "@/lib/telegram";

/** "Connect Telegram": asks the server for a one-time code and shows how to use it. */
export function TelegramConnect({
  installation,
  account,
}: {
  installation: number;
  account: string;
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
    <div className="telegram-connect">
      {code ? (
        <div className="telegram-code" aria-live="polite">
          <p>
            One-time code for {account}, valid for 15 minutes (until{" "}
            <time dateTime={code.expires_at}>{expires}</time>):
          </p>
          <code className="telegram-code-value">{code.code}</code>
          <div className="telegram-actions">
            <a className="primary-button" href={code.deep_link}>
              Open @{code.bot_username}
              <ArrowUpRight size={17} aria-hidden="true" />
            </a>
            <a className="text-link" href={code.group_link}>
              Add to a group <ArrowUpRight size={14} aria-hidden="true" />
            </a>
          </div>
          <p>
            Or send <code>/link {code.code}</code> to @{code.bot_username} in
            any chat the bot is in. Each code links one chat.
          </p>
          <div className="telegram-actions">
            <button
              className="quiet-button"
              onClick={() => router.refresh()}
              type="button"
            >
              <RefreshCw size={14} aria-hidden="true" />
              Refresh linked chats
            </button>
            <button
              className="quiet-button"
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
          className="quiet-button telegram-start"
          onClick={create}
          disabled={busy}
          type="button"
        >
          {busy ? (
            <>
              <LoaderCircle className="loading-icon" size={14} />
              Creating a code…
            </>
          ) : (
            <>
              <Send size={14} aria-hidden="true" />
              Connect Telegram
            </>
          )}
        </button>
      )}
      <p role="alert" className="request-error console-form-error">
        {error}
      </p>
    </div>
  );
}
