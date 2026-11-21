"""Operations snapshot and operator alerts, against real Postgres and Procrastinate's own tables."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from codeintent import ops, store
from codeintent.api import app

pytestmark = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_INTEGRATION") != "1", reason="requires real Postgres"
)


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
    yield
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def job(conn, task: str, status: str, *, failed_at=None, scheduled_at=None) -> int:
    ident = conn.execute(
        """INSERT INTO procrastinate_jobs(queue_name,task_name,args,status,scheduled_at,attempts)
        VALUES ('pulls',%s,'{}',%s,%s,3) RETURNING id""",
        (task, status, scheduled_at),
    ).fetchone()["id"]
    if failed_at:
        conn.execute(
            "INSERT INTO procrastinate_events(job_id,type,at) VALUES (%s,'failed',%s)",
            (ident, failed_at),
        )
    return ident


def test_final_failures_and_backlog_are_reported_once(schema):
    now = datetime.now(UTC)
    with store.connection() as conn:
        job(
            conn, "analyze_pull_request", "failed", failed_at=now - timedelta(minutes=3)
        )
        job(conn, "analyze_pull_request", "failed", failed_at=now - timedelta(hours=2))
        job(conn, "scan_repository", "todo", scheduled_at=now - timedelta(hours=1))
        lines = ops.problems(conn, now - timedelta(minutes=10))
        state = ops.snapshot(conn)
    assert lines[0] == "1 analyze_pull_request job failed with no retry left"
    assert any("oldest waiting job" in line for line in lines) == (now.minute < 10)
    assert state["queue"]["failed_24h"] == {"analyze_pull_request": 2}
    assert state["queue"]["waiting"] == {"scan_repository": 1}
    assert state["worker"]["stalled"] is True


def test_ops_needs_the_operator_key(schema, monkeypatch):
    monkeypatch.setenv("CODEINTENT_API_SECRET", "s" * 32)
    monkeypatch.setenv("CODEINTENT_OPERATOR_TOKEN", "o" * 32)
    with TestClient(app) as client:
        assert (
            client.get("/app/ops", headers={"X-Api-Key": "s" * 32}).status_code == 403
        )
        body = client.get(
            "/app/ops", headers={"X-Api-Key": "s" * 32, "X-Operator-Key": "o" * 32}
        ).json()
    assert set(body) >= {"worker", "queue", "webhooks_24h", "scans", "telegram", "mcp"}
