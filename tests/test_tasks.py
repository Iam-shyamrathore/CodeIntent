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
