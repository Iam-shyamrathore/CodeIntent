"""MCP through the API process: per-installation tokens, revocation, and which repositories they unlock.

Real Postgres in a disposable schema (CODEINTENT_RUN_INTEGRATION=1). The tool call downloads a real public
repository (CODEINTENT_RUN_NETWORK=1).
"""

from __future__ import annotations

import json
import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from codeintent import github_app, store
from codeintent.api import app

SECRET = "test-service-secret"
integration = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_INTEGRATION") != "1", reason="requires real Postgres"
)
network = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_NETWORK") != "1", reason="downloads a GitHub repository"
)
ACCEPT = {"Accept": "application/json, text/event-stream"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}


@pytest.fixture
def client(monkeypatch):
    original = os.environ.get("DATABASE_URL") or pytest.skip("DATABASE_URL is not set")
    name = "ci_test_" + uuid.uuid4().hex
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    monkeypatch.setenv(
        "DATABASE_URL",
        psycopg.conninfo.make_conninfo(original, options=f"-c search_path={name}"),
    )
    monkeypatch.setenv("CODEINTENT_API_SECRET", SECRET)
    monkeypatch.delenv("CODEINTENT_MCP_TOKEN", raising=False)
    store.migrate()
    with store.connection() as conn:
        conn.execute(
            """INSERT INTO ci_installations(id,account_login,account_type) VALUES
            (31,'acme','Organization'),(32,'other','User')"""
        )
        conn.execute(
            """INSERT INTO ci_installation_repositories(installation_id,repository_id,full_name) VALUES
            (31,1,'Iam-shyamrathore/codeintent-demo')"""
        )
    with TestClient(app, headers={"X-Api-Key": SECRET}) as test:
        yield test
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def mcp(client, token: str | None, body: dict):
    headers = {**ACCEPT, "X-Api-Key": ""}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/mcp", json=body, headers=headers)


def result_of(response) -> dict:
    """The JSON-RPC message from a JSON or a single-event SSE response."""
    text = response.text
    if text.lstrip().startswith("{"):
        return json.loads(text)
    data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    return json.loads(data[-1])


@integration
def test_tokens_are_shown_once_scoped_and_revocable(client):
    created = client.post("/app/installations/31/mcp-tokens")
    assert created.status_code == 201
    token = created.json()["token"]
    assert token.startswith("ci_mcp_") and len(token) > 40
    listed = client.get("/app/installations/31/mcp-tokens").json()["tokens"]
    assert [t["hint"] for t in listed] == [token[-4:]] and "token" not in listed[0]
    with store.connection() as conn:
        stored = conn.execute("SELECT token_hash FROM ci_mcp_tokens").fetchone()
    assert token not in json.dumps(stored)

    assert mcp(client, None, INITIALIZE).status_code == 401
    assert mcp(client, "ci_mcp_" + "x" * 43, INITIALIZE).status_code == 401
    assert mcp(client, token, INITIALIZE).status_code == 200
    assert client.get("/app/installations/31/mcp-tokens").json()["tokens"][0][
        "last_used_at"
    ]

    ident = listed[0]["id"]
    assert client.delete(f"/app/installations/32/mcp-tokens/{ident}").status_code == 404
    assert client.delete(f"/app/installations/31/mcp-tokens/{ident}").status_code == 204
    assert mcp(client, token, INITIALIZE).status_code == 401
    assert client.post("/app/installations/99/mcp-tokens").status_code == 404


@integration
@network
def test_a_workspace_token_reads_its_own_repositories_with_the_installation_token(
    client, monkeypatch
):
    from codeintent.upgrades.repository import token as developer_token

    used, real = [], developer_token()

    def installation_token(installation_id, **_):
        used.append(installation_id)
        return real

    monkeypatch.setattr(github_app, "installation_token", installation_token)
    token = client.post("/app/installations/31/mcp-tokens").json()["token"]
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "why_pinned",
            "arguments": {
                "repo": "Iam-shyamrathore/codeintent-demo",
                "package": "httpx",
            },
        },
    }
    assert mcp(client, token, INITIALIZE).status_code == 200
    response = mcp(client, token, call)
    assert response.status_code == 200, response.text
    structured = result_of(response)["result"]["structuredContent"]
    assert structured["declarations"][0]["specifier"] == "==0.27.2"
    assert used and set(used) == {31}
    with store.connection() as conn:
        run = conn.execute(
            "SELECT * FROM ci_runs WHERE kind='mcp' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        steps = conn.execute(
            "SELECT name,status FROM ci_run_steps WHERE run_id=%s ORDER BY seq",
            (run["id"],),
        ).fetchall()
    assert (run["installation_id"], run["subject"], run["status"]) == (
        31,
        "why_pinned",
        "succeeded",
    )
    assert run["repository"] == "Iam-shyamrathore/codeintent-demo" and run["token_id"]
    assert run["input"] == {
        "repo": "Iam-shyamrathore/codeintent-demo",
        "package": "httpx",
    }
    assert run["result"]["declarations"][0]["specifier"] == "==0.27.2"
    assert run["summary"]["declarations"] == 1
    assert steps[0] == {"name": "download the repository", "status": "ok"}

    used.clear()
    other = {
        **call,
        "params": {
            **call["params"],
            "arguments": {"repo": "pallets/flask@1.1.4", "package": "itsdangerous"},
        },
    }
    assert mcp(client, token, other).status_code == 200
    assert used == []  # not this workspace's repository: fetched as the public sees it

    bad = {
        **call,
        "params": {
            **call["params"],
            "arguments": {"repo": "not a repo", "package": "httpx"},
        },
    }
    assert result_of(mcp(client, token, bad))["result"]["isError"] is True
    with store.connection() as conn:
        failed = conn.execute(
            "SELECT status,error FROM ci_runs WHERE kind='mcp' AND status='failed'"
        ).fetchone()
    assert failed["error"].startswith("ToolError: ")
