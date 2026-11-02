# Open-source reuse map

Source review: 1 November 2026. The decisions below identify reusable capabilities and integration work. They do not claim that these packages have already been installed or tested together.

## Selected foundations

| Upstream | Reuse | Boundary we own |
| --- | --- | --- |
| [CodeGraphContext](https://github.com/CodeGraphContext/CodeGraphContext), MIT | Tree-sitter parsing, symbol/call extraction and resolution where the integration spike succeeds | Index identity, normalized schema, ingestion scope, historical evidence and safe persistence |
| [PyDriller](https://github.com/ishepard/pydriller), Apache-2.0 | Repository/commit traversal and modified-file data | Source selection, explicit PR associations, rename evidence and decision extraction |
| [Neo4j GraphRAG Python](https://github.com/neo4j/neo4j-graphrag-python) | Applicable retrievers and generation interfaces | Scoped query templates, source bundles and our claim-validation contract |
| [Google Gen AI Python SDK](https://github.com/googleapis/python-genai), Apache-2.0 | Authenticated model requests and typed outputs through the account-supported API | Vertex configuration, supported model selection, retries, budgets, evaluation and error semantics |
| [Procrastinate](https://github.com/procrastinate-org/procrastinate), MIT | PostgreSQL task dispatch, workers, retries and locks | Idempotent stage design, cancellation, domain checkpoints and publication of a ready index |
| [shadcn/ui](https://github.com/shadcn-ui/ui), MIT | Accessible composable controls and owned component source | Product tokens, layout, content, full state handling and visual identity |
| [React Flow](https://github.com/xyflow/xyflow), MIT | Focused node/edge interactions | Actual evidence graph data, bounded expansion, readable labels and list alternative |
| [Unslop](https://github.com/heydamir/unslop), CC BY 4.0 | Design direction/review method and applicable token guidance | Original product composition and implementation; retain Damir Sokolovsky credit |

FastAPI/Pydantic, Next.js/React, SQLAlchemy/Alembic, HTTPX, source/diff rendering and browser-test tools use normal package integration. Confirm exact package licences and transitive notices in the implementation lockfile inventory. Font and icon assets receive the same provenance review.

Neo4j GraphRAG Python's [licence notice](https://github.com/neo4j/neo4j-graphrag-python/blob/d9474ea9d750af74efa9089e317d3567cda7885c/LICENSE.txt) states Apache-2.0 generally with marked PSF-licensed portions. This is separate from the Neo4j database software and the terms of the selected Aura service.

## Inspected revisions and seams

These are research anchors. Prefer an appropriate tested release at implementation; if a reviewed commit is required, pin it explicitly and explain why. Never treat a moving branch as a reproducible dependency.

### CodeGraphContext

Reviewed revision: `93c9685bff9151f50a3121e9913e5ba2d27c1191`.

- [TreeSitterParser](https://github.com/CodeGraphContext/CodeGraphContext/blob/93c9685bff9151f50a3121e9913e5ba2d27c1191/src/codegraphcontext/tools/tree_sitter_parser.py) exposes construction by language and a `parse(path, ...)` method.
- [GraphBuilder](https://github.com/CodeGraphContext/CodeGraphContext/blob/93c9685bff9151f50a3121e9913e5ba2d27c1191/src/codegraphcontext/tools/graph_builder.py) delegates to indexing pipelines and contains parsing, resolution and persistence entry points, including `parse_file`, `link_function_calls` and `build_graph_from_path_async`.
- The reviewed [pyproject](https://github.com/CodeGraphContext/CodeGraphContext/blob/93c9685bff9151f50a3121e9913e5ba2d27c1191/pyproject.toml) reports version 0.6.13 and declares several database drivers, constrained parser versions, and broad supporting dependencies. Package metadata and current README versions can differ; use the tested lockfile as the implementation record.
- Configuration supports Neo4j, but this does not establish that upstream writes already satisfy our repository/index isolation, snapshot semantics, or Aura deployment.

**Spike:** extract a small real Python subsystem, verify definitions and selected calls, write normalized revision-scoped output to a disposable Neo4j graph, then run two repository/index fixtures to detect collision. Measure dependency resolution, startup and memory.

**Preferred integration:** a dedicated indexer adapter in an isolated worker environment, preserving useful upstream parsing/resolution while translating output into our canonical graph writer. Parser and indexer internals are not a stable API promise.

**Fallback:** if adapting the resolution/writer boundary is disproportionate, vendor a minimal MIT parser/extractor slice with its licence, upstream revision, modification notes and focused fixture tests, or use Tree-sitter directly behind the identical contract. Keep this decision small; do not begin by maintaining an entire fork.

### PyDriller

Reviewed revision: `9729e010b0a07378e20382dabeda5d5dfb5d40de`.

The [Repository class](https://github.com/ishepard/pydriller/blob/9729e010b0a07378e20382dabeda5d5dfb5d40de/pydriller/repository.py) provides `traverse_commits`. Reuse it for scoped historical extraction after our controlled clone step. Supplement with Git's rename/history/blame capabilities where needed; this library alone does not ingest GitHub reviews or determine design intent.

### Neo4j GraphRAG Python

Reviewed revision: `d9474ea9d750af74efa9089e317d3567cda7885c`.

The [GraphRAG class](https://github.com/neo4j/neo4j-graphrag-python/blob/d9474ea9d750af74efa9089e317d3567cda7885c/src/neo4j_graphrag/generation/graphrag.py) accepts retriever/model interfaces and exposes `search`. Reuse compatible retrieval components instead of creating a competing general-purpose RAG framework. Our typed answer/citation checks remain authoritative; the spike decides whether the high-level generation path fits them or whether we reuse the retrieval layer alone.

### Unslop

Reviewed revision: `1d13095e4bef6ad6c74f1dd828d84c4ba309a4dc`.

Reviewed the [skill](https://github.com/heydamir/unslop/blob/1d13095e4bef6ad6c74f1dd828d84c4ba309a4dc/skills/unslop/SKILL.md) and [tokens](https://github.com/heydamir/unslop/blob/1d13095e4bef6ad6c74f1dd828d84c4ba309a4dc/skills/unslop/references/tokens.md). It prescribes product-derived direction and successive visual passes. It does not supply a React app, component library, graph backend or evidence engine. No global skill installation has been performed.

## Alternatives retained, not combined by default

- [LightRAG](https://github.com/HKUDS/LightRAG), MIT: strong alternative if the retrieval spike identifies a specific missing capability. Adding it alongside another complete ingestion/retrieval framework requires a demonstrated benefit and explicit schema/ownership boundaries.
- [DeepWiki Open](https://github.com/AsyncFuncAI/deepwiki-open), MIT: useful product/reference patterns, but the planned investigation interface and evidence contract differ from a repository wiki. Adopt individual suitable code only after inspecting its current implementation and provenance.
- [Microsoft GraphRAG](https://github.com/microsoft/graphrag), MIT: a candidate for a comparative retrieval experiment; it is not automatically another production service.
- [GitNexus](https://github.com/abhigyanpatwari/GitNexus): current [PolyForm Noncommercial licence](https://github.com/abhigyanpatwari/GitNexus/blob/main/LICENSE) is a material difference from the selected permissive foundations. Keep it as a reference unless appropriate reuse rights are established.

## Reuse inventory required during implementation

For each dependency or vendored file, record upstream URL, release/commit, licence/notice location, exact reused capability, local modifications, integration tests and update strategy. Keep third-party material visibly distinct from our product's original work. Retain required source headers and attribution.

The application licence, distribution notices and hackathon disclosure of reused material are reviewed against the actual final dependency inventory and event rules before submission. This source review does not establish submission eligibility or reopen the deadline.
