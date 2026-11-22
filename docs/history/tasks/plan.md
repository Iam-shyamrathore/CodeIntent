# Implementation Plan: CodeIntent upgrade verdicts

Source spec: [planning/finale-build-plan.md](../planning/finale-build-plan.md)

## Overview

CodeIntent tells a team whether a Python dependency upgrade breaks their code and why. It names the exact affected lines, the upstream decision behind the change (with cited PRs) and any later reversal. It explains every pin. Verdicts arrive on the Dependabot/Renovate PR and in Telegram, and an MCP server hands the fix brief to the team's AI agent. The existing ledger, Tree-sitter parsing, decision extraction, Neo4j graph and citation checks are reused.

## Architecture decisions

- **Research record:** [docs/research/phase-1-verdict-engine.md](../../research/phase-1-verdict-engine.md) holds the reuse decisions, experiments and sources behind this plan.
- **Verdicts are consumer-driven.** For every symbol and keyword argument the consumer uses, resolve it in both library versions using griffe's static model (`allow_inspection=False`), including non-public aliases. griffe's own breakage list alone caught only 2 of the 4 real outages; consumer-driven resolution caught 4 of 4.
- **Usage extraction uses LibCST** (scope and qualified-name metadata), following module-level aliases, local subclasses of library classes and `**kwargs` forwarding to `super().__init__` (needed for the real openai-python break).
- **Verdicts are deterministic. The model only explains.** "Breaks you" comes from static facts: the symbols and arguments your code uses, intersected with the API difference between the two library versions. The model links each difference to the upstream PR that explains it and drafts the replacement text, and every quote goes through the existing citation validation. A verdict never depends on model judgement alone.
- **Unknown means "Not checked", never "safe".** Dynamic access (`getattr`, `**kwargs` pass-through, star imports), transitive dependencies and anything we cannot parse are reported as not checked, with the reason.
- **Python first, direct dependencies first.** Manifests: `pyproject.toml`, `requirements*.txt`, `uv.lock`, `poetry.lock`. Transitive dependencies are listed but marked not checked in v1.
- **Shared upstream index.** A library release range (`package@from..to`) is collected, diffed and explained once, then reused by every workspace. Upstream data is public. Workspace data (repositories, usage, pins, verdicts) is always scoped by `workspace_id`.
- **The PyPI package maps to its repository** through PyPI `project_urls`; release tags are matched against the version (`0.28.0`, `v0.28.0`, `httpx-0.28.0`).
- **GitHub App, not an OAuth app.** It provides installation tokens for private repositories, webhooks, check runs and sign-in, with least-privilege permissions.
- **Existing runtime is reused:** FastAPI service, Procrastinate worker on PostgreSQL, Neo4j, Next.js web. Webhooks, Telegram updates and MCP calls are served by the API, and all heavy work runs as durable jobs.
- **MCP** runs on FastMCP over streamable HTTP, authenticated with a per-workspace token.
- **Telegram** runs as an async bot library inside the API process (webhook mode in production, long polling locally).
- **Neo4j holds the connected model:** `Repository → File → Usage → LibrarySymbol ← APIChange → Decision → Source`, plus `Pin → IntroducedBy → Source`. PostgreSQL holds the ledger, jobs, workspaces, webhook deliveries and verdict records.

## Code layout

```
codeintent/upgrades/
  models.py           typed records: Dependency, Pin, Usage, ApiChange, Verdict, NotChecked
  manifests/          requirements.py, pyproject.py, uvlock.py, poetrylock.py, toml_lines.py
  usage/              extractor.py (LibCST), distributions.py (import name -> distribution)
  artifacts.py        PyPI download, SHA-256 check, safe extraction, cache
  surface.py          griffe static loading and symbol resolution
  releases.py         package -> repository, versions -> tags
  verdict.py          usage x surface diff -> verdict
scripts/verdict.py    CLI
tests/upgrades/       unit tests; tests/fixtures/upgrades/ for manifests and code samples
evals/upgrades.json   labelled backtest cases
```

## Phases

| Phase | Outcome | Why this order |
| --- | --- | --- |
| 0. Gates and baseline | Current app live on a public URL, ArgosX baseline scan, Next.js advisory fixed | The baseline scan is due by midnight 21 Nov, and the live URL is a submission gate |
| 1. Verdict engine (offline) | A CLI returns correct verdicts for the 4 real breakages and no false alarms on harmless upgrades | Highest risk: if this fails, nothing else matters |
| 2. Graph, shared index, pins | Verdicts and pins stored in Neo4j/Postgres and reused across workspaces | Everything user-facing reads from here |
| 3. GitHub App | A real Dependabot PR on a real repo gets a check and comment automatically | The primary journey |
| 4. Telegram and MCP | Alerts and commands in Telegram; agents fetch fix briefs | Workspace channels |
| 5. Web app | Install flow, repository overview, verdict report | Self-serve evaluation |
| 6. Harden and ship | Observability, failure states, security review, final ArgosX scan, docs, demo repo | Production bar |

The market track (interviews, canvas, persona matrix) runs in parallel with every phase and does not block code.

## Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Static API diff misses behaviour-only changes (e.g. changed defaults inside function bodies) | High | Diff literal defaults too; surface changelog and PR decisions for touched symbols as "Needs a change: review"; measure on the harmless set |
| Dynamic Python hides usage | High | Report "Not checked" with the reason; never call it safe |
| Inconsistent tag names, or no tags | Med | Try multiple tag patterns, fall back to PyPI release dates mapped to commits; otherwise "Not checked: release not located" |
| GitHub rate limits when collecting a range | Med | Installation tokens, ETag caching, the shared index (collect once), backoff already in `GitHub.get` |
| Webhook replay or duplicates | Med | Verify signatures; idempotency table keyed by `X-GitHub-Delivery` |
| Cross-workspace data leak | High | `workspace_id` on every row and graph node; isolation tests; reports scoped |
| ArgosX deadlines (baseline by 21 Nov midnight, final by 22 Nov 11 AM) | High | Phase 0 first; final scan reserved in Phase 6 |
| New dependencies (GitHub App JWT, Telegram, FastMCP) | Med | Pin versions released at least 7 days ago; check licences |

## Open questions

- Hosting target for the live URL: the existing Heroku config, or Render/Vercel plus managed Postgres and Aura?
- Who owns the GitHub App registration and the Telegram bot token (team account)?
- ArgosX account access and the target URL to scan.
- Payer evidence: the three interviews (security/platform leads) still need to happen.

Tasks: [tasks/todo.md](todo.md)
