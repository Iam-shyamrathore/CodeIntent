"""Runs and the breaks ledger, against real Postgres in a disposable schema (CODEINTENT_RUN_INTEGRATION=1)."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg import sql

from codeintent import breaks, runs, store

pytestmark = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_INTEGRATION") != "1", reason="requires real Postgres"
)

# The demo repository's real finding (scan of Iam-shyamrathore/codeintent-demo), trimmed.
HTTPX = {
    "package": "httpx",
    "start": "0.27.2",
    "end": "0.28.1",
    "verdict": "breaks",
    "findings": [
        {
            "severity": "breaks",
            "change": {
                "kind": "parameter-removed",
                "symbol": "httpx._client.Client",
                "parameter": "proxies",
                "replacement": "proxy= or mounts=",
            },
            "locations": [{"file": "weather/client.py", "line": 12, "column": 8}],
        }
    ],
    "decisions": [
        {
            "change_key": {
                "symbol": "httpx._client.Client",
                "parameter": "proxies",
                "kind": "parameter-removed",
            },
            "pr_number": 3319,
            "pr_url": "https://github.com/encode/httpx/pull/3319",
        }
    ],
}
CLIENT = '''"""Fetches forecasts."""
import httpx


def make_client():
    proxy = None
    return httpx.Client(
        timeout=10,
        proxies={"https://": proxy} if proxy else None,
    )
'''


@pytest.fixture
def schema(monkeypatch):
    original = os.environ.get("DATABASE_URL") or pytest.skip("DATABASE_URL is not set")
    name = "ci_test_" + uuid.uuid4().hex
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    monkeypatch.setenv(
        "DATABASE_URL",
        psycopg.conninfo.make_conninfo(original, options=f"-c search_path={name}"),
    )
    store.migrate()
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_installations(id,account_login,account_type) VALUES (41,'acme','Organization')"
        )
    yield
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def steps(run_id: str) -> list[tuple]:
    with store.connection() as conn:
        return [
            (r["name"], r["status"], r["detail"])
            for r in conn.execute(
                "SELECT * FROM ci_run_steps WHERE run_id=%s ORDER BY seq", (run_id,)
            ).fetchall()
        ]


def run_row(run_id: str) -> dict:
    with store.connection() as conn:
        return conn.execute("SELECT * FROM ci_runs WHERE id=%s", (run_id,)).fetchone()


def test_a_failing_step_fails_the_run_with_only_its_category(schema):
    class UpstreamDown(Exception):
        pass

    with pytest.raises(UpstreamDown):
        with runs.recorded(
            "scan", installation_id=41, repository="acme/app", subject="default branch"
        ) as run:
            with run.step("read the repository") as note:
                note["detail"] = "default branch main"
            with run.step("download the repository"):
                raise UpstreamDown("https://api.github.com/... token=secret")
    row = run_row(run.id)
    assert (row["status"], row["failed_step"], row["error"]) == (
        "failed",
        "download the repository",
        "UpstreamDown",
    )
    assert row["finished_at"] is not None
    assert steps(run.id) == [
        ("read the repository", "ok", "default branch main"),
        ("download the repository", "failed", "UpstreamDown"),
    ]


def test_a_finished_run_keeps_its_summary_and_result(schema):
    with runs.recorded(
        "pull", installation_id=41, repository="acme/app", subject="#5"
    ) as run:
        run.skip("check advisories for new packages", "no new packages")
        run.finish(
            "partial", summary={"unreadable": ["numpy"]}, result={"verdicts": []}
        )
    row = run_row(run.id)
    assert (row["status"], row["summary"], row["result"]) == (
        "partial",
        {"unreadable": ["numpy"]},
        {"verdicts": []},
    )


def test_breaks_keep_the_code_line_and_resolve_with_later_runs(schema, tmp_path):
    (tmp_path / "weather").mkdir()
    (tmp_path / "weather" / "client.py").write_text(
        CLIENT.replace("    proxy = None\n", "    proxy = None\n\n\n\n")
    )
    line = (
        CLIENT.replace("    proxy = None\n", "    proxy = None\n\n\n\n")
        .splitlines()
        .index('        proxies={"https://": proxy} if proxy else None,')
        + 1
    )
    verdict = HTTPX | {
        "findings": [
            HTTPX["findings"][0]
            | {"locations": [{"file": "weather/client.py", "line": line}]}
        ]
    }
    with runs.recorded(
        "scan", installation_id=41, repository="acme/app", subject="main"
    ) as first:
        with store.connection() as conn:
            counts = breaks.record(
                conn,
                installation_id=41,
                repository="acme/app",
                source="scan",
                verdicts=[verdict],
                root=tmp_path,
                run_id=first.id,
            )
    assert counts == {"found": 1, "fixed": 0}
    with store.connection() as conn:
        row = conn.execute("SELECT * FROM ci_breaks").fetchone()
    assert row["key"] == "httpx@0.28.1:parameter-removed:httpx._client.Client:proxies"
    assert row["places"] == [
        {
            "file": "weather/client.py",
            "line": line,
            "code": 'proxies={"https://": proxy} if proxy else None,',
        }
    ]
    assert row["decision"]["pr_number"] == 3319 and row["status"] == "open"

    # The next scan no longer finds it: the code was fixed.
    with runs.recorded(
        "scan", installation_id=41, repository="acme/app", subject="main"
    ) as second:
        with store.connection() as conn:
            assert breaks.record(
                conn,
                installation_id=41,
                repository="acme/app",
                source="scan",
                verdicts=[],
                root=tmp_path,
                run_id=second.id,
            ) == {"found": 0, "fixed": 1}
    with store.connection() as conn:
        row = conn.execute(
            "SELECT status,resolved_at,last_run FROM ci_breaks"
        ).fetchone()
    assert (
        row["status"] == "fixed"
        and row["resolved_at"]
        and str(row["last_run"]) == second.id
    )


def test_pull_request_breaks_follow_the_pull_request(schema):
    with runs.recorded(
        "pull", installation_id=41, repository="acme/app", subject="#7"
    ) as run:
        with store.connection() as conn:
            breaks.record(
                conn,
                installation_id=41,
                repository="acme/app",
                source="pull",
                verdicts=[HTTPX],
                root=None,
                run_id=run.id,
                pull_number=7,
            )
            assert breaks.pull_closed(conn, 41, "acme/app", 8, merged=True) == 0
            assert breaks.pull_closed(conn, 41, "acme/app", 7, merged=True) == 1
            row = conn.execute("SELECT status,places FROM ci_breaks").fetchone()
    assert row["status"] == "merged"
    assert row["places"] == [{"file": "weather/client.py", "line": 12, "code": None}]


def test_code_outside_the_repository_is_never_read(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "secret.txt").write_text("token\n")
    assert breaks.code_at(tmp_path / "repo", "../secret.txt", 1) is None


def test_runs_and_breaks_are_scoped_to_the_callers_installations(schema, monkeypatch):
    from fastapi.testclient import TestClient

    from codeintent.api import app

    monkeypatch.setenv("CODEINTENT_API_SECRET", "s" * 32)
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_installations(id,account_login,account_type) VALUES (42,'other','User')"
        )
        conn.execute(
            """INSERT INTO ci_installation_repositories(installation_id,repository_id,full_name) VALUES
            (41,1,'acme/app'),(42,2,'other/secret')"""
        )
    for installation, repository in ((41, "acme/app"), (42, "other/secret")):
        with pytest.raises(RuntimeError):
            with runs.recorded(
                "pull",
                installation_id=installation,
                repository=repository,
                subject="#1",
            ) as run:
                with store.connection() as conn:
                    breaks.record(
                        conn,
                        installation_id=installation,
                        repository=repository,
                        source="pull",
                        verdicts=[HTTPX],
                        root=None,
                        run_id=run.id,
                        pull_number=1,
                    )
                with run.step("write the comment"):
                    raise RuntimeError("boom")
        if installation == 41:
            mine = run.id
    with TestClient(app, headers={"X-Api-Key": "s" * 32}) as client:
        listed = client.get("/app/runs?installations=41&problems=true").json()["runs"]
        assert [(r["id"], r["failed_step"], r["error"]) for r in listed] == [
            (mine, "write the comment", "RuntimeError")
        ]
        detail = client.get(f"/app/runs/{mine}?installations=41").json()
        assert [s["status"] for s in detail["steps"]] == ["failed"]
        assert detail["breaks"][0]["package"] == "httpx"
        assert client.get(f"/app/runs/{mine}?installations=42").status_code == 404
        found = client.get("/app/breaks?installations=41").json()["breaks"]
        assert [b["repository"] for b in found] == ["acme/app"]
        assert client.get("/app/breaks?installations=43").json()["breaks"] == []
