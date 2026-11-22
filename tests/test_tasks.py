import importlib


def test_graph_keepalive_runs_a_read_query(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused@localhost/unused")
    tasks = importlib.import_module("codeintent.tasks")
    queries = []

    class FakeDriver:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("codeintent.graph.driver", FakeDriver)
    monkeypatch.setattr(
        "codeintent.graph.run_query", lambda db, query, **_: queries.append(query)
    )

    tasks.graph_keepalive(timestamp=0)

    assert queries == ["RETURN 1"]


def test_jobs_join_the_callers_transaction_outside_the_worker(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused@localhost/unused")
    monkeypatch.delenv("CODEINTENT_PROCESS", raising=False)
    tasks = importlib.import_module("codeintent.tasks")
    conn = object()

    assert tasks.on(conn) == {"connection": conn}


def test_jobs_queued_inside_the_worker_use_procrastinates_own_pool(monkeypatch):
    # The worker's pool is async: handing it a sync connection raises TypeError.
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused@localhost/unused")
    monkeypatch.setenv("CODEINTENT_PROCESS", "worker")
    tasks = importlib.import_module("codeintent.tasks")

    assert tasks.on(object()) == {}


def test_ecosystem_releases_are_queued_without_the_sync_connection_in_the_worker(
    monkeypatch,
):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused@localhost/unused")
    monkeypatch.setenv("CODEINTENT_PROCESS", "worker")
    ecosystem = importlib.import_module("codeintent.ecosystem")
    tasks = importlib.import_module("codeintent.tasks")
    seen = []

    class Deferrer:
        def defer(self, **kwargs):
            seen.append(kwargs)

    class Conn:
        def commit(self):
            pass

        def rollback(self):
            pass

    class Connection:
        def __enter__(self):
            return Conn()

        def __exit__(self, *exc):
            return False

    def configure(**options):
        assert "connection" not in options
        return Deferrer()

    monkeypatch.setattr(tasks.index_release, "configure", configure)
    monkeypatch.setattr("codeintent.store.connection", Connection)

    assert ecosystem._defer([{"package": "h11", "version": "0.14.0"}]) == 1
    assert seen == [{"package": "h11", "version": "0.14.0"}]
