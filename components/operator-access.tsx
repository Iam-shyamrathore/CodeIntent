"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, LoaderCircle } from "lucide-react";

/** The workspace-key form: the operator's admin fallback, secondary to GitHub sign-in. */
export function OperatorSignIn({ purpose }: { purpose: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const token = new FormData(e.currentTarget).get("token");
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not sign in");
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="access-form">
      <label htmlFor="workspace-key">Workspace key</label>
      <p>{purpose}</p>
      <div>
        <input
          id="workspace-key"
          name="token"
          type="password"
          autoComplete="current-password"
          spellCheck={false}
          required
          maxLength={512}
          aria-describedby={error ? "workspace-key-error" : undefined}
        />
        <button className="primary-button" disabled={busy}>
          {busy ? (
            <>
              Signing in… <LoaderCircle className="loading-icon" size={16} />
            </>
          ) : (
            <>
              Sign in <ArrowRight size={16} aria-hidden="true" />
            </>
          )}
        </button>
      </div>
      <p
        id="workspace-key-error"
        role="alert"
        aria-live="polite"
        className="request-error console-form-error"
      >
        {error}
      </p>
    </form>
  );
}
