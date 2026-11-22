# CodeIntent

**Know what a dependency upgrade breaks before you merge it.**

When Dependabot, Renovate or a developer opens a pull request that changes a Python dependency,
CodeIntent tells you whether the upgrade breaks your code, gives the exact file and line, says what
to change, and shows which functions, routes, tests and scripts depend on that line. It links each
claim to the upstream pull request that made the change. Then it gives your AI coding agent
everything it needs to fix the code, over MCP.

The verdict comes from deterministic static analysis of your code and of both library releases. No
model decides it. Gemini agents add context on top of it (suggested fixes, release-note behaviour
changes, security news), and their output is always labelled as the agent's.

| | |
| --- | --- |
| Dashboard | https://codeintent.shyam.codes |
| Live example (Breaks you) | https://github.com/Iam-shyamrathore/codeintent-demo/pull/4 |
| API and MCP endpoint | `https://codeintent-api-ded80aad7f4b.herokuapp.com/mcp` |
| Five-minute walkthrough | [docs/evaluator-guide.md](docs/evaluator-guide.md) |

## What a developer gets

On a dependency pull request, CodeIntent adds one check run and one comment, and edits the comment in
place on later pushes:

- **One verdict per package:** `Breaks you`, `Needs a change`, `No known impact` or `Not checked`.
  `Not checked` always gives a reason (for example `**kwargs` passthrough or a dynamic attribute). It
  never quietly becomes "safe".
- **The exact place and the fix:** `weather/client.py:12`: `httpx.Client(proxies=)` was removed in
  0.28.0, so use `proxy=` or `mounts=`. Quoted from encode/httpx#3319.
- **Where the package reaches your code:** every line that uses it. If you never import the package,
  the chain that pulls it in instead, for example `httpx → httpcore → h11`.
- **What else this breaks**, read from the code graph: the function that holds the broken line, its
  callers, the files that import it, and any tests, routes and console scripts that reach it.
- **Known vulnerabilities** (OSV.dev) in the old and new versions.
- **Agent review** (Gemini, labelled as the agent's):
  - a suggested edit, which CodeIntent applies to a copy and analyses again;
  - assessments of uses static analysis couldn't follow;
  - behaviour changes quoted from the release notes.
- **"Fix it with your AI agent":** `fix_brief(repo, pr)` gives Claude Code, Codex, Cursor or Devin the
  edits, current code, upstream evidence and dependents in one structured call.

Away from pull requests:

- **Before you upgrade:** a daily check of every locked dependency against its latest release, before
  any PR exists.
- **Security news:** a daily web search (Serper) for reports on the packages you lock. CodeIntent
  checks the version range and cross-checks OSV.dev itself.
- **Telegram:** team alerts, plus `/status` and `/why <package>`.
- **Dashboard:** runs, breaks, the repository and ecosystem graphs, security news, AI-agent tokens and
  operations.

## How it works

```
GitHub App installed ──► scan every accessible repository's default branch
                          ├─ manifests and locks (pyproject, requirements, uv.lock, poetry.lock)
                          ├─ code map: files, imports, functions, calls, tests, entry points (ast)
                          ├─ every dependency use, line by line (LibCST)
                          └─ project into Neo4j: workspace graph ⇄ shared ecosystem graph

Dependency PR opened ──► signed webhook ─► durable job (PostgreSQL / Procrastinate)
                          ├─ download both releases from PyPI (SHA-256 checked, never installed)
                          ├─ compare the API surface you use, old vs new (griffe)
                          ├─ OSV advisories + upstream PR/commit that made each change
                          ├─ deterministic verdict per package
                          ├─ graph trace: reach, transitive chain, blast radius
                          └─ check run + comment + Telegram + Neo4j projection
                                     │
                                     └─► agents queue (separate process): patcher, investigator,
                                         release-notes reader → agent section, fix_brief
```

Library code and customer code are only downloaded and parsed. Nothing is installed, imported, built
or executed.

### Neo4j: two graphs, one query

The **shared ecosystem graph** holds public facts: packages, releases, the dependencies between
releases, source repositories, advisories and upstream pull requests. Each installation's
**workspace graph** holds its own code and links into the shared one:

```
(:Repository)-[:CONTAINS]->(:File)-[:HAS_LINE]->(:CodeLine)-[:USES]->(:Symbol)
(:File)-[:DEFINES]->(:Function)<-[:INSIDE]-(:CodeLine)
(:File)-[:IMPORTS]->(:File)        (:Function)-[:CALLS]->(:Function)
(:Repository)-[:LOCKS]->(:Release)-[:DEPENDS_ON]->(:Release)
(:Run)-[:CHECKED]->(:Upgrade)-[:FOUND]->(:Finding)-[:AT]->(:CodeLine)
(:Finding)-[:CAUSED_BY]->(:APIChange)-[:CHANGED_IN]->(:UpstreamPR)
(:Advisory)-[:AFFECTS]->(:Release)
```

One traversal answers "this PR → the API change → your line → the function it's in → everything that
calls it → the upstream decision". Public nodes carry no workspace data. Workspace nodes carry their
installation id, and every query filters on it. PostgreSQL is the source of truth, so the graph can
always be rebuilt (`workspace_graph.rebuild(installation_id)` re-projects every run and code map). Demo queries are in
[docs/neo4j.md](docs/neo4j.md); the Browser style is [docs/neo4j/codeintent.grass](docs/neo4j/codeintent.grass).

### MCP tools for coding agents

The endpoint is streamable HTTP at `/mcp`. Each token belongs to one workspace and is shown once,
stored as a SHA-256 digest and revocable. Every tool is read-only and returns schema-checked JSON.

| Tool | Answers |
| --- | --- |
| `fix_brief` | Everything needed to fix one dependency PR: edits, code, evidence, dependents, agent output |
| `upgrade_brief` | What breaks if package X moves to version Y, and the ordered steps |
| `impact` | Which lines across your repositories a library change touches |
| `who_uses` | Where your repositories use a library |
| `dependency_path` | The chain of releases that explains why a transitive package is installed |
| `dependents` | A package's source repository, dependencies, dependents, advisories and the repositories that depend on it |
| `why_pinned` | Every pin of a package, and the commit and PR that added it |
| `list_dependencies` | Direct dependencies and newer releases |
| `advisories` | OSV advisories for every locked package |

Details: [docs/mcp.md](docs/mcp.md).

### Agents

The harness lives in `codeintent/agent/` and follows Codex CLI's agent loop and Hermes Agent's
toolsets and `SOUL.md` prompts. Its graph tools follow CodexGraph and LocAgent; its
"the engine finds the place, the agent repairs, the engine validates" flow follows Agentless.

- **Limits:** a turn budget and a fallback model for every agent; parallel read-only tool calls;
  tool output capped in size.
- **Checked answers:** every answer must match a schema and pass deterministic checks before it is
  used. Quotes must exist in the source, and edits must match the file.
- **Prompt injection:** following the prompt-injection design-patterns and CaMeL papers, no agent has
  a tool that writes, posts or sends data anywhere.
  - Web pages can only be opened from that session's own search results, and never at private
    addresses.
  - Agent prose is stripped of links and HTML before it reaches a PR comment.

Agents run on their own queue in a child process, so they can never block or change a verdict. Design
and sources: [docs/agents.md](docs/agents.md).

## Security

Customers' private code is the most sensitive thing CodeIntent touches, so the design starts there.
Full threat model: [docs/security/threat-model.md](docs/security/threat-model.md). How to report a
vulnerability: [SECURITY.md](SECURITY.md).

| Control | Implementation | Evidence |
| --- | --- | --- |
| Authentic webhooks only | HMAC-SHA256 over the raw body, constant-time compare, duplicate deliveries ignored | `tests/test_github_app.py` |
| No code execution | Static parsing only (LibCST, `ast`, griffe with inspection off); size-capped tarballs extracted with the `data` filter; SHA-256-checked PyPI artifacts | `tests/upgrades/`, `codeintent/upgrades/artifacts.py` |
| Tenant isolation | Every dashboard read is scoped to the installations GitHub says the user can access; unknown and forbidden both return 404; graph queries filter on the installation | `tests/test_dashboard_api.py`, `tests/test_scans.py`, `tests/test_workspace_graph.py` |
| Least-privilege GitHub App | Read: contents, metadata. Write: checks and PR comments only. Short-lived installation tokens, held in memory | `codeintent/github_app.py` |
| MCP tokens | Per workspace, shown once, stored as SHA-256, revocable, last use recorded | `tests/test_mcp_workspaces.py` |
| Web sessions | GitHub OAuth with state and PKCE; signed HttpOnly SameSite cookies; same-origin check on every mutating route | `app/api/` |
| Agent safety | Read-only tools, session-bound web fetches, private-address block, schema and evidence validation, sanitised output | `tests/test_agent.py` |
| No secrets in logs | Failures store and log the exception class only; webhook payloads aren't logged | `tests/test_telegram.py` |
| Supply chain | Exact pins and lock files (`uv.lock`, `package-lock.json`); `pip-audit` and `npm audit` gate CI; Dependabot for pip, npm and Actions with a 7-day cooldown; CI Actions pinned by commit; read-only CI token | `.github/workflows/ci.yml`, `.github/dependabot.yml` |
| Static security analysis | CodeQL `security-extended` on Python, TypeScript and the workflows, on every PR and weekly | `.github/workflows/codeql.yml` |
| Browser hardening | HSTS, `X-Frame-Options: DENY`, `nosniff`, strict referrer and Permissions-Policy headers; no `X-Powered-By` | `next.config.ts` |

## Code quality

- **CI on every push** (`.github/workflows/ci.yml`):
  - Python: `ruff check`, `ruff format --check` and the full `pytest` suite against real PostgreSQL 17
    and Neo4j 5.26 services, plus engine tests on real PyPI releases.
  - Web: Prettier, Next.js production build (which type-checks) and `npm audit --audit-level=high`.
  - Supply chain: `pip-audit` over the locked Python dependencies; CodeQL security analysis
    (`.github/workflows/codeql.yml`); Dependabot updates.
- **218 test cases** (165 run anywhere; 53 need PostgreSQL, Neo4j or the network and run in CI). Graph traversal, tenant isolation, webhook signatures, the agent harness, the
  code map and the PR comment all run against real services rather than mocks where it matters.
- **Typed boundaries:** Pydantic models for engine results, API responses, MCP output schemas and agent
  answers; strict TypeScript on the web.
- **Durable, idempotent jobs:** Procrastinate on PostgreSQL. Webhooks are de-duplicated by delivery
  id. Each scan runs in a child process, which keeps the worker within 512 MB.
- **Measured accuracy** (`artifacts/backtest/latest.json`, 101 labelled real upgrades):
  - 19 real breakages: 14 called `Breaks you` (13 at the exact lines named in the original issue
    reports). The other 5 were `Not checked`, never `No known impact`.
  - 80 harmless upgrades (78 ran): **0 false `Breaks you`**, a 95% upper bound of 4.7%.

## Repository layout

```
codeintent/              Python backend (FastAPI API, worker jobs, engine, graph, agents)
  api.py                 HTTP API: GitHub/Telegram webhooks, dashboard endpoints, /mcp mount
  github_app.py          App JWT, installation tokens, check runs and PR comments
  tasks.py               Procrastinate jobs: PR checks, scans, projection, agents, daily sweeps
  scans.py, codemap.py   default-branch scans; files, imports, functions, calls, tests, entry points
  workspace_graph.py     Neo4j projection and graph queries (reach, blast radius, run graph, rebuild)
  ecosystem.py           shared public package graph
  mcp_server.py          the nine MCP tools, including fix_brief
  telegram.py            alerts and bot commands
  upgrades/              verdict engine: manifests, usage, releases, surface, advisories, verdict, report
  agent/                 agent harness, read-only tools, review agents, security news, prompts
migrations/              numbered PostgreSQL migrations, applied on every release
tests/                   pytest suites (integration tests use real PostgreSQL and Neo4j in CI)
scripts/                 operator CLIs: migrate, worker, verdict, backtest, seed_ecosystem, ...

app/                     Next.js App Router: landing page, dashboard, run pages, docs (MDX)
components/, lib/        React components; typed API client, auth and data loaders
public/                  static assets

docs/                    architecture, agents, MCP, Neo4j, security, operations, deployment
  security/              threat model and remediation log
  history/               original planning documents (not current guidance)
evals/, artifacts/       labelled evaluation sets and their recorded results (backtest, validation)
fixtures/                saved public corpus and example studies used by the demo pages
infra/                   Dockerfiles, Caddyfile and optional Compose overrides (dev, HTTPS, credentials)

compose.yaml             full local stack: web, API, worker, PostgreSQL, Neo4j
heroku.yml, Dockerfile.heroku   production API and worker image (Heroku)
vercel.json              production dashboard (Vercel)
pyproject.toml, uv.lock  Python dependencies (exact pins, locked)
package.json, package-lock.json   web dependencies (locked)
```

## Run it locally

You need Python 3.12, Node 22, `uv` and Docker.

```sh
python3 scripts/generate_env.py          # writes .env with random secrets
docker compose -f compose.yaml -f infra/compose.dev.yaml up -d postgres neo4j
uv sync --locked && npm ci
uv run python -m scripts.migrate
uv run python -m scripts.worker          # terminal 1
uv run uvicorn codeintent.api:app --host 127.0.0.1 --port 8210   # terminal 2
npm run dev                              # terminal 3, http://127.0.0.1:3210
```

The GitHub App flow needs `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET` and the
OAuth client credentials. Agents need Vertex credentials, and security news needs `SERPER_API_KEY`.
Every variable is documented in [.env.example](.env.example).

To try the engine alone, without the App:

```sh
uv run python -m scripts.verdict --repo openai/openai-python@v1.54.4 --package httpx --from 0.27.2 --to 0.28.0
```

To run the checks:

```sh
uv run ruff check codeintent scripts tests && uv run ruff format --check codeintent scripts tests
uv run pytest -q                                        # unit tests
CODEINTENT_RUN_INTEGRATION=1 uv run pytest -q           # + PostgreSQL and Neo4j
npm run check && npm run build
```

Production runs as Heroku web and worker processes, with Vercel for the dashboard, Neo4j Aura, and
Heroku Postgres. See [docs/deployment.md](docs/deployment.md) and [docs/operations.md](docs/operations.md).

## Limits

- **Python only.** Verdicts need a static API reader for each language. The graph model is
  language-neutral, and JavaScript/TypeScript is next.
- **`No known impact` isn't a guarantee.** It means every use was compared in both releases and
  nothing it relies on changed. Runtime behaviour changes are left to the release-notes agent, and
  that agent's output is labelled.
- **A suggested fix needs review.** "CodeIntent re-analysed the edited code and no longer finds this
  break" means the call fits the new API, not that the values are right.
- **Access is per installation, not per repository.** It matches how GitHub scopes Apps (see the
  threat model's residual risks).

## Documentation

[Architecture](docs/architecture.md) · [Agents](docs/agents.md) · [MCP](docs/mcp.md) ·
[Neo4j](docs/neo4j.md) · [Threat model](docs/security/threat-model.md) ·
[Security log](docs/security/remediation-log.md) · [Operations](docs/operations.md) ·
[Deployment](docs/deployment.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

CodeIntent began as a tool for investigating why a codebase took its shape. That feature still runs
at `/investigate`; its design is described in the legacy section of
[docs/architecture.md](docs/architecture.md), and `docs/history/` keeps the early design history.
