"""Upcoming-breakage scans: what queues them, when they are skipped, and who can read them.

Database tests use real Postgres in a disposable schema (CODEINTENT_RUN_INTEGRATION=1). The full scan
runs against the real public demo repository, GitHub and PyPI with CODEINTENT_RUN_NETWORK=1.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from codeintent import scans, store
from codeintent.api import app
from codeintent.github_app import handle_webhook

SECRET = "test-service-secret"
integration = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_INTEGRATION") != "1", reason="requires real Postgres"
)
network = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_NETWORK") != "1", reason="reads GitHub and PyPI"
)
SHA = "c" * 40


def test_projects_are_found_where_the_parser_reads_them():
    assert scans.projects(["README.md", "requirements.txt"]) == ["."]
    assert scans.projects(
        [
            "src/time/pyproject.toml",
            "src/fetch/pyproject.toml",
            "pyproject.toml",
            "requirements/dev.in",
        ]
    ) == [".", "src/fetch", "src/time"]
    assert scans.projects(["package.json", "src/app.ts"]) == []
    assert scans.projects([".github/requirements.txt", "node_modules/x/setup.py"]) == []


def test_alert_keys_name_versions_and_skip_withdrawn_advisories():
    item = {
        "package": "requests",
        "current": "2.31.0",
        "latest": "2.32.4",
        "verdict": {"verdict": "breaks"},
        "advisories": {
            "status": "advisories",
            "advisories": [
                {"id": "GHSA-9wx4-h78v-vm56"},
                {"id": "GHSA-old", "withdrawn": True},
            ],
        },
    }
    assert scans.alert_keys(item) == [
        ("breaks:requests@2.32.4", "breaks"),
        ("advisory:requests@2.31.0:GHSA-9wx4-h78v-vm56", "advisory"),
    ]
    assert (
        scans.alert_keys({"package": "idna", "verdict": {"verdict": "needs-change"}})
        == []
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


def jobs() -> list[dict]:
    with store.connection() as conn:
        return conn.execute(
            "SELECT queue_name,args,priority FROM procrastinate_jobs WHERE task_name='scan_repository' ORDER BY id"
        ).fetchall()


INSTALLATION = {"id": 21, "account": {"login": "acme", "type": "Organization"}}


def repo(full_name: str, ident: int) -> dict:
    return {"id": ident, "full_name": full_name, "private": False}


@integration
def test_install_and_added_repositories_queue_one_scan_each(schema):
    code, _ = handle_webhook(
        "installation",
        "d-1",
        {
            "action": "created",
            "installation": INSTALLATION,
            "repositories": [repo("acme/app", 1), repo("acme/web", 2)],
        },
    )
    assert code == 202
    handle_webhook(
        "installation_repositories",
        "d-2",
        {
            "action": "added",
            "installation": INSTALLATION,
            "repositories_added": [repo("acme/app", 1), repo("acme/cli", 3)],
            "repositories_removed": [],
        },
    )
    # acme/app was already queued: the second request is absorbed, not duplicated.
    assert [
        (j["queue_name"], j["args"]["repository"], j["priority"]) for j in jobs()
    ] == [
        ("scans", "acme/app", -10),
        ("scans", "acme/web", -10),
        ("scans", "acme/cli", -10),
    ]
    with store.connection() as conn:
        assert {
            r["repository"]: r["status"]
            for r in conn.execute("SELECT * FROM ci_repository_scans").fetchall()
        } == {"acme/app": "queued", "acme/web": "queued", "acme/cli": "queued"}


@integration
def test_only_merges_into_the_default_branch_rescan(schema):
    def merged(delivery: str, base: str, merged: bool = True):
        return handle_webhook(
            "pull_request",
            delivery,
            {
                "action": "closed",
                "number": 4,
                "installation": INSTALLATION,
                "repository": repo("acme/app", 1)
                | {
                    "default_branch": "main",
                    "owner": {"login": "acme", "type": "Organization"},
                },
                "pull_request": {
                    "merged": merged,
                    "base": {"ref": base, "sha": SHA},
                    "head": {"sha": SHA},
                },
            },
        )[1]

    assert merged("d-3", "feature")["status"] == "ignored"
    assert merged("d-4", "main", merged=False)["status"] == "ignored"
    assert merged("d-5", "main")["status"] == "rescan"
    assert [j["args"] for j in jobs()] == [
        {"installation_id": 21, "repository": "acme/app"}
    ]


class GitHubStub:
    """The three GitHub reads a scan makes before it downloads anything, as GitHub shapes them."""

    def __init__(self, paths: list[str], accessible: list[dict] | None = None):
        self.paths, self.calls, self.accessible = paths, [], accessible

    def get(self, path: str, params=None):
        request = httpx.Request("GET", "https://api.github.com" + path)
        if self.accessible is not None and not any(
            path == f"/repos/{r['full_name']}" for r in self.accessible
        ):
            return httpx.Response(404, json={"message": "Not Found"}, request=request)
        return httpx.Response(200, json=self.json(path, params), request=request)

    def json(self, path: str, params=None):
        self.calls.append(path)
        if path == "/installation/repositories":
            return {
                "total_count": len(self.accessible or []),
                "repositories": self.accessible or [],
            }
        if path.endswith("/branches/main"):
            return {"name": "main", "commit": {"sha": SHA}}
        if "/git/trees/" in path:
            return {
                "sha": SHA,
                "tree": [{"path": p, "type": "blob"} for p in self.paths],
            }
        return {"default_branch": "main", "archived": False}

    def token(self) -> str:
        raise AssertionError("nothing should be downloaded")


def watch(full_name: str = "acme/app"):
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_installations(id,account_login,account_type) VALUES (21,'acme','Organization') ON CONFLICT DO NOTHING"
        )
        conn.execute(
            "INSERT INTO ci_installation_repositories(installation_id,repository_id,full_name) VALUES (21,1,%s)",
            (full_name,),
        )


@integration
def test_repositories_without_python_manifests_are_skipped_without_download(schema):
    watch()
    stub = GitHubStub(["package.json", "src/index.ts"])
    assert scans.run(21, "acme/app", stub, None) == "skipped"
    with store.connection() as conn:
        row = conn.execute("SELECT * FROM ci_repository_scans").fetchone()
    assert (row["status"], row["error"], row["head_sha"]) == (
        "skipped",
        "no-python-manifests",
        SHA,
    )
    # Same commit, scanned recently: no tree read at all the second time.
    again = GitHubStub(["package.json"])
    assert scans.run(21, "acme/app", again, None) == "skipped"
    assert not any("/git/trees/" in c for c in again.calls)


@integration
def test_unwatched_repositories_drop_their_scan(schema):
    watch()
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_repository_scans(installation_id,repository,status) VALUES (21,'acme/gone','queued')"
        )
    assert scans.run(21, "acme/gone", GitHubStub([]), None) == "removed"
    with store.connection() as conn:
        assert not conn.execute(
            "SELECT 1 FROM ci_repository_scans WHERE repository='acme/gone'"
        ).fetchone()


@integration
def test_a_repository_gone_on_github_reconciles_the_installation(schema):
    """GitHub sent no removal webhook: the scan's 404 re-reads the list and drops what is gone."""
    watch()
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_installation_repositories(installation_id,repository_id,full_name) VALUES (21,2,'acme/old')"
        )
    demo = {"id": 3, "full_name": "acme/demo", "private": False}
    stub = GitHubStub(["requirements.txt"], accessible=[demo])
    assert scans.run(21, "acme/app", stub, None) == "removed"
    with store.connection() as conn:
        assert [
            r["full_name"]
            for r in conn.execute(
                "SELECT full_name FROM ci_installation_repositories ORDER BY full_name"
            ).fetchall()
        ] == ["acme/demo"]
        assert [
            r["repository"]
            for r in conn.execute(
                "SELECT repository FROM ci_repository_scans"
            ).fetchall()
        ] == ["acme/demo"]
    assert [j["args"]["repository"] for j in jobs()] == ["acme/demo"]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CODEINTENT_API_SECRET", SECRET)
    with TestClient(app, headers={"X-Api-Key": SECRET}) as test:
        yield test


@integration
def test_scan_results_are_scoped_to_the_callers_installations(schema, client):
    watch()
    item = {
        "package": "httpx",
        "current": "0.27.2",
        "latest": "0.28.1",
        "status": "compared",
        "location": {"file": "requirements.txt", "line": 1},
        "verdict": {
            "verdict": "breaks",
            "label": "Breaks you",
            "reason": "r",
            "findings": [{"locations": [{}, {}]}],
        },
    }
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_repository_scans(installation_id,repository,status,items,scanned_at) VALUES (21,'acme/app','done',%s,%s)",
            (Jsonb([item]), datetime.now(UTC)),
        )
    body = client.get("/app/repositories/acme/app/upcoming?installations=21").json()
    assert (
        body["scan"]["status"] == "done"
        and body["scan"]["items"][0]["package"] == "httpx"
    )
    assert (
        client.get("/app/repositories/acme/app/upcoming?installations=99").status_code
        == 404
    )
    summary = client.get("/app/upcoming?installations=21").json()
    assert summary["findings"][0] | {"scanned_at": None} == {
        "repository": "acme/app",
        "project": ".",
        "package": "httpx",
        "specifier": "",
        "lift": None,
        "current": "0.27.2",
        "latest": "0.28.1",
        "verdict": "breaks",
        "label": "Breaks you",
        "reason": "r",
        "places": 2,
        "advisories": [],
        "scanned_at": None,
    }
    assert client.get("/app/upcoming?installations=99").json()["findings"] == []
    listed = client.get("/app/installations/21/repositories").json()["repositories"][0]
    assert listed["upcoming"]["breaks"] == 1
    assert (
        client.post("/app/repositories/acme/app/scan?installations=99").status_code
        == 404
    )
    assert client.post("/app/repositories/acme/app/scan?installations=21").json() == {
        "status": "queued"
    }
    assert client.post("/app/repositories/acme/app/scan?installations=21").json() == {
        "status": "already-queued"
    }


class PublicGitHub:
    """Real GitHub reads with the developer's token; stands in for the installation client."""

    def __init__(self):
        from codeintent.upgrades.repository import token

        self.secret = token()
        self.http = httpx.Client(
            base_url="https://api.github.com",
            headers={"Authorization": f"Bearer {self.secret}"} if self.secret else {},
            timeout=30,
        )

    def get(self, path: str, params=None):
        return self.http.get(path, params=params)

    def json(self, path: str, params=None):
        response = self.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def token(self) -> str | None:
        return self.secret


@integration
@network
def test_demo_repository_scan_finds_the_breaking_httpx_release(schema):
    watch("Iam-shyamrathore/codeintent-demo")
    with httpx.Client(timeout=60, follow_redirects=True) as pypi:
        assert (
            scans.run(21, "Iam-shyamrathore/codeintent-demo", PublicGitHub(), pypi)
            == "done"
        )
    with store.connection() as conn:
        items = conn.execute("SELECT items FROM ci_repository_scans").fetchone()[
            "items"
        ]
    httpx_item = next(i for i in items if i["package"] == "httpx")
    assert httpx_item["current"] == "0.27.2"
    assert httpx_item["verdict"]["verdict"] == "breaks"
    locations = [
        (loc["file"], loc["line"])
        for f in httpx_item["verdict"]["findings"]
        for loc in f["locations"]
    ]
    assert ("weather/client.py", 12) in locations
    requests_item = next(i for i in items if i["package"] == "requests")
    assert requests_item["advisories"]["status"] == "advisories"
