import json
import time
from pathlib import Path

from codeintent.domain import scoped_id
from codeintent.graph import driver, index_id
from codeintent.vertex import client

root = Path(__file__).resolve().parents[1]
corpus = json.loads((root / ".data/corpus.json").read_text())
scope = index_id(corpus)
started = time.perf_counter()
rows = []
with client() as model:
    for offset in range(0, len(corpus["documents"]), 10):
        docs = corpus["documents"][offset : offset + 10]
        response = model.models.embed_content(
            model="gemini-embedding-001",
            contents=[s["title"] + "\n" + s["body"][:12000] for s in docs],
            config={"output_dimensionality": 768, "task_type": "RETRIEVAL_DOCUMENT"},
        )
        if len(response.embeddings) != len(docs):
            raise ValueError("Embedding count mismatch")
        for source, embedding in zip(docs, response.embeddings, strict=True):
            if len(embedding.values) != 768:
                raise ValueError("Embedding dimension mismatch")
            rows.append(
                {
                    "uid": scoped_id(
                        corpus["repository_id"], scope, "entity", source["id"]
                    ),
                    "embedding": embedding.values,
                }
            )
with driver() as db:
    db.execute_query(
        "UNWIND $rows AS row MATCH (n:CIEntity {uid:row.uid}) SET n.embedding=row.embedding",
        rows=rows,
    )
    db.execute_query("""CREATE VECTOR INDEX ci_source_vector IF NOT EXISTS FOR (n:CIEntity) ON n.embedding
        OPTIONS {indexConfig: {`vector.dimensions`:768,`vector.similarity_function`:'cosine'}}""")
    db.execute_query("CALL db.awaitIndexes(60)")
result = {
    "sources": len(rows),
    "dimensions": 768,
    "seconds": round(time.perf_counter() - started, 2),
}
(root / ".data/embedding-check.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result))
