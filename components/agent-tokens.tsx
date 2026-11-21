"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import type { McpToken, NewMcpToken } from "@/lib/mcp";

const ICON = { size: 15, strokeWidth: 1.5, "aria-hidden": true } as const;

/** "AI agents": create an MCP token (shown once, with the command to add it) and revoke old ones. */
export function AgentTokens({
  installation,
  account,
  tokens,
}: {
  installation: number;
  account: string;
  tokens: McpToken[];
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [created, setCreated] = useState<NewMcpToken | null>(null),
    [copied, setCopied] = useState(false);
  async function call(method: "POST" | "DELETE", id?: string) {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/mcp-token", {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ installation, id }),
      });
      if (method === "POST") {
        const value = await response.json();
        if (!response.ok) throw new Error(value.detail);
        setCreated(value as NewMcpToken);
        setCopied(false);
      } else if (!response.ok)
        throw new Error("The token could not be revoked");
      router.refresh();
    } catch (e) {
      setError(
        e instanceof Error && e.message ? e.message : "Something went wrong",
      );
    } finally {
      setBusy(false);
    }
  }
  const command = created
    ? `claude mcp add --transport http codeintent ${created.endpoint} --header "Authorization: Bearer ${created.token}"`
    : "";
  return (
    <div className="ci-agents">
      {created ? (
        <div className="ci-token-new" aria-live="polite">
          <p>
            <Check {...ICON} /> Token for {account} · shown once
          </p>
          <code className="ci-agent-command" translate="no">
            {command}
          </code>
          <div className="ci-tg-actions">
            <button
              className="ci-btn"
              type="button"
              onClick={async () => {
                await navigator.clipboard.writeText(command);
                setCopied(true);
              }}
            >
              {copied ? <Check {...ICON} /> : <Copy {...ICON} />}
              {copied ? "Copied" : "Copy command"}
            </button>
            <button
              className="ci-btn-quiet"
              type="button"
              onClick={() => setCreated(null)}
            >
              Done
            </button>
          </div>
        </div>
      ) : (
        <button
          className="ci-btn"
          type="button"
          onClick={() => call("POST")}
          disabled={busy}
        >
          <Plus {...ICON} />
          {busy ? "Creating…" : "Create token"}
        </button>
      )}
      {tokens.length > 0 && (
        <ul className="ci-agent-tokens" aria-label={`Tokens for ${account}`}>
          {tokens.map((t) => (
            <li key={t.id}>
              <KeyRound {...ICON} />
              <code translate="no">…{t.hint}</code>
              <span>
                {t.last_used_at
                  ? `Used ${new Date(t.last_used_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`
                  : "Never used"}
              </span>
              <button
                className="ci-icon-btn"
                type="button"
                onClick={() => call("DELETE", t.id)}
                disabled={busy}
                aria-label={`Revoke token ending ${t.hint}`}
              >
                <Trash2 {...ICON} />
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}
      <p role="alert" className="ci-error">
        {error}
      </p>
    </div>
  );
}
