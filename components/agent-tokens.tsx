"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { McpToken, NewMcpToken } from "@/lib/mcp";

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
        <div className="ci-tg-code" aria-live="polite">
          <p>
            Token for {account}. It is shown once; add it to your agent now.
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
          <p>
            Other agents: endpoint{" "}
            <code translate="no">{created.endpoint}</code> with header{" "}
            <code translate="no">Authorization: Bearer …</code>.
          </p>
        </div>
      ) : (
        <button
          className="ci-btn-quiet"
          type="button"
          onClick={() => call("POST")}
          disabled={busy}
        >
          {busy ? "Creating…" : "Create an agent token"}
        </button>
      )}
      {tokens.length > 0 && (
        <ul className="ci-agent-tokens" aria-label="Active agent tokens">
          {tokens.map((t) => (
            <li key={t.id}>
              <code translate="no">ci_mcp_…{t.hint}</code>
              <span>
                {t.last_used_at
                  ? `used ${new Date(t.last_used_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`
                  : "never used"}
              </span>
              <button
                className="ci-link"
                type="button"
                onClick={() => call("DELETE", t.id)}
                disabled={busy}
              >
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
