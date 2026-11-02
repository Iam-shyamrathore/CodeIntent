# Third-party components and public source material

Code Intent uses upstream packages through their APIs. Their notices and licences remain in the installed distributions; the lockfiles identify exact versions. No GitNexus code is included.

| Component | Use | Licence / source |
| --- | --- | --- |
| Next.js, React | Web application | MIT |
| Radix Dialog and Tabs | Accessible interaction primitives | MIT |
| React Flow / xyflow | Interactive evidence neighbourhood | MIT |
| FastAPI, Pydantic | HTTP and typed evidence contracts | MIT |
| Procrastinate | PostgreSQL queue, locks, retries, worker liveness | MIT |
| Psycopg | PostgreSQL driver | LGPL-3.0; packaged separately, unmodified |
| Neo4j GraphRAG Python | Official hybrid retrieval and embedder extension | Apache-2.0; marked PSF portions |
| Google Gen AI SDK | Vertex structured generation and embeddings | Apache-2.0 |
| Tree-sitter | Syntax parsing without executing target code | MIT |
| tree-sitter-language-pack | Pinned language loading; individual grammar notices retained | MIT / Apache-2.0; individual grammars vary |
| PyDriller | Initial historical demonstration commit collection; reproduction script | Apache-2.0 |
| CodeGraphContext | Original isolated parser feasibility study; optional reproduction environment | MIT; not imported into the production API |
| IBM Plex Sans / Mono | Self-hosted fonts | SIL OFL-1.1 |
| Lucide | Interface icons | ISC |
| PostgreSQL / Neo4j Community | Ledger and graph services | PostgreSQL Licence / GPL-3.0, separate container distributions |
| Caddy | Optional HTTPS proxy | Apache-2.0 |

Design process: [Unslop](https://github.com/heydamir/unslop) by **Damir Sokolovsky**, CC BY 4.0, revision `1d13095e4bef6ad6c74f1dd828d84c4ba309a4dc`. The visual direction and product implementation are original. Unslop is used as design guidance; it is not an application runtime dependency.

The shipped HTTPX demonstration source snapshots are attributed individually by original GitHub URL, author and date. HTTPX source code is BSD-3-Clause; the complete notice is in [docs/licenses/HTTPX-BSD-3-Clause.md](docs/licenses/HTTPX-BSD-3-Clause.md). Public discussion passages retain their source attribution; no endorsement by contributors is implied. Answer fixtures are explicitly saved model outputs, not simulated live calls.

Production imports use the direct Tree-sitter adapter rather than the broad CodeGraphContext runtime. Historical source collection is available in `scripts/collect_sources.py`; general imports use bounded GitHub API collection. These boundaries are deliberate and should not be described as wholesale reuse of those repositories.
