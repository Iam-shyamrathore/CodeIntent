# Feasibility report: first working slice

Date: 1 November 2026. Scope: Gate A investigation feasibility and Gate B initial screen studies, not the full release.

## Outcome

A real public-source collection now reaches an actual Neo4j graph, official hybrid GraphRAG retrieval, Vertex generation, exact source-span binding and a working local web interface. The interface includes the landing, investigation, source drawer, sources/relationship views, coverage information and credits.

The public-facing prepared reports are saved real model results. Free-form follow-ups call the backend. The collection remains explicitly limited to selected HTTPX cases.

## Verified engineering results

| Check | Observed result |
| --- | --- |
| Git/GitHub collection | 50 source documents; four PRs and two issues with selected-endpoint pagination, comments, reviews and diffs; one rationale comment; two current code files |
| Git history reuse | PyDriller traversed four actual merge commits |
| Code-indexer reuse | CodeGraphContext 0.6.13 parsed two files: 133 functions, nine classes, 363 call sites |
| Parser isolation | Separate 87-package indexer environment; API/model dependencies in their own environment |
| Graph projection | 194 nodes and 195 input relationship rows in the scoped index |
| Repeat projection | Node count remained stable after repeated import; relationships use deterministic merge keys |
| Isolation | Two populated scopes exercised; sentinel content from the second scope did not appear in the first; no cross-scope relationships found |
| Vertex structured output | Passed through the authorized APCAN Vertex API-key configuration |
| Vertex embeddings | 768 dimensions; 50 source vectors created; batch embedding run approximately 3.55 seconds |
| Retrieval reuse | Official `HybridCypherRetriever` combines lexical/vector seeds with a bounded source-relationship query |
| Actual answer runs | RawURL case: partial support, five claims, one explicit gap, 4.44 seconds; app-deprecation case: supported, five claims, 3.95 seconds; missing-rationale case: insufficient, zero claims, 2.15 seconds |
| HTTP proxy path | Same-origin browser-facing request returned 200 with a supported live answer, approximately 4.03 seconds; unrelated Origin returned 403 |
| Contract checks | Six meaningful tests passed |
| Frontend | TypeScript and production build passed |
| Browser journey | A new live question completed in the production-built browser; source and relationship tabs, original review drawer, index coverage and saved evidence-gap entry verified |
| Responsive checks | Landing page width matched the viewport at 360, 768, 1280 and 1440 px; mobile workbench/document/main widths matched at 360 px; browser sizing restored afterwards |
| Secret inventory check | No configured provider API key or private-key material found among the 44 candidate version-controlled files checked |

These timings are individual local observations, not p95 benchmarks, capacity claims or guaranteed latency. No financial cost claim is established.

HTTPX source revision: `b5addb64f0161ff6bfe94c124ef76f6a1fba5254`.

Selected index identity: `857781993dea900e6526bd63`. Source content hashes and retrieval timestamps are retained in the source ledger and attached to the saved report fixtures.

## Decisions established by the spike

### CodeGraphContext is reusable, with isolation

Its released Python parser works against real HTTPX files. Use an adapter and a separately locked environment. The installed release brought broad database dependencies even though this spike only used its parser; keeping that environment out of the API was worthwhile.

The language pack was pinned to 1.20.0 for the tested environment. The first grammar initialization took about 41 seconds; an initialized parsing run for the two files took about 0.041 seconds. This does not establish full-repository throughput.

Call sites were extracted, but inter-file call resolution and CALLS-edge projection have not been verified in this slice. The graph currently contains source relationships and file/symbol containment.

### Citation selection should use pre-addressed passages

The first attempt asked the model to reproduce quotations exactly. A mismatch was caught and the answer rejected. The revised contract assigns passage IDs before generation. The model selects IDs; the server binds original source text and offsets and validates source membership.

This removes quotation-reproduction errors from the model's responsibility. It does not eliminate unsupported interpretation, which still needs semantic evaluation and labelled cases.

### Use the working Vertex route explicitly

The initially discovered service-account keys were rejected by Google. APCAN's configuration uses Vertex API-key authentication and passed actual generation and embedding calls. The application stores a reference to that local environment file, not a copy of its key.

Runtime credential files, raw working data and database configuration are ignored by Git. No provider switch or account modification was needed.

### Keep the two databases' intended roles distinct

Neo4j is exercised here. The canonical source ledger in this spike is local JSON. PostgreSQL persistence, Procrastinate jobs, checkpoints/outbox and migrations remain part of the next implementation gate; they have not been substituted with a claim of production durability.

## Design study

The selected light silver / ink / cobalt palette is implemented. The landing uses the actual RawURL sequence as its central interaction. The workbench emphasizes the question and answer and opens source detail on demand. Its source and connection tabs display real retrieved data.

The initial browser pass exposed an Origin mismatch in the frontend proxy; it was fixed and the live proxy request verified. A browser extension added `cz-shortcut-listen` to the body and triggered a development hydration warning. This was identified as an external attribute mutation; application rendering was not changed to accommodate that extension.

Visual/browser evidence is saved under `artifacts/screenshots/`: desktop landing, desktop workbench, source inspector and mobile landing/workbench. Browser control briefly required reconnecting through the selected browser's direct documented APIs. A 360 px pass led to larger small labels and a deliberate two-line landing heading. This is a targeted responsive/interaction pass; complete keyboard, accessibility, and the full state matrix remain release work.

## Runtime

- Frontend: Next.js 16.4.3, production-build preview on loopback port 3211.
- API: FastAPI, loopback port 8210, two concurrent investigations maximum in this local slice.
- Graph: Neo4j 5.26 Community in an isolated `codeintent` Colima profile; loopback Bolt 7692 and browser 7482.
- Tested container digest: `sha256:249a1ec6e3c52d82101a5ed33d6ed2b5ed5b0017b21a28c0bfebc335e87fb177`.
- Docker's original global context is `default` and was restored after Colima initialization.
- Python 3.12; package resolutions stored in `uv.lock` and `requirements-indexer.lock`; frontend resolution in `package-lock.json`.

No hosted deployment or Aura integration has been verified.

## Remaining work before release

1. Replace local JSON and synchronous request orchestration with the planned durable ledger, background imports and resumable publication.
2. Build and evaluate decision extraction, aliases, and scoped temporal relationships. The current model can reason over retrieved historical evidence; that is not yet a validated temporal decision engine.
3. Expand from the selected source cases to a declared substantial subsystem/history range; prove GitHub pagination and partial-failure recovery at that scale.
4. Add the 30-question development/held-out benchmark, source-support review and fair text-only retrieval ablation.
5. Complete source-view refinements, responsive/keyboard review and the full product state set.
6. Establish provider load behaviour, actual usage accounting, query cancellation and operational limits.
7. Verify Aura, hosted workers, migrations, authentication/authorization, quotas, backup/rebuild and deployment independently.

The next gate is a durable, evaluated investigation pipeline with a refined interface. The application is ready to inspect locally, with its present scope and limits visible.
