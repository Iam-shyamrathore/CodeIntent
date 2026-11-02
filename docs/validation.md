# Local release validation · 2 November 2026

This report distinguishes a deployable local release from a public deployment. No public domain, hosted provider deployment or remote CI run is claimed.

## Completed checks

| Check | Observed result |
| --- | --- |
| Python suite with real PostgreSQL / Neo4j integration | **44 passed** |
| Ruff and Python formatting | passed |
| TypeScript and Prettier | passed |
| Next.js production build | passed, including container build |
| API / worker / web container images | built and booted in Compose |
| PostgreSQL / Neo4j / API / web health | healthy; authenticated readiness returned 200 |
| Fresh public GitHub import through browser UI | `pallets/itsdangerous`, PR 442, 11 captured sources, published ready |
| Initial public demo pipeline | HTTPX, 50 captured sources, published ready |
| Real Vertex through production web/API/graph stack | supported app-deprecation investigation, 8.64 seconds, persisted report |
| Saved public report without operator session | readable, exact citations and all returned source hashes verified |
| Unauthorized import / foreign-origin POST | 403 / 403 |
| Optional Caddy configuration | validated with the official image and network disabled; no certificate issued |

The SQL integration tests use disposable schemas and scoped graph fixtures. They exercise transactional enqueue rollback, migration replay, quota persistence, idempotent projection, cross-index isolation, checkpoint recovery after a simulated graph failure, and requeueing after a worker record disappears. That last case covers the queue's ON DELETE SET NULL behavior; it does not rely on an arbitrary job-duration timeout.

The test client currently emits one upstream Starlette/httpx deprecation warning. Tests pass. Runtime HTTP calls use the pinned client version; no test-only SDK migration was mixed into this release.

## Thirty-question regression run

The checked-in [questions](../evals/questions.json) cover recorded rationale, temporal changes, missing evidence, entity ambiguity and misleading premises. The generation policy is `evidence-v3`; all questions use real Vertex generation/embeddings and the same captured public corpus. Source IDs and complete per-case results are in [latest.json](../artifacts/evaluation/latest.json); aggregate values are in [summary.json](../artifacts/evaluation/summary.json).

- **30/30** results passed exact source-membership, quote/offset and answer-state checks.
- **7/7** deliberately unsupported prompts produced insufficient answers with zero claims. This includes the instruction to invent a ticketing rationale.
- There were no unhandled case failures in the completed run. The bounded invalid-reference repair was separately tested.
- Observed native-run latency: median **4.12 s**, empirical p95 **6.10 s**, maximum **6.78 s** across 30 questions with two evaluation threads. These measure the investigation function, not internet delivery or production capacity. The separate container/browser call took **8.64 s**.
- Both hybrid retrieval without graph expansion and graph retrieval recovered the labelled essential source set for **23/23** source-bearing cases. The small corpus does **not** demonstrate an aggregate recall advantage for graph retrieval. Graph expansion changed context in all 30 prompts and added concrete discussion/diff passages used in some answers.
- Baseline: 14 hybrid results. Graph path: 4 hybrid seeds expanded to at most 14 sources over bounded evidence edges. Source-count caps match; context tokens are not claimed to be perfectly equal.

The original development/held-out labels remain in the dataset for provenance, but every case was exercised during development. This is regression evidence, not an untouched held-out study. Exact citations and a second model review do not establish human-rated semantic accuracy. No 90% human-support score or broad generalization claim is made. Two additional questions about current ownership and a universal latest-comment rule were appropriately answered with insufficient evidence rather than asserted as project facts.

The evaluator used immutable snapshot `6e38e780fb16896fe97f66c9`. The runtime demo uses manifest `e0a117e910da9496a5f27678`, which adds model/policy identity to manifest hashing over the same captured documents. Verification compares the canonical source hash maps, rather than treating differing manifest-version identifiers as different source content.

## Browser / visual pass

Checked at CSS widths **360, 768, 1280 and 1440 px**: landing and saved report layouts matched viewport width without horizontal overflow. Desktop and mobile screenshots are saved locally under `artifacts/screenshots/` (excluded from Git).

Exercised real pointer/keyboard interactions for operator sign-in, public repository import, cancellation, retry-to-ready and progress, sidebar collapse, a live investigation, Sources/Timeline/Connections tabs, graph zoom/fit, keyboard graph-source opening, exact evidence/context expansion, Escape dismissal and focus restoration, index details, clipboard answer/share links, JSON download and permanent report navigation. Tab arrow-key navigation selected the next tab. New reports retain a saved label when reopened.

This is a targeted Chromium-based review. It is not a full WCAG certification, cross-browser/device lab, screen-reader audit or production load test. Reduced-motion styles and accessible Radix primitives are present; those broader checks remain separate from the observed local proof.

## Local infrastructure recovery

The clean-stack test initially collided with prototype volume names. The conflicting processes were stopped; the Compose volumes were separated into explicit `*_ledger_v1` and `*_graph_v1` names. The native source ledger and saved report were preserved before the disposable native test database was rebuilt.

A later image rebuild exhausted temporary host storage and caused I/O errors in the isolated Colima test engine. The engine was stopped/restarted, only agent-created obsolete build resources were removed, and unused disk blocks were reclaimed. The final images rebuilt successfully, database health and persisted reports were rechecked, and a complete evaluation run was resumed against its unchanged source snapshot. No application source/data from APCAN was modified; its existing provider configuration was mounted read-only for tests.

## Remaining deployment work

Supply runtime secrets/provider configuration, choose hosting/DNS, deploy the provided images/Compose configuration and verify the public origin. A managed Neo4j tier must support the selected full-text/vector indexes and queries; local Community testing does not prove an untested tier. Private repositories, tenant accounts, whole-program call resolution and complete repository history are outside this release's stated scope.
