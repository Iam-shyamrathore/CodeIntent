"""Dashboard read endpoints for GitHub App installations, repositories and pull request verdicts.

Validation and auth tests run anywhere. The database tests run against real Postgres in a disposable
schema: CODEINTENT_RUN_INTEGRATION=1 uv run pytest tests/test_dashboard_api.py
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from codeintent import store
from codeintent.api import app
from codeintent.upgrades.verdict import UpgradeVerdict

SECRET = "test-service-secret"
integration = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_INTEGRATION") != "1", reason="requires real Postgres"
)

# Trimmed from `python -m scripts.verdict --path openai-python-v1.54.4 --package httpx --from 0.27.2
# --to 0.28.0 --no-release`; validated through the model so the stored shape matches the engine's.
HTTPX = UpgradeVerdict.model_validate(
    {
        "package": "httpx",
        "start": "0.27.2",
        "end": "0.28.0",
        "verdict": "breaks",
        "label": "Breaks you",
        "reason": "2 change(s) in httpx 0.28.0 break code you use, at 3 place(s)",
        "findings": [
            {
                "severity": "breaks",
                "change": {
                    "kind": "parameter-removed",
                    "symbol": "httpx._client.Client",
                    "parameter": "proxies",
                    "detail": "httpx._client.Client accepts proxies= in 0.27.2 but not in 0.28.0",
                    "message": "The 'proxies' argument is now deprecated. Use 'proxy' or 'mounts' instead.",
                    "replacement": "proxy= or mounts=",
                    "replacement_source": "message",
                    "before": {"file": "httpx/_client.py", "line": 628},
                    "after": {"file": "httpx/_client.py", "line": 641},
                },
                "guarded": False,
                "locations": [
                    {"file": "src/openai/_base_client.py", "line": 857, "column": 38},
                    {"file": "src/openai/cli/_cli.py", "line": 179, "column": 18},
                ],
            }
        ],
        "limits": [
            {
                "reason": "kwargs-passthrough",
                "detail": "keyword arguments reach httpx.Client.send through ** unpacking",
                "location": {
                    "file": "src/openai/_base_client.py",
                    "line": 991,
                    "column": 23,
                },
                "symbol": "httpx.Client.send",
            }
        ],
        "coverage": {
            "files": 51,
            "usages": 619,
            "checked": 619,
            "unchecked": 14,
            "unchanged_unchecked": 14,
            "upstream_changes": 16,
        },
        "advisories": [
            {"package": "httpx", "version": "0.27.2", "status": "none-known"},
            {"package": "httpx", "version": "0.28.0", "status": "none-known"},
        ],
    }
).model_dump(mode="json")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CODEINTENT_ENV", "test")
    monkeypatch.setenv("CODEINTENT_API_SECRET", SECRET)
    return TestClient(app, headers={"X-Api-Key": SECRET})


@pytest.mark.parametrize(
    "path",
    [
        "/app/installations",
        "/app/installations/1/repositories",
        "/app/repositories/acme/app/pulls",
        f"/app/pulls/{uuid.uuid4()}",
    ],
)
def test_dashboard_requires_service_secret(client, path):
    assert client.get(path, headers={"X-Api-Key": "wrong"}).status_code == 401


def test_dashboard_validates_inputs_before_querying(client):
    assert client.get("/app/pulls/not-a-uuid").status_code == 422
    assert client.get("/app/repositories/-bad/app/pulls").status_code == 422
    assert client.get("/app/repositories/acme/app/pulls?limit=0").status_code == 422
    assert client.get("/app/repositories/acme/app/pulls?limit=101").status_code == 422
    response = client.get("/app/repositories/acme/app/pulls?cursor=bm90LWEtY3Vyc29y")
    assert response.status_code == 400


@pytest.mark.parametrize(
    "path", ["/app/installations", "/app/repositories/acme/app/pulls"]
)
def test_installation_scope_is_validated_before_querying(client, path):
    assert client.get(f"{path}?installations=0").status_code == 422
    assert client.get(f"{path}?installations=x").status_code == 422
    many = "&".join(f"installations={i}" for i in range(1, 102))
    assert client.get(f"{path}?{many}").status_code == 422


@pytest.fixture
def seeded(monkeypatch, client):
    original = os.environ.get("DATABASE_URL") or pytest.skip("DATABASE_URL is not set")
    name = "ci_test_" + uuid.uuid4().hex
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    monkeypatch.setenv(
        "DATABASE_URL",
        psycopg.conninfo.make_conninfo(original, options=f"-c search_path={name}"),
    )
    store.migrate()
    now = datetime.now(UTC)
    ids = {}
    with store.connection() as conn:
        conn.execute(
            """INSERT INTO ci_installations(id,account_login,account_type,deleted_at) VALUES
            (11,'acme','Organization',NULL),(12,'solo','User',NULL),(13,'gone','Organization',now())"""
        )
        conn.execute(
            """INSERT INTO ci_installation_repositories(installation_id,repository_id,full_name,private) VALUES
            (11,1,'acme/app',false),(11,2,'acme/private-app',true),(12,3,'solo/empty',false),(13,4,'gone/secret',true)"""
        )
        rows = [
            ("breaks", 11, "acme/app", 5, "reported", "breaks", [HTTPX], 3),
            ("skipped", 11, "acme/app", 6, "skipped", None, None, 2),
            ("running", 11, "acme/app", 7, "running", None, None, 1),
            ("private", 11, "acme/private-app", 1, "reported", "breaks", [HTTPX], 1),
            ("gone", 13, "gone/secret", 1, "reported", "breaks", [HTTPX], 1),
        ]
        for key, inst, repo, number, status, verdict, verdicts, days in rows:
            ids[key] = str(uuid.uuid4())
            diff = {
                "files": ["requirements.lock"],
                "added": [],
                "removed": [],
                "changed": [
                    {
                        "name": "httpx",
                        "file": "requirements.lock",
                        "old": {"specifier": "", "locked_version": "0.27.2"},
                        "new": {"specifier": "", "locked_version": "0.28.0"},
                    }
                ],
                "issues": [],
            }
            conn.execute(
                """INSERT INTO ci_pull_analyses(id,installation_id,repository,number,head_sha,base_sha,
                status,diff,verdicts,verdict,title,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    ids[key],
                    inst,
                    repo,
                    number,
                    "a" * 40,
                    "b" * 40,
                    status,
                    Jsonb(diff),
                    Jsonb(verdicts) if verdicts else None,
                    verdict,
                    f"Bump httpx #{number}",
                    now - timedelta(days=days),
                ),
            )
    yield ids
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


@integration
def test_installations_hide_deleted_and_count_repositories(client, seeded):
    body = client.get("/app/installations").json()
    assert [
        (i["account_login"], i["repositories"], i["analyses"])
        for i in body["installations"]
    ] == [
        ("acme", 2, 4),
        ("solo", 1, 0),
    ]
    assert client.get("/app/installations/13/repositories").status_code == 404
    assert client.get("/app/installations/99/repositories").status_code == 404


@integration
def test_repositories_carry_latest_analysis_and_latest_verdict(client, seeded):
    body = client.get("/app/installations/11/repositories").json()
    app_repo = next(r for r in body["repositories"] if r["full_name"] == "acme/app")
    assert app_repo["last_analysis"]["status"] == "running"
    assert app_repo["last_verdict"]["id"] == seeded["breaks"]
    assert app_repo["verdict_counts"]["breaks"] == 1
    assert {r["full_name"] for r in body["repositories"]} == {
        "acme/app",
        "acme/private-app",
    }


@integration
def test_pulls_paginate_newest_first_and_stay_in_their_installation(client, seeded):
    first = client.get("/app/repositories/ACME/app/pulls?limit=2").json()
    assert [p["number"] for p in first["pulls"]] == [7, 6]
    assert first["pulls"][0]["packages"] == [
        {
            "package": "httpx",
            "start": "0.27.2",
            "end": "0.28.0",
            "verdict": None,
            "label": None,
        }
    ]
    second = client.get(
        f"/app/repositories/acme/app/pulls?limit=2&cursor={first['next_cursor']}"
    ).json()
    assert [p["number"] for p in second["pulls"]] == [5]
    assert second["pulls"][0]["packages"][0]["label"] == "Breaks you"
    assert second["next_cursor"] is None
    assert client.get("/app/repositories/gone/secret/pulls").status_code == 404
    assert (
        client.get("/app/repositories/acme/app/pulls?installation=12").status_code
        == 404
    )


@integration
def test_pull_detail_returns_verdicts_and_never_deleted_installations(client, seeded):
    body = client.get(f"/app/pulls/{seeded['breaks']}").json()
    assert body["verdicts"] == [HTTPX]
    assert body["private"] is False and body["account_login"] == "acme"
    assert body["diff"]["changed"][0]["name"] == "httpx"
    assert client.get(f"/app/pulls/{seeded['private']}").json()["private"] is True
    assert client.get(f"/app/pulls/{seeded['gone']}").status_code == 404
    assert (
        client.get(f"/app/pulls/{seeded['breaks']}?installation=12").status_code == 404
    )
    assert client.get(f"/app/pulls/{uuid.uuid4()}").status_code == 404


@integration
def test_installation_scope_limits_installations_and_repository_pulls(client, seeded):
    scoped = client.get("/app/installations?installations=12&installations=13").json()
    assert [i["account_login"] for i in scoped["installations"]] == ["solo"]
    both = client.get("/app/installations?installations=11&installations=12").json()
    assert [i["id"] for i in both["installations"]] == [11, 12]
    assert (
        client.get("/app/repositories/acme/app/pulls?installations=12").status_code
        == 404
    )
    allowed = client.get(
        "/app/repositories/acme/app/pulls?installations=12&installations=11"
    ).json()
    assert allowed["repository"]["installation_id"] == 11
    assert len(allowed["pulls"]) == 3
