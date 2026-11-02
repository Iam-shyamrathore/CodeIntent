# Deployment

The supported portable target is Docker Compose on a VM, or the same web/API/worker images with managed PostgreSQL and Neo4j. Heroku (API and worker), Vercel (Next.js), Supabase (PostgreSQL session pooler) and Neo4j Aura are also supported with the checked-in platform configuration.

## Service map

| Service | Image / build | Port | Process |
| --- | --- | --- | --- |
| Web | `infra/Dockerfile.web` | 3000, public ingress | Next.js standalone server |
| API | `infra/Dockerfile.api` | 8210, internal | schema migration then Uvicorn |
| Worker | same API image | no ingress | seed demo then Procrastinate worker |
| PostgreSQL | `postgres:17-alpine` | 5432, internal | canonical ledger, reports, queue |
| Neo4j | `neo4j:5.26-community` | Bolt 7687, internal | rebuildable scoped evidence projection |
| Caddy, optional | `compose.https.yaml` | 80/443 | TLS termination and web reverse proxy |

The exact application packages are locked in `package-lock.json`, `uv.lock` and `requirements.txt`. Database base images use the declared maintenance tags; record the resolved digests when promoting a release. Do not reuse another running database's volume. This project uses separate `*_ledger_v1` and `*_graph_v1` volumes; changing `COMPOSE_PROJECT_NAME` isolates an additional stack.

## Required environment

| Variable | Services | Value |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | Compose database/API/worker | generated random hex; Compose constructs the DSN |
| `DATABASE_URL` | native/managed API/worker | PostgreSQL URL, including required SSL options for your provider |
| `NEO4J_URI` | API/worker | `bolt://neo4j:7687` locally, or your provider's `neo4j+s://…` URI |
| `NEO4J_USERNAME` | API/worker | normally `neo4j` |
| `NEO4J_PASSWORD` | API/worker/Compose graph | database password |
| `CODEINTENT_API_SECRET` | web/API | identical random secret, at least 32 characters |
| `CODEINTENT_OPERATOR_TOKEN` | web/API | identical random secret, at least 32 characters; entered only by the operator |
| `CODEINTENT_SESSION_SECRET` | web | random secret, at least 32 characters |
| `CODEINTENT_API_URL` | web | private API base URL, no trailing slash |
| `CODEINTENT_PUBLIC_URL` | web | exact public HTTPS origin; enables Secure cookies and proxy-origin validation |
| `GOOGLE_API_KEY` | API/worker, Express mode | Vertex Express Mode API key; a generic non-Vertex key is not interchangeable |
| `GOOGLE_CLOUD_PROJECT` | API/worker, ADC/file mode | enabled Vertex project |
| `GOOGLE_CLOUD_LOCATION` | API/worker | validated default `global` |
| `VERTEX_GENERATION_MODEL` | API/worker | validated default `gemini-2.5-flash` |
| `VERTEX_EMBEDDING_MODEL` | API/worker | validated default `gemini-embedding-001`, 768 dimensions |
| `GITHUB_TOKEN` | worker | recommended public-read token; collector rejects private repositories |
| `CODEINTENT_ENV` | API/worker | `production` |

`CODEINTENT_QUESTIONS_PER_DAY` defaults to 30 per hashed client address; `CODEINTENT_GLOBAL_QUESTIONS_PER_DAY` defaults to 300 uncached questions across the deployment; `CODEINTENT_IMPORTS_PER_DAY` defaults to 20. The global limits are persisted in PostgreSQL. Put the web service behind a trusted ingress that supplies `X-Forwarded-For`; the global cap still applies if client-address attribution is unavailable.

There are no `NEXT_PUBLIC_*` secrets. API and worker need no browser credentials. Source snapshots and model requests remain server-side, apart from the public evidence/report data intentionally returned to visitors.

## Vertex identity alternatives

1. **Express Mode:** set `GOOGLE_API_KEY`; all other credential mechanisms can remain empty.
2. **Attached Google Cloud identity / ADC:** leave the key and file settings empty, set project and location, and grant the runtime identity the Vertex permissions appropriate to that project. Runtime SDK calls use ADC; this does not silently switch provider.
3. **Service-account JSON:** set an absolute host path in `GOOGLE_APPLICATION_CREDENTIALS` and combine `compose.credentials.yaml` with the base Compose file. Both Python services receive the file as a read-only mount at `/run/vertex.json`. Ensure UID 10001 can read the mount through your secret mechanism. Do not add the JSON to the build context.

```sh
docker compose -f compose.yaml -f compose.credentials.yaml up -d --build
```

For local development only, `CODEINTENT_VERTEX_ENV_FILE` can reference an existing external `.env` containing `GOOGLE_API_KEY` and explicit `GOOGLE_GENAI_USE_VERTEX=true`. It is not a portable host path inside a container; use the production methods above.

A failed provider request never falls back to another account/provider. Changing models requires refreshing the index; model identity contributes to new index manifests. Previously saved reports retain their model and snapshot.

## First boot and health

API startup applies numbered SQL migrations under a PostgreSQL advisory lock. Worker startup idempotently queues the shipped HTTPX demo. A ready index is published only after parsing, decisions, graph projection, embeddings and count checks finish. Saved example pages are usable while that first import runs.

```sh
docker compose ps
docker compose logs --tail=100 api worker
```

`/health` checks API process liveness. `/ready` checks PostgreSQL and Neo4j and requires the service key. The web proxy exposes the authenticated readiness check at `/api/service/ready`. Repositories shows queue stages and actual worker liveness. Vertex readiness is demonstrated by a real investigation, not inferred from database health.

## HTTPS on a VM

Set `CODEINTENT_DOMAIN=code.example.com` and `CODEINTENT_PUBLIC_URL=https://code.example.com`, configure DNS, allow ports 80 and 443, and use the HTTPS Compose override. Caddy routes only to the web service; its persistent volumes retain certificates. This uses Caddy's documented [automatic HTTPS](https://caddyserver.com/docs/automatic-https) and [reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) behavior. Certificate issuance is verified after actual public deployment; no public certificate was issued during local validation.

With a hosting platform that already terminates TLS, deploy the standalone web image behind that ingress instead. Keep the API on the private network and configure its private URL in the web environment. The long-running worker is a separate process, not a serverless request.

## Promotion checklist

Build images from the intended commit, preserve database volumes/backups, supply secrets at runtime, verify all service health checks, observe a ready demo index, sign in and import one public repository, then run a fresh question and open its saved link in a separate browser session. Confirm your provider's Neo4j tier supports the configured full-text/vector indexes and bounded traversal. Local Community proof does not establish an untested managed tier's compatibility.


## Heroku + Vercel

The root `Dockerfile.heroku` builds the backend on Heroku; `heroku.yml` applies SQL migrations and idempotently queues the demo during release. Web and worker use the same image. No local Docker build is required.

1. Create a container-stack Heroku app and configure runtime secrets: `DATABASE_URL` (Supabase **session** pooler on port 5432, with `sslmode=require`), `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, optional `NEO4J_DATABASE`, `GOOGLE_API_KEY`, `CODEINTENT_API_SECRET`, `CODEINTENT_OPERATOR_TOKEN`, `CODEINTENT_ENV=production`, and `CODEINTENT_ASYNC_QUESTIONS=1`. Set secrets through the platform settings or a protected secret file, never commit them.
2. Push the release and start both processes:

```sh
heroku git:remote --app YOUR_API_APP
git push heroku HEAD:main
heroku ps:scale web=1:basic worker=1:basic --app YOUR_API_APP
```

3. Link the frontend using `vercel link`. Add production variables with `vercel env add NAME production`: `CODEINTENT_API_URL` (Heroku HTTPS origin), the matching `CODEINTENT_API_SECRET` and `CODEINTENT_OPERATOR_TOKEN`, a separate `CODEINTENT_SESSION_SECRET`, and `CODEINTENT_PUBLIC_URL` (Vercel production origin). Then run `vercel --prod`. `.vercelignore` excludes local credentials, Python services, corpus, and runtime state; saved study fixtures remain in the deployment.
4. Check `/api/service/ready`, observe an online worker and a ready HTTPX index in Repositories, submit an uncached question, and reopen its saved report. Saved examples alone are not proof of cloud provider readiness.

On Heroku, uncached questions return `202` with a durable job ID. The browser polls `/api/service/questions/{id}` for queued/running/retrying/ready/failed state. Reports persist after a browser disconnect. The worker runs two tasks concurrently and gives investigations higher priority than waiting imports. A worker heartbeat recovers orphaned import and investigation tasks after a process loss.

Migration 004 enables RLS and revokes Data API role privileges on the app ledger and Procrastinate objects only. The backend connects as the database owner; no Supabase browser key is required. New migrations introducing app tables/functions must preserve this boundary.

Use the operator token from your private environment file to sign in at Repositories. Vercel never receives PostgreSQL, Neo4j or Vertex credentials. GitHub imports work anonymously within GitHub's rate limits; set a public-read `GITHUB_TOKEN` on Heroku for sustained use.
