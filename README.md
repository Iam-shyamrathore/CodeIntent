# Code Intent

Understand why a codebase took its current shape. Investigate public GitHub code, pull requests, review discussions, issues and commits through dated, individually cited explanations.

A complete portable web application: Next.js interface, FastAPI service, Procrastinate worker, PostgreSQL source ledger and Neo4j evidence graph. Vertex powers embeddings, structured answers and a separate support review. Public examples are saved investigations; new questions use the running backend.

## Deploy

Requires Docker with Compose and Python 3 for the configuration helper.

```sh
python3 scripts/generate_env.py
```

Edit `.env`:

- Set `GOOGLE_API_KEY` to a **Vertex Express Mode** key, or use the identity/file alternatives in [deployment.md](docs/deployment.md).
- Set `GITHUB_TOKEN` for reliable public GitHub collection. Without it, GitHub's anonymous request limit can interrupt larger imports.
- Set `CODEINTENT_PUBLIC_URL` to your public HTTPS origin. The generated database/service/session/operator secrets can stay as generated.

```sh
docker compose up -d --build
```

Open [http://localhost:3000](http://localhost:3000). The worker automatically queues the bundled public HTTPX corpus; follow its progress under **Repositories**. Existing saved examples open immediately. Use **Workspace access** and the `CODEINTENT_OPERATOR_TOKEN` value from your own environment to import repositories.

For a VM with a domain and bundled HTTPS, set `CODEINTENT_DOMAIN` and `CODEINTENT_PUBLIC_URL=https://your-domain`, point DNS at that VM, and run:

```sh
docker compose -f compose.yaml -f compose.https.yaml up -d --build
```

The web port binds to loopback by default. API, PostgreSQL and Neo4j have no published ports. For managed container hosting, route public traffic to the web service on port 3000 and use the service/environment map in [deployment.md](docs/deployment.md).

## What works

- Minimal silver/ink/cobalt landing page and responsive investigation workspace.
- Operator-authorized public GitHub imports, real progress/event history, cancellation, automatic retries and checkpoint recovery.
- Immutable source snapshots, hashes, dates, authors and revision identity in PostgreSQL. A failed refresh preserves the previous ready index.
- Python, JavaScript/TypeScript, Go, Rust and Java syntax extraction with Tree-sitter. Local unambiguous calls and explicitly recorded file renames are projected into the graph.
- Scoped lexical/vector retrieval plus bounded evidence traversal. No arbitrary model-generated Cypher or repository code execution.
- Exact passage/offset checks, one bounded repair of malformed citations, and separate claim support review. Unsupported explanations are withheld.
- Dated decision assertions, merged versus proposed changes, and conservative replacements limited to a verified aspect. A matching name or newer date never establishes whole-API equivalence.
- Evidence drawer with captured context and source links; timeline; interactive graph with equivalent relationship list; copy, JSON export and saved public report links.
- Signed operator sessions, origin checks, service authentication, persistent daily quotas, concurrency limits, health/readiness, schema migrations and CI.

## Scope

Imports are deliberately bounded: at most 30 selected PRs (12 recent closed PRs by default), 10 linked issues, 200 comments/reviews per endpoint, 100 changed files per PR and 40 current source files. Sources are limited to 24,000 captured characters each; model passage windows are smaller. Omissions are recorded. GitHub PR patches and commit metadata provide change evidence; the application does not claim a complete clone/history or whole-program type resolution.

Only public repositories are supported. Anyone using this deployment can inspect imported public evidence and saved reports. This release is a single public workspace with an operator key; it does not offer private repositories or tenant accounts.

Model support review is fallible. The interface distinguishes recorded facts, inference, conflicts, partial answers and missing evidence. Neither a graph edge nor an exact quotation is a calibrated truth score.

## Develop and validate

Python 3.12, Node 22 and `uv` are used for native development. The generated `.env` includes native loopback addresses and the matching database password. Start the database-only development configuration, then:

```sh
docker compose -f compose.yaml -f compose.dev.yaml up -d postgres neo4j
uv sync --locked
npm ci
uv run python -m scripts.migrate
uv run python -m scripts.seed
uv run python -m scripts.worker
```

In separate terminals:

```sh
uv run uvicorn codeintent.api:app --host 127.0.0.1 --port 8210
npm run dev
```

```sh
uv run pytest -q
CODEINTENT_RUN_INTEGRATION=1 uv run pytest -q
npm run build
uv run python -m scripts.evaluate --answers
```

The integration suite uses a disposable PostgreSQL schema and explicitly scoped synthetic graph nodes. The evaluation runs 30 labelled cases plus a retrieval ablation; it makes real Vertex calls. Results and measured limits are in [validation.md](docs/validation.md).

See [operations.md](docs/operations.md), [architecture.md](docs/architecture.md), and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The initial design and feasibility history is retained in `planning/`; it is not the current deployment guide.
