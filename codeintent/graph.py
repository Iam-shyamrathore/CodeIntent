"""Scoped Neo4j projection and an official GraphRAG Retriever extension."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j_graphrag.retrievers.base import Retriever
from neo4j_graphrag.types import RawSearchResult, RetrieverResultItem

from codeintent.domain import scoped_id

ROOT = Path(__file__).resolve().parents[1]


def driver():
    load_dotenv(ROOT / ".env", override=False)
    return GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )


def run_query(db, query, **parameters):
    return db.execute_query(
        query, database_=os.getenv("NEO4J_DATABASE") or None, **parameters
    )


def index_id(corpus: dict) -> str:
    load_dotenv(ROOT / ".env", override=False)
    # Provenance, coverage and extractor policy are part of immutable index identity.
    manifest = json.dumps(
        {
            "version": "manifest-v2",
            "documents": sorted(corpus["documents"], key=lambda s: s["id"]),
            "links": sorted(
                corpus["links"], key=lambda r: json.dumps(r, sort_keys=True)
            ),
            "coverage": corpus["coverage"],
            "parser": "tree-sitter-0.25.2",
            "decision_policy": "evidence-v2",
            "embedding_model": os.getenv(
                "VERTEX_EMBEDDING_MODEL", "gemini-embedding-001"
            ),
            "decision_model": os.getenv("VERTEX_GENERATION_MODEL", "gemini-2.5-flash"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return scoped_id(corpus["repository_id"], corpus["revision"], "index", manifest)[
        :24
    ]


def project(corpus: dict, parsed: list[dict], *, scope: str | None = None) -> dict:
    scope = scope or index_id(corpus)
    repo_id, revision = corpus["repository_id"], corpus["revision"]
    entities, links = [], []

    def uid(key):
        return scoped_id(repo_id, scope, "entity", key)

    def entity(key: str, kind: str, **props):
        entities.append(
            {
                "uid": uid(key),
                "index_id": scope,
                "repository_id": repo_id,
                "revision": revision,
                "kind": kind,
                **props,
            }
        )

    def link(source: str, target: str, relation: str, evidence: str):
        links.append(
            {
                "source": uid(source),
                "target": uid(target),
                "relation": relation,
                "evidence": evidence,
                "index_id": scope,
            }
        )

    sources_by_id = {s["id"]: s for s in corpus["documents"]}
    numbers = {
        s["number"]: s["id"]
        for s in corpus["documents"]
        if s["kind"] in ["pull_request", "issue"] and "number" in s
    }
    for s in corpus["documents"]:
        entity(
            s["id"],
            "source",
            source_id=s["id"],
            source_kind=s["kind"],
            title=s["title"],
            body=s["body"],
            url=s["url"],
            date=s["date"],
            author=s["author"],
            sha256=s["sha256"],
            retrieved_at=s["retrieved_at"],
            merged_at=s.get("merged_at"),
            path=s.get("path"),
        )
        person_key = "person:" + s["author"]
        entity(person_key, "person", title=s["author"])
        link(s["id"], person_key, "AUTHORED_BY", s["id"])
        for n in re.findall(r"(?<![\w])#(\d+)\b", s["body"]):
            target = numbers.get(int(n))
            if target and target != s["id"]:
                link(s["id"], target, "REFERENCES", s["id"])
    for relation in corpus["links"]:
        if relation["source"] in sources_by_id and relation["target"] in sources_by_id:
            link(
                relation["source"],
                relation["target"],
                relation["relation"],
                relation["evidence"],
            )
    for file in parsed:
        path = file["path"]
        file_key = "file:" + path
        entity(file_key, "file", path=path, title=path)
        for kind, rows in [("function", file["functions"]), ("class", file["classes"])]:
            for item in rows:
                qual = (item.get("class_context") or "") + "." + item["name"]
                key = f"{path}:{kind}:{qual}:{item['line_number']}"
                entity(
                    key,
                    kind,
                    path=path,
                    title=qual.strip("."),
                    start_line=item["line_number"],
                    end_line=item.get("end_line", item["line_number"]),
                )
                link(
                    file_key,
                    key,
                    "CONTAINS",
                    file.get("source_id") or "code-" + path.replace("/", "-"),
                )
        for s in corpus["documents"]:
            if s.get("path") == path:
                link(s["id"], file_key, "RELATES_TO_PATH", s["id"])
        functions = {}
        for item in file["functions"]:
            functions.setdefault(item["name"], []).append(item)
        for call in file.get("function_calls", []):
            targets = functions.get(call["name"], [])
            if len(targets) == 1:
                target = targets[0]
                qual = (target.get("class_context") or "") + "." + target["name"]
                target_key = f"{path}:function:{qual}:{target['line_number']}"
                call_key = f"{path}:call:{call['line_number']}:{call['name']}"
                entity(
                    call_key,
                    "call",
                    path=path,
                    title=call["name"],
                    start_line=call["line_number"],
                )
                link(file_key, call_key, "CONTAINS", file.get("source_id", ""))
                link(call_key, target_key, "CALLS", file.get("source_id", ""))
    for source in corpus["documents"]:
        if source.get("previous_path") and source.get("path"):
            old = "file:" + source["previous_path"]
            new = "file:" + source["path"]
            entity(
                old,
                "file_alias",
                path=source["previous_path"],
                title=source["previous_path"],
            )
            entity(new, "file", path=source["path"], title=source["path"])
            link(old, new, "RENAMED_TO", source["id"])
            link(source["id"], old, "PREVIOUS_PATH", source["id"])
    with driver() as db:
        db.verify_connectivity()
        run_query(
            db,
            "CREATE CONSTRAINT ci_entity_uid IF NOT EXISTS FOR (n:CIEntity) REQUIRE n.uid IS UNIQUE",
        )
        run_query(
            db,
            "CREATE FULLTEXT INDEX ci_source_text IF NOT EXISTS FOR (n:CIEntity) ON EACH [n.title,n.body]",
        )
        run_query(
            db,
            "UNWIND $rows AS row MERGE (n:CIEntity {uid:row.uid}) SET n += row",
            rows=entities,
        )
        run_query(
            db,
            """UNWIND $rows AS row
            MATCH (a:CIEntity {uid:row.source,index_id:row.index_id})
            MATCH (b:CIEntity {uid:row.target,index_id:row.index_id})
            MERGE (a)-[r:CI_LINK {relation:row.relation,evidence:row.evidence,index_id:row.index_id}]->(b)""",
            rows=links,
        )
        counts, _, _ = run_query(
            db,
            "MATCH (n:CIEntity {index_id:$scope}) RETURN count(n) AS nodes",
            scope=scope,
        )
    return {
        "index_id": scope,
        "nodes": counts[0]["nodes"],
        "input_links": len(links),
        "files": len(parsed),
        "functions": sum(len(p["functions"]) for p in parsed),
    }


class EvidenceRetriever(Retriever):
    """Lexical seed retrieval plus bounded evidence traversal; vectors follow provider validation."""

    def get_search_results(
        self, query_text: str, scope: str, top_k: int = 10
    ) -> RawSearchResult:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", query_text)
        ignored = {
            "why",
            "was",
            "the",
            "what",
            "did",
            "how",
            "and",
            "does",
            "this",
            "that",
            "with",
            "from",
            "for",
            "were",
            "use",
            "using",
            "please",
            "httpx",
        }
        tokens = [t for t in tokens if t.lower() not in ignored][:12]
        if not tokens:
            return RawSearchResult(
                records=[], metadata={"index_id": scope, "paths": []}
            )
        lucene = " OR ".join('"' + t + '"' for t in tokens)
        records, _, _ = run_query(
            self.driver,
            """
            CALL db.index.fulltext.queryNodes('ci_source_text',$q) YIELD node,score
            WHERE node.index_id=$scope AND node.kind='source'
            RETURN node.uid AS uid,score ORDER BY score DESC LIMIT 5
            """,
            q=lucene,
            scope=scope,
        )
        seed_ids = [r["uid"] for r in records]
        result, _, _ = run_query(
            self.driver,
            """
            MATCH p=(seed:CIEntity)-[:CI_LINK*0..2]-(s:CIEntity)
            WHERE seed.uid IN $seeds AND s.index_id=$scope AND s.kind='source'
              AND all(n IN nodes(p) WHERE n.index_id=$scope)
              AND all(r IN relationships(p) WHERE r.index_id=$scope)
            WITH s,min(length(p)) AS distance
            RETURN s.source_id AS source_id,s.title AS title,s.body AS body,s.url AS url,
                   s.source_kind AS kind,s.date AS date,s.author AS author,distance
            ORDER BY distance,s.date LIMIT $limit
            """,
            seeds=seed_ids,
            scope=scope,
            limit=max(1, min(top_k, 20)),
        )
        paths, _, _ = run_query(
            self.driver,
            """
            MATCH (a:CIEntity)-[r:CI_LINK]->(b:CIEntity)
            WHERE a.index_id=$scope AND b.index_id=$scope AND r.index_id=$scope
              AND a.kind='source' AND b.kind='source'
              AND (a.source_id IN $ids AND b.source_id IN $ids)
            RETURN a.source_id AS source,r.relation AS relation,b.source_id AS target,r.evidence AS evidence
            LIMIT 30
            """,
            scope=scope,
            ids=[r["source_id"] for r in result],
        )
        return RawSearchResult(
            records=result,
            metadata={
                "index_id": scope,
                "paths": [dict(p) for p in paths],
                "mode": "lexical_and_graph",
                "seed_count": len(seed_ids),
            },
        )

    def get_result_formatter(self):
        return lambda record: RetrieverResultItem(
            content=record["body"],
            metadata={k: record[k] for k in record.keys() if k != "body"},
        )


def scope_names(scope: str):
    if not re.fullmatch(r"[a-f0-9]{24}", scope):
        raise ValueError("Invalid graph index identity")
    return "CISource_" + scope, "ci_vector_" + scope, "ci_text_" + scope


def embed_corpus(corpus: dict, *, scope: str | None = None) -> dict:
    from codeintent.vertex import client

    scope = scope or index_id(corpus)
    label, vector, text = scope_names(scope)
    rows = []
    with driver() as db:
        existing, _, _ = run_query(
            db,
            "MATCH (n:CIEntity {index_id:$scope,kind:'source'}) WHERE n.embedding IS NOT NULL RETURN n.source_id AS id",
            scope=scope,
        )
        done = {r["id"] for r in existing}
        with client() as model:
            pending = [s for s in corpus["documents"] if s["id"] not in done]
            for offset in range(0, len(pending), 10):
                docs = pending[offset : offset + 10]
                response = model.models.embed_content(
                    model=os.getenv("VERTEX_EMBEDDING_MODEL", "gemini-embedding-001"),
                    contents=[s["title"] + "\n" + s["body"][:12000] for s in docs],
                    config={
                        "output_dimensionality": 768,
                        "task_type": "RETRIEVAL_DOCUMENT",
                    },
                )
                if len(response.embeddings) != len(docs):
                    raise ValueError("Embedding count mismatch")
                rows = []
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
                run_query(
                    db,
                    "UNWIND $rows AS row MATCH (n:CIEntity {uid:row.uid,index_id:$scope}) SET n.embedding=row.embedding",
                    rows=rows,
                    scope=scope,
                )
        # Scope-specific indexes prevent another repository consuming top-k slots.
        run_query(
            db,
            f"MATCH (n:CIEntity {{index_id:$scope,kind:'source'}}) SET n:{label}",
            scope=scope,
        )
        run_query(
            db,
            f"CREATE FULLTEXT INDEX {text} IF NOT EXISTS FOR (n:{label}) ON EACH [n.title,n.body]",
        )
        run_query(
            db,
            f"CREATE VECTOR INDEX {vector} IF NOT EXISTS FOR (n:{label}) ON n.embedding OPTIONS {{indexConfig: {{`vector.dimensions`:768,`vector.similarity_function`:'cosine'}}}}",
        )
        run_query(db, "CALL db.awaitIndexes(120)")
    return {
        "sources": len(corpus["documents"]),
        "new_embeddings": len(pending),
        "dimensions": 768,
    }


def project_decisions(corpus: dict, decisions: list[dict], *, scope: str | None = None):
    scope = scope or index_id(corpus)
    rows = []
    links = []
    for decision in decisions:
        ident = scoped_id(corpus["repository_id"], scope, "entity", decision["id"])
        rows.append(
            {
                "uid": ident,
                "index_id": scope,
                "repository_id": corpus["repository_id"],
                "kind": "decision",
                "title": decision["summary"],
                "subject": decision["subject"],
                "aspect": decision["aspect"],
                "date": decision["date"],
                "outcome": decision["outcome"],
                "temporal_status": decision["status"],
            }
        )
        for citation in decision["citations"]:
            links.append(
                {
                    "source": ident,
                    "target": scoped_id(
                        corpus["repository_id"], scope, "entity", citation["source_id"]
                    ),
                    "relation": "SUPPORTED_BY",
                    "evidence": citation["source_id"],
                    "index_id": scope,
                }
            )
        if decision.get("replacement"):
            links.append(
                {
                    "source": ident,
                    "target": scoped_id(
                        corpus["repository_id"],
                        scope,
                        "entity",
                        decision["replacement"]["decision_id"],
                    ),
                    "relation": "QUALIFIED_REPLACEMENT",
                    "evidence": decision["source_id"],
                    "index_id": scope,
                }
            )
    with driver() as db:
        run_query(
            db,
            "UNWIND $rows AS row MERGE (n:CIEntity {uid:row.uid}) SET n += row",
            rows=rows,
        )
        run_query(
            db,
            """UNWIND $rows AS row MATCH (a:CIEntity {uid:row.source,index_id:row.index_id}),
            (b:CIEntity {uid:row.target,index_id:row.index_id})
            MERGE (a)-[:CI_LINK {index_id:row.index_id,relation:row.relation,evidence:row.evidence}]->(b)""",
            rows=links,
        )
