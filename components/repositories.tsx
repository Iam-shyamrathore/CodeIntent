"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  GitBranch,
  LoaderCircle,
  RefreshCw,
  LockKeyhole,
} from "lucide-react";
import { Brand } from "./brand";

type Repository = {
  id: number;
  name: string;
  ready_index?: string;
  revision?: string;
  sources?: number;
  indexed_at?: string;
  coverage?: { scope: string };
};
type Import = {
  id: string;
  repository: string;
  status: string;
  stage: string;
  progress: number;
  error?: string;
  created_at: string;
};
type Data = {
  repositories: Repository[];
  imports: Import[];
  worker_online: boolean;
};
export default function Repositories() {
  const [data, setData] = useState<Data | null>(null),
    [error, setError] = useState(""),
    [operator, setOperator] = useState(false);
  const [loadError, setLoadError] = useState(""),
    [access, setAccess] = useState(false),
    [key, setKey] = useState(""),
    [repo, setRepo] = useState(""),
    [numbers, setNumbers] = useState(""),
    [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<
      { id: number; message: string; stage: string; created_at: string }[]
    >([]),
    [selected, setSelected] = useState("");
  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/service/repositories");
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail);
      setData(value);
      setLoadError("");
    } catch (e) {
      setLoadError(
        e instanceof Error ? e.message : "Could not load repositories",
      );
    }
  }, []);
  useEffect(() => {
    load();
    fetch("/api/session")
      .then((r) => r.json())
      .then((v) => setOperator(v.operator))
      .catch(() => {});
    const interval = setInterval(load, 4000);
    return () => clearInterval(interval);
  }, [load]);
  useEffect(() => {
    if (!selected) return;
    const update = () =>
      fetch(`/api/service/imports/${selected}`)
        .then((r) => r.json())
        .then((v) => setEvents(v.events || []))
        .catch(() => {});
    update();
    const interval = setInterval(update, 2500);
    return () => clearInterval(interval);
  }, [selected]);
  async function login(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: key }),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail);
      setOperator(true);
      setKey("");
      setAccess(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const pulls = numbers.trim()
        ? numbers.split(/[,\s]+/).map((n) => Number(n.replace(/^#/, "")))
        : [];
      if (pulls.some((n) => !Number.isInteger(n) || n < 1))
        throw new Error("Use pull request numbers separated by commas");
      const response = await fetch("/api/service/imports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repository: repo,
          pull_requests: pulls,
          limit: 12,
        }),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail);
      setSelected(value.id);
      setRepo("");
      setNumbers("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start import");
    } finally {
      setBusy(false);
    }
  }
  async function action(id: string, action: "retry" | "cancel") {
    setBusy(true);
    setError("");
    try {
      const r = await fetch(`/api/service/imports/${id}/${action}`, {
        method: "POST",
      });
      const v = await r.json();
      if (!r.ok) throw new Error(v.detail);
      await load();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The import could not be updated",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="repository-page">
      <header className="collection-header">
        <Brand />
        <div>
          <Link href="/investigate">
            Open example <ArrowUpRight size={14} />
          </Link>
          <button
            className="quiet-button"
            onClick={async () => {
              if (operator) {
                await fetch("/api/session", { method: "DELETE" });
                setOperator(false);
              } else setAccess(!access);
            }}
          >
            <LockKeyhole size={14} />
            {operator ? "Sign out" : "Workspace access"}
          </button>
        </div>
      </header>
      <main className="collection-main">
        <div className="collection-intro">
          <div>
            <p className="collection-breadcrumb">Workspace / Repositories</p>
            <h1>A memory for your code.</h1>
            <p>
              Bring the source and its conversations together. Then ask what led
              here.
            </p>
          </div>
          <button
            className="quiet-button"
            onClick={load}
            aria-label="Refresh repositories"
          >
            <RefreshCw size={16} />
          </button>
        </div>
        {(error || loadError) && (
          <p role="alert" className="request-error collection-error">
            {error || loadError}
          </p>
        )}
        {access && !operator && (
          <form onSubmit={login} className="access-form">
            <label htmlFor="workspace-key">Workspace key</label>
            <p>
              Operator access is required to import public repositories.
              Existing investigations are open to everyone.
            </p>
            <div>
              <input
                id="workspace-key"
                type="password"
                autoComplete="current-password"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                required
              />
              <button className="primary-button" disabled={busy}>
                Sign in <ArrowRight size={16} />
              </button>
            </div>
          </form>
        )}
        {operator && (
          <form className="import-form" onSubmit={create}>
            <div>
              <h2>Import a repository</h2>
              <p>
                Public GitHub sources only. Your existing index stays available
                during a refresh.
              </p>
            </div>
            <label htmlFor="repository">GitHub repository</label>
            <input
              id="repository"
              placeholder="owner/repository"
              value={repo}
              onChange={(e) => setRepo(e.target.value)}
              required
              maxLength={180}
            />
            <div className="import-options">
              <div>
                <label htmlFor="pr-numbers">
                  Specific pull requests <span>optional</span>
                </label>
                <input
                  id="pr-numbers"
                  placeholder="2241, 2481, 3050"
                  value={numbers}
                  onChange={(e) => setNumbers(e.target.value)}
                  maxLength={250}
                />
                <p>
                  Leave empty to capture the 12 most recently updated closed
                  pull requests.
                </p>
              </div>
              <button
                className="primary-button"
                disabled={busy || !repo.trim()}
              >
                {busy ? (
                  <LoaderCircle className="loading-icon" size={16} />
                ) : (
                  <>
                    Start import <ArrowRight size={16} />
                  </>
                )}
              </button>
            </div>
            <p className="import-note">
              Captures bounded discussions and up to 40 source files. Coverage
              and omissions are recorded with each index.
            </p>
          </form>
        )}
        <section
          aria-labelledby="repositories-heading"
          className="repository-collection"
        >
          <div className="section-line">
            <h2 id="repositories-heading">Ready to investigate</h2>
            <span>
              {data?.repositories.filter((r) => r.ready_index).length || 0}{" "}
              repositories
            </span>
          </div>
          {!data && !error && (
            <p className="muted-state" role="status">
              Loading repositories…
            </p>
          )}
          {data?.repositories
            .filter((r) => r.ready_index)
            .map((r) => (
              <Link
                key={r.id}
                className="repository-row"
                href={`/investigate?repository=${encodeURIComponent(r.name)}`}
              >
                <GitBranch size={20} />
                <div>
                  <h3>{r.name}</h3>
                  <p>{r.coverage?.scope}</p>
                  <span>
                    {r.sources} captured sources · {r.revision?.slice(0, 7)} ·{" "}
                    {r.indexed_at &&
                      new Date(r.indexed_at).toLocaleDateString("en-GB", {
                        timeZone: "UTC",
                      })}
                  </span>
                </div>
                <ArrowRight size={20} />
              </Link>
            ))}
          {data && !data.repositories.some((r) => r.ready_index) && (
            <div className="muted-state">
              <p>No repository index is ready yet.</p>
              <p>
                Import a public repository with workspace access, or explore the
                saved HTTPX example.
              </p>
              <Link href="/investigate" className="text-link">
                Explore the example <ArrowRight size={14} />
              </Link>
            </div>
          )}
        </section>
        {!!data?.imports.length && (
          <section className="imports-section">
            <div className="section-line">
              <h2>Import history</h2>
              <span>
                {data.worker_online
                  ? "Worker connected"
                  : "Worker offline · queued imports will wait"}
              </span>
            </div>
            {data.imports.map((j) => (
              <article className="import-row" key={j.id}>
                <div className="import-row-top">
                  <button
                    className="job-title"
                    onClick={() => setSelected(selected === j.id ? "" : j.id)}
                    aria-expanded={selected === j.id}
                  >
                    {j.repository}
                    <span>{j.status === "running" ? j.stage : j.status}</span>
                  </button>
                  <div>
                    {j.status === "ready" ? (
                      <Link
                        href={`/investigate?repository=${encodeURIComponent(j.repository)}`}
                      >
                        Investigate <ArrowUpRight size={14} />
                      </Link>
                    ) : (
                      operator &&
                      (j.status === "failed" || j.status === "cancelled" ? (
                        <button
                          onClick={() => action(j.id, "retry")}
                          disabled={busy}
                        >
                          Retry import
                        </button>
                      ) : (
                        <button
                          onClick={() => action(j.id, "cancel")}
                          disabled={busy}
                        >
                          Cancel
                        </button>
                      ))
                    )}
                  </div>
                </div>
                <progress
                  max={100}
                  value={j.progress}
                  aria-label={`${j.repository} import progress`}
                />
                {j.error && <p className="job-error">{j.error}</p>}
                {selected === j.id && (
                  <ol className="job-events">
                    {events.map((e) => (
                      <li key={e.id}>
                        <time>
                          {new Date(e.created_at).toLocaleTimeString("en-GB", {
                            timeZone: "UTC",
                          })}{" "}
                          UTC
                        </time>
                        <span>{e.message}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </article>
            ))}
          </section>
        )}
        <p className="collection-footnote">
          Every index is a snapshot. An unanswered question is a visible limit
          of the record.
        </p>
      </main>
    </div>
  );
}
