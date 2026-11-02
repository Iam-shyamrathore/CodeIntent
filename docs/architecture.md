# Architecture and evidence contract

```mermaid
flowchart LR
  Browser --> Web[Next.js]
  Web --> API[FastAPI]
  API --> PG[(PostgreSQL ledger / reports / quotas)]
  API --> Queue[Procrastinate transaction]
  Queue --> Worker
  Worker --> GitHub[Public GitHub API]
  Worker --> Parser[Tree-sitter]
  Worker --> PG
  Worker --> Graph[(Neo4j scoped projection)]
  Worker --> Vertex
  API --> Retrieval[Hybrid seeds / bounded graph traversal]
  Retrieval --> Graph
  Retrieval --> Vertex
  API --> Checks[Exact citations / independent support review]
  Checks --> PG
```

## Ownership

PostgreSQL owns immutable repository snapshots, collection coverage, source hashes, imported decisions, stage checkpoints, reports, usage counters and job state. A corpus is stored as bounded JSONB inside an immutable index row. Neo4j is a projection, not the sole copy of evidence. There is no cross-database transaction: a pending ledger record is written first, the graph is projected, then a PostgreSQL transaction publishes the index. Failed graph writes never move the repository's ready pointer.

Queue submission and the import ledger row use the same PostgreSQL transaction through Procrastinate's external connection interface. This removes the enqueue/outbox gap. Repository locks serialize competing workers, while an active-import unique index and advisory lock make duplicate submissions idempotent.

An index manifest includes repository/revision, full captured source records and provenance, deterministic links, coverage, parser policy, model identities and decision policy. Equal symbol names in different files/revisions do not establish identity. Explicit GitHub rename metadata creates file lineage; only uniquely resolved calls in the same file get CALLS edges. This is deliberately narrower than whole-program type resolution.

## Retrieval

Each immutable graph scope has separate full-text and 768-dimensional vector indexes, preventing other repositories from consuming its nearest-neighbour slots. The official Neo4j HybridCypherRetriever selects hybrid seeds, then parameterized Cypher follows an allowlist of evidence relationships for up to two hops. All nodes and relationships on a path must belong to the same index. Authorship alone does not expand the evidence neighbourhood.

The graph path uses four hybrid seeds and up to 14 evidence sources. The comparison baseline uses up to 14 hybrid results without expansion. Both cap source count at 14 before timeline evidence is attached. Exact context sizes and retrieved IDs are available in evaluation output; these are bounded retrieval observations, not proof of universal graph superiority.

User text is tokenized into literal Lucene terms while its original text supplies the embedding and the question. Neither user nor model output becomes arbitrary Cypher or a shell command. Repository code is parsed as data, never installed, imported or executed.

## Answers

Captured source text is partitioned into short addressable spans before generation. The model returns span IDs; the server binds original text and offsets. It verifies bundle membership, matching original characters and evidence-state invariants. One bounded repair is permitted for malformed references. A separate Vertex support review then removes claims whose cited passage/context does not support the complete claim. A failed review withholds the answer.

This checks provenance and provides a second semantic filter; it remains fallible. Inference is explicitly labelled. Partial support includes unknowns, and an insufficient answer cannot assert claims. Current behavior cannot be established by a historical comment alone. Source timestamps, merge outcomes, captured times, indexed revision and report generation time remain distinct.

Validated results are persisted with model/policy/index identity. Permanent report URLs and JSON exports refer to that stored result. New questions from an archived report remain scoped to its displayed index rather than silently moving to a newer revision.

## Decision history

Model-extracted decisions require exact passages from the relevant PR or its children and a literal subject present in cited text. Outcome is derived from captured merge metadata. A qualified replacement needs the same subject/aspect, overlapping changed paths, a later merged change and explicit replacement language; it stays labelled as inferred.

A separate deterministic path identifies unique declaration deletions/additions from merged diffs on the same exact file/symbol. A later declaration restoration can replace that declaration-presence aspect. It does not prove public export, implementation equivalence or a complete rollback. The HTTPX fixture exercises this distinction for `httpx/_urls.py::raw`.

## Trust boundary

This is one public workspace. Imports require a signed, expiring operator session; the server forwards an operator secret only after validating it. API routes also require the separate web-to-API service secret. Origin checks protect state-changing browser requests. All imported repositories must be public github.com repositories; arbitrary hosts and private repositories are rejected. Public reports contain public source data.

Private repositories, GitHub OAuth, tenant accounts, complete historical call graphs, calibrated confidence scores, automatic code modifications and arbitrary external-tool execution are outside this release.
