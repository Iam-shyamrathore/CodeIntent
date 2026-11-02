"""Runs against real Postgres and Neo4j in a disposable SQL schema/graph scope.
Run with CODEINTENT_RUN_INTEGRATION=1 uv run pytest tests/test_storage_integration.py.
"""

import hashlib
import os
import uuid
from types import SimpleNamespace

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from codeintent import store
from codeintent.settings import required

pytestmark = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_INTEGRATION") != "1",
    reason="requires real Postgres and Neo4j",
)


@pytest.fixture
def isolated(monkeypatch):
    original = required("DATABASE_URL")
    name = "ci_test_" + uuid.uuid4().hex
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    monkeypatch.setenv(
        "DATABASE_URL",
        psycopg.conninfo.make_conninfo(original, options=f"-c search_path={name}"),
    )
    store.migrate()
    yield
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


@pytest.fixture
def corpus():
    body = "A unique fixture decision " + uuid.uuid4().hex
    return {
        "repository": "fixtures/test",
        "repository_id": 987654321,
        "revision": "f" * 40,
        "documents": [
            {
                "id": "pr-1",
                "kind": "pull_request",
                "title": "Fixture decision",
                "body": body,
                "url": "https://github.com/fixtures/test/pull/1",
                "date": "2024-01-01T00:00:00Z",
                "author": "fixture",
                "retrieved_at": "2024-01-02T00:00:00Z",
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
            }
        ],
        "links": [],
        "coverage": {
            "scope": "disposable integration fixture",
            "full_repository_history": False,
        },
    }


def test_migrations_are_repeatable(isolated):
    store.migrate()
    with store.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS count FROM ci_schema_versions").fetchone()[
                "count"
            ]
            == 2
        )


def test_queue_submission_and_ledger_rollback_together(isolated):
    from codeintent.tasks import import_repository

    ident = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO ci_imports(id,repository,options) VALUES (%s,'fixture/rollback','{}')",
                (ident,),
            )
            import_repository.configure(connection=conn, queue="isolated-test").defer(
                import_id=ident
            )
            raise RuntimeError("Simulated process failure before commit")
    with store.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS count FROM ci_imports").fetchone()["count"]
            == 0
        )
        assert (
            conn.execute("SELECT count(*) AS count FROM procrastinate_jobs").fetchone()[
                "count"
            ]
            == 0
        )


def test_quota_boundary_is_atomic_and_persistent(isolated):
    store.consume_quota("test", 1)
    with pytest.raises(store.QuotaExceeded):
        store.consume_quota("test", 1)
    with store.connection() as conn:
        assert (
            conn.execute("SELECT count FROM ci_usage WHERE bucket='test'").fetchone()[
                "count"
            ]
            == 1
        )


def test_failed_projection_resumes_from_decision_checkpoint(
    isolated, corpus, monkeypatch
):
    from codeintent.graph import driver, index_id
    from codeintent.tasks import import_repository

    scope = index_id(corpus)
    ident = str(uuid.uuid4())
    calls = []
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_imports(id,repository,options,checkpoint) VALUES (%s,%s,'{}',%s)",
            (ident, corpus["repository"], Jsonb({"corpus": corpus})),
        )
    monkeypatch.setattr(
        "codeintent.temporal.extract_decisions",
        lambda data: calls.append("extract") or [],
    )

    def fail(data):
        raise ConnectionError("Simulated graph outage")

    monkeypatch.setattr("codeintent.graph.embed_corpus", fail)
    context = SimpleNamespace(job=SimpleNamespace(attempts=0))
    try:
        with pytest.raises(RuntimeError):
            import_repository.func(context, import_id=ident)
        assert store.job(ident)["status"] == "retrying"
        assert store.get_index(repository=corpus["repository"]) is None
        assert store.get_index(scope) is None

        def embed(data):
            with driver() as db:
                db.execute_query(
                    "MATCH (n:CIEntity {index_id:$scope,kind:'source'}) SET n.embedding=$vector",
                    scope=scope,
                    vector=[0.1] * 768,
                )

        monkeypatch.setattr("codeintent.graph.embed_corpus", embed)
        import_repository.func(context, import_id=ident)
        assert calls == ["extract"]
        assert store.job(ident)["status"] == "ready"
        assert store.get_index(repository=corpus["repository"])["id"] == scope
        # Replaying a completed task cannot duplicate anything.
        import_repository.func(context, import_id=ident)
        assert calls == ["extract"]
    finally:
        with driver() as db:
            db.execute_query(
                "MATCH (n:CIEntity {index_id:$scope}) DETACH DELETE n", scope=scope
            )


def test_graph_projection_is_idempotent_and_scoped(corpus):
    from codeintent.graph import EvidenceRetriever, driver, index_id, project

    foreign = {
        **corpus,
        "revision": "e" * 40,
        "documents": [
            dict(corpus["documents"][0], sha256="a" * 64, body="FOREIGN_INDEX_SENTINEL")
        ],
    }
    one = index_id(corpus)
    two = index_id(foreign)
    try:
        first = project(corpus, [])
        again = project(corpus, [])
        project(foreign, [])
        assert first["nodes"] == again["nodes"]
        with driver() as db:
            result = EvidenceRetriever(db).get_search_results(
                "FOREIGN_INDEX_SENTINEL", scope=one
            )
            assert not result.records
            links, _, _ = db.execute_query(
                "MATCH (a:CIEntity)-[r:CI_LINK]->(b:CIEntity) WHERE a.index_id=$one AND b.index_id=$two RETURN count(r) AS count",
                one=one,
                two=two,
            )
            assert links[0]["count"] == 0
    finally:
        with driver() as db:
            db.execute_query(
                "MATCH (n:CIEntity) WHERE n.index_id IN $scopes DETACH DELETE n",
                scopes=[one, two],
            )


def test_worker_loss_requeues_orphaned_job(isolated):
    from codeintent.tasks import heartbeat, import_repository

    with store.connection() as conn:
        ident = import_repository.configure(
            connection=conn, queue="isolated-test"
        ).defer(import_id=str(uuid.uuid4()))
        conn.execute(
            "UPDATE procrastinate_jobs SET status='doing',worker_id=NULL WHERE id=%s",
            (ident,),
        )
    heartbeat.func(0)
    with store.connection() as conn:
        assert (
            conn.execute(
                "SELECT status FROM procrastinate_jobs WHERE id=%s", (ident,)
            ).fetchone()["status"]
            == "todo"
        )
