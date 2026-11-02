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
            == 4
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


def test_question_deduplication_and_atomic_quota(isolated, corpus, monkeypatch):
    from codeintent.questions import submit

    scope = "b" * 24
    store.save_index(corpus, [], scope, publish=True)
    key = store.cache_key(scope, "Why did the fixture change?")
    first = submit({"id": scope}, "Why did the fixture change?", key, "test")
    assert submit({"id": scope}, "Why did the fixture change?", key, "test") == first
    with store.connection() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM procrastinate_jobs").fetchone()["n"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count FROM ci_usage WHERE bucket='client:test'"
            ).fetchone()["count"]
            == 1
        )
    monkeypatch.setenv("CODEINTENT_GLOBAL_QUESTIONS_PER_DAY", "1")
    with pytest.raises(store.QuotaExceeded):
        submit({"id": scope}, "Another fixture question?", "other", "second")
    with store.connection() as conn:
        assert not conn.execute(
            "SELECT 1 FROM ci_usage WHERE bucket='client:second'"
        ).fetchone()
        assert (
            conn.execute("SELECT count(*) AS n FROM ci_questions").fetchone()["n"] == 1
        )


def test_question_provider_failure_retries_and_persists_report(
    isolated, corpus, monkeypatch
):
    from codeintent.questions import process, status, submit

    scope = "c" * 24
    question = "Why did the fixture change?"
    store.save_index(corpus, [], scope, publish=True)
    job = submit({"id": scope}, question, store.cache_key(scope, question), "test")

    def fail(*args, **kwargs):
        raise ConnectionError("secret upstream details")

    monkeypatch.setattr("codeintent.investigate.investigate", fail)
    context = SimpleNamespace(job=SimpleNamespace(attempts=0))
    with pytest.raises(RuntimeError, match="ConnectionError"):
        process(context, job["job_id"])
    assert status(job["job_id"])["status"] == "retrying"
    assert "secret" not in status(job["job_id"])["detail"]
    monkeypatch.setattr(
        "codeintent.investigate.investigate",
        lambda *args, **kw: {
            "question": question,
            "index_id": scope,
            "answer": {"status": "insufficient"},
        },
    )
    process(context, job["job_id"])
    result = status(job["job_id"])
    assert result["status"] == "ready"
    process(context, job["job_id"])
    assert status(job["job_id"])["result"]["report_id"] == result["result"]["report_id"]


def test_data_api_cannot_access_ledger_or_queue(isolated):
    with store.connection() as conn:
        assert not conn.execute(
            "SELECT relname FROM pg_class WHERE relnamespace=current_schema()::regnamespace AND relkind='r' AND NOT relrowsecurity"
        ).fetchall()
        assert not conn.execute("""SELECT p.proname FROM pg_proc p, LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) acl
            WHERE p.pronamespace=current_schema()::regnamespace AND acl.grantee=0 AND acl.privilege_type='EXECUTE'""").fetchall()
