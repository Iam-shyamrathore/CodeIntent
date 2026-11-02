import json
import time
from pathlib import Path

from codeintent.graph import EvidenceRetriever, driver, index_id, project

root = Path(__file__).resolve().parents[1]
corpus = json.loads((root / ".data/corpus.json").read_text())
parsed = json.loads((root / ".data/parsed-code.json").read_text())
started = time.perf_counter()
stats = project(corpus, parsed)
# The same input is imported twice: counts must remain stable.
again = project(corpus, parsed)
assert stats["nodes"] == again["nodes"]
with driver() as db:
    result = EvidenceRetriever(db).search(
        query_text="Why was RawURL removed and then restored?", scope=index_id(corpus)
    )
    other = EvidenceRetriever(db).search(query_text="RawURL", scope="unrelated-index")
    assert not other.items
    stats.update(
        {
            "seconds": round(time.perf_counter() - started, 3),
            "retrieved_sources": len(result.items),
            "retrieved_paths": len(result.metadata["paths"]),
            "idempotency_passed": True,
            "scope_filter_passed": True,
        }
    )
    assert result.items
(root / ".data/graph-check.json").write_text(json.dumps(stats, indent=2))
print(json.dumps(stats, indent=2))
