"""The workspace graph: what a run turns into, and the cross-repository questions it answers.

``build`` is pure and tested anywhere. Projection and queries need Postgres and Neo4j
(CODEINTENT_RUN_INTEGRATION=1, as in CI); every test uses its own workspace ids and deletes them.
"""

from __future__ import annotations

import os
import random
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg import sql

from codeintent import runs, store, workspace_graph

integration = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_INTEGRATION") != "1", reason="requires Postgres and Neo4j"
)

# Trimmed from the demo repository's real scan (Iam-shyamrathore/codeintent-demo).
BREAKS = {
    "package": "httpx",
    "start": "0.27.2",
    "end": "0.28.1",
    "verdict": "breaks",
    "label": "Breaks you",
    "reason": "1 change(s) in httpx 0.28.1 break code you use, at 1 place(s)",
    "findings": [
        {
            "severity": "breaks",
            "guarded": False,
            "change": {
                "kind": "parameter-removed",
                "symbol": "httpx._client.Client",
                "parameter": "proxies",
                "detail": "httpx._client.Client accepts proxies= in 0.27.2 but not in 0.28.1",
                "replacement": "proxy= or mounts=",
            },
            "locations": [{"file": "weather/client.py", "line": 12}],
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
            "pr_title": "Introduce new `SSLContext` API & escalate deprecations.",
            "pr_url": "https://github.com/encode/httpx/pull/3319",
            "quotes": [
                {
                    "text": "The deprecated `proxies` argument has now been removed.",
                    "source_kind": "changelog",
                    "source_url": "https://github.com/encode/httpx/blob/master/CHANGELOG.md",
                }
            ],
            "deprecation": {
                "pr_number": 2879,
                "pr_url": "https://github.com/encode/httpx/pull/2879",
            },
        }
    ],
    "advisories": [],
}


def scan_result(verdict: dict | None, keywords: list[str], line: int = 12) -> dict:
    return {
        "items": [
            {
                "package": "httpx",
                "project": ".",
                "current": "0.27.2",
                "latest": "0.28.1",
                "status": "compared",
                "specifier": "==0.27.2",
                "location": {"file": "requirements.txt", "line": 1},
                "verdict": verdict,
            }
        ],
        "usages": {
            "httpx": [
                {
                    "symbol": "httpx.Client",
                    "kind": "call",
                    "keywords": keywords,
                    "file": "weather/client.py",
                    "line": line,
                }
            ]
        },
    }


def run_row(ws: int, repo: str, kind: str, result: dict) -> dict:
    return {
        "id": uuid.uuid4(),
        "installation_id": ws,
        "kind": kind,
        "repository": repo,
        "subject": "default branch",
        "status": "succeeded",
        "started_at": datetime.now(UTC),
        "result": result,
    }


def test_a_scan_becomes_usage_change_and_upstream_nodes():
    batch = workspace_graph.build(
        run_row(7, "acme/app", "scan", scan_result(BREAKS, ["timeout", "proxies"])),
        [],
        [],
        "acme",
        None,
    )
    names = {
        label: sorted(n.get("name", "") for n in rows.values())
        for label, rows in batch.nodes.items()
    }
    assert names["APIChange"] == ["httpx.Client(proxies=)"]
    assert names["Symbol"] == ["httpx.Client"]
    assert names["CodeLine"] == ["weather/client.py:12"]
    assert names["UpstreamPR"] == ["encode/httpx#2879", "encode/httpx#3319"]
    assert names["SourceRepo"] == ["encode/httpx"]
    kinds = {kind for (_, kind, _) in batch.rels}
    assert {
        "USES",
        "AFFECTS",
        "CAUSED_BY",
        "AT",
        "CHANGED_IN",
        "DEPRECATED_IN",
        "LOCKS",
        "DEPENDS_ON",
    } <= kinds
    for label, rows in batch.nodes.items():
        prefix = "pub|" if label in workspace_graph.PUBLIC else "7|"
        assert all(uid.startswith(prefix) for uid in rows), label
    assert "ws" not in next(iter(batch.nodes["APIChange"].values()))
    uses = next(iter(batch.rels[("CodeLine", "USES", "Symbol")].values()))["props"]
    assert uses["keywords"] == ["timeout", "proxies"]


def test_private_names_are_shown_as_users_import_them():
    assert workspace_graph.public("httpx._client.Client") == "httpx.Client"
    assert (
        workspace_graph.public("markupsafe.__init__.soft_unicode")
        == "markupsafe.__init__.soft_unicode"
    )


@pytest.fixture
def workspaces(monkeypatch):
    original = os.environ.get("DATABASE_URL") or pytest.skip("DATABASE_URL is not set")
    name = "ci_test_" + uuid.uuid4().hex
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    monkeypatch.setenv(
        "DATABASE_URL",
        psycopg.conninfo.make_conninfo(original, options=f"-c search_path={name}"),
    )
    store.migrate()
    a, b = random.randint(10**9, 2 * 10**9), random.randint(2 * 10**9 + 1, 3 * 10**9)
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_installations(id,account_login,account_type) VALUES (%s,'acme','Organization'),(%s,'other','User')",
            (a, b),
        )
    yield a, b
    from codeintent.graph import driver, run_query

    with driver() as db:
        run_query(db, "MATCH (n) WHERE n.ws IN $ws DETACH DELETE n", ws=[a, b])
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def recorded(ws: int, repo: str, result: dict) -> str:
    with runs.recorded(
        "scan", installation_id=ws, repository=repo, subject="default branch"
    ) as run:
        run.finish(result=result)
    workspace_graph.project(run.id)
    return run.id


@integration
def test_impact_finds_lines_no_run_compared_and_stays_in_its_workspace(workspaces):
    from codeintent.graph import driver

    a, b = workspaces
    # acme/app compared httpx 0.28.1 and broke; acme/cli passes proxies= too but never compared it.
    recorded(a, "acme/app", scan_result(BREAKS, ["proxies"]))
    recorded(a, "acme/cli", scan_result(None, ["proxies"], line=40) | {"items": []})
    recorded(a, "acme/docs", scan_result(None, ["timeout"], line=5) | {"items": []})
    recorded(b, "other/secret", scan_result(BREAKS, ["proxies"]))
    with driver() as db:
        lines = workspace_graph.impact(db, a, "httpx", "0.28.1")
        uses = workspace_graph.usages(db, a, "httpx", "httpx.Client")
    assert [(r["repository"], r["line"], r["confirmed"]) for r in lines] == [
        ("acme/app", 12, True),
        ("acme/cli", 40, False),
    ]
    assert lines[0]["replacement"] == "proxy= or mounts="
    assert {u["repository"] for u in uses} == {"acme/app", "acme/cli", "acme/docs"}


@integration
def test_a_later_scan_removes_uses_the_code_no_longer_has(workspaces):
    from codeintent.graph import driver

    a, _ = workspaces
    recorded(a, "acme/app", scan_result(BREAKS, ["proxies"]))
    recorded(a, "acme/app", scan_result(None, []) | {"usages": {}})
    with driver() as db:
        assert workspace_graph.usages(db, a, "httpx") == []
        assert workspace_graph.impact(db, a, "httpx", "0.28.1") == []


@integration
def test_run_graph_draws_the_why_chain(workspaces):
    from codeintent.graph import driver

    a, _ = workspaces
    run_id = recorded(a, "acme/app", scan_result(BREAKS, ["proxies"]))
    with driver() as db:
        drawn = workspace_graph.run_graph(db, a, run_id)
    labels = {n["label"] for n in drawn["nodes"]}
    assert {
        "Run",
        "Repository",
        "Upgrade",
        "Finding",
        "CodeLine",
        "APIChange",
        "UpstreamPR",
    } <= labels
    assert {"CHECKED", "FOUND", "AT", "CAUSED_BY", "CHANGED_IN"} <= {
        e["type"] for e in drawn["edges"]
    }
    with store.connection() as conn:
        assert conn.execute(
            "SELECT projected_at FROM ci_runs WHERE id=%s", (run_id,)
        ).fetchone()["projected_at"]


@integration
def test_agents_and_telegram_ask_the_same_graph(workspaces, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    from codeintent import mcp_server, telegram

    a, b = workspaces
    recorded(a, "acme/app", scan_result(BREAKS, ["proxies"]))
    recorded(a, "acme/cli", scan_result(None, ["proxies"], line=40) | {"items": []})
    with pytest.raises(ToolError):
        mcp_server.impact("httpx", "0.28.1")  # no workspace token
    reset = mcp_server._installation.set(a)
    try:
        answer = mcp_server.impact("httpx", "0.28.1")
        uses = mcp_server.who_uses("httpx", "httpx.Client")
    finally:
        mcp_server._installation.reset(reset)
    assert answer.repositories == ["acme/app", "acme/cli"]
    assert [line.confirmed for line in answer.lines] == [True, False]
    assert {u.repository for u in uses.uses} == {"acme/app", "acme/cli"}

    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_telegram_chats(chat_id,installation_id) VALUES (555,%s)",
            (a,),
        )
    monkeypatch.setenv("CODEINTENT_PUBLIC_URL", "https://codeintent.example")
    text = telegram.impact(555, "httpx 0.28.1")
    assert "2 line(s) in 2 repositories" in text
    assert "weather/client.py:40" in text and "found through the graph" in text
    assert telegram.impact(556, "httpx") == telegram.NOT_LINKED
    assert "not a Python package" in telegram.impact(555, "httpx <script>")


# --- The code map in the graph, and the PR check's questions -------------------------------------


@pytest.fixture
def mapped(tmp_path, monkeypatch) -> dict:
    from test_codemap import FILES

    from codeintent import codemap

    monkeypatch.setenv("CODEINTENT_ARTIFACT_CACHE", str(tmp_path / "cache"))
    for name, text in FILES.items():
        path = tmp_path / "repo" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.lstrip("\n"))
    root = tmp_path / "repo"
    return codemap.build(root, codemap.dependencies_of(root))


def test_a_code_map_becomes_files_imports_functions_calls_and_uses(mapped):
    batch = workspace_graph.map_batch(7, "acme/app", mapped, "2026-01-01T00:00:00")
    kinds = {kind for (_, kind, _) in batch.rels}
    assert {"CONTAINS", "IMPORTS", "DEFINES", "CALLS", "USES", "INSIDE"} <= kinds
    functions = {n["qualname"]: n for n in batch.nodes["Function"].values()}
    assert functions["users"]["entry"] == "GET /users"
    assert all(uid.startswith("7|") for uid in batch.nodes["Function"])
    inside = batch.rels[("CodeLine", "INSIDE", "Function")]
    assert (
        "7|CodeLine|acme/app|src/app/client.py|5",
        "7|Function|acme/app|src/app/client.py:make",
    ) in inside


def store_map(ws: int, repo: str, mapped: dict) -> None:
    from psycopg.types.json import Jsonb

    with store.connection() as conn:
        conn.execute(
            """INSERT INTO ci_code_maps(installation_id,repository,sha,map) VALUES(%s,%s,'abc',%s)
            ON CONFLICT(installation_id,repository) DO UPDATE SET map=EXCLUDED.map,built_at=now()""",
            (ws, repo, Jsonb(mapped)),
        )
    workspace_graph.project_map(ws, repo)


def lock_chain(ws: int, repo: str) -> None:
    from codeintent.graph import driver

    b = workspace_graph.Batch(ws)
    httpx_, httpcore, h11 = (
        b.release("httpx", "0.27.2"),
        b.release("httpcore", "1.0.7"),
        b.release("h11", "0.14.0"),
    )
    b.rel("LOCKS", b.repository(repo), httpx_, direct=True)
    b.rel("DEPENDS_ON", httpx_, httpcore)
    b.rel("DEPENDS_ON", httpcore, h11)
    with driver() as db:
        workspace_graph.write(db, b)


@integration
def test_reach_finds_own_uses_and_chains_through_other_packages(workspaces, mapped):
    from codeintent.graph import driver

    a, b = workspaces
    store_map(a, "acme/app", mapped)
    lock_chain(a, "acme/app")
    with driver() as db:
        own = workspace_graph.reach(db, a, "acme/app", "httpx")
        through = workspace_graph.reach(db, a, "acme/app", "h11")
        other = workspace_graph.reach(db, b, "acme/app", "httpx")
    assert "src/app/client.py" in own["files"]
    assert next(r for r in own["lines"] if r["line"] == 5)["function"] == "make"
    assert through["uses"] == 0
    assert through["through"][0]["chain"] == [
        "httpx@0.27.2",
        "httpcore@1.0.7",
        "h11@0.14.0",
    ]
    assert through["through"][0]["uses"] >= 1
    assert other["uses"] == 0 and other["through"] == []


@integration
def test_blast_follows_a_broken_line_to_callers_routes_and_tests(workspaces, mapped):
    from codeintent.graph import driver

    a, b = workspaces
    store_map(a, "acme/app", mapped)
    place = [{"file": "src/app/client.py", "line": 5}]
    with driver() as db:
        [found] = workspace_graph.blast(db, a, "acme/app", place)
        assert workspace_graph.blast(db, b, "acme/app", place)[0]["function"] is None
    assert found["function"] == "make"
    callers = {(c["function"], c["depth"]) for c in found["callers"]}
    assert {("users", 1), ("Session.__init__", 1), ("main", 2)} <= callers
    assert "GET /users" in {e["name"] for e in found["entry_points"]}
    assert found["tests"] == ["tests/test_client.py"]
    assert "src/app/api.py" in {i["file"] for i in found["importers"]}


@integration
def test_a_new_map_replaces_calls_and_imports_the_code_no_longer_has(
    workspaces, mapped
):
    from codeintent.graph import driver

    a, _ = workspaces
    store_map(a, "acme/app", mapped)
    trimmed = {
        **mapped,
        "imports": [i for i in mapped["imports"] if i["file"] != "src/app/api.py"],
        "calls": [
            c for c in mapped["calls"] if not c["caller"].startswith("src/app/api.py")
        ],
        "functions": [f for f in mapped["functions"] if f["file"] != "src/app/api.py"],
    }
    store_map(a, "acme/app", trimmed)
    with driver() as db:
        [found] = workspace_graph.blast(
            db, a, "acme/app", [{"file": "src/app/client.py", "line": 5}]
        )
    assert "users" not in {c["function"] for c in found["callers"]}
    assert "src/app/api.py" not in {i["file"] for i in found["importers"]}


@integration
def test_fix_brief_hands_the_agent_every_edit_with_what_depends_on_it(
    workspaces, mapped
):
    from mcp.server.mcpserver.exceptions import ToolError

    from codeintent import mcp_server
    from codeintent.graph import driver

    a, b = workspaces
    store_map(a, "acme/app", mapped)
    verdict = {
        **BREAKS,
        "findings": [
            {
                **BREAKS["findings"][0],
                "locations": [{"file": "src/app/client.py", "line": 5}],
            }
        ],
    }
    with driver() as db:
        traced = {
            "httpx": {
                "reach": workspace_graph.reach(db, a, "acme/app", "httpx"),
                "blast": workspace_graph.blast(
                    db, a, "acme/app", [{"file": "src/app/client.py", "line": 5}]
                ),
            }
        }
    with runs.recorded(
        "pull", installation_id=a, repository="acme/app", subject="#12", ref="deadbeef"
    ) as run:
        run.finish(
            summary={"verdict": "breaks"},
            result={"verdicts": [verdict], "graph": traced},
        )
    reset = mcp_server._installation.set(a)
    try:
        brief = mcp_server.fix_brief("acme/app", 12)
    finally:
        mcp_server._installation.reset(reset)
    [upgrade] = brief.upgrades
    [edit] = upgrade.edits
    assert (edit.file, edit.line, edit.function) == ("src/app/client.py", 5, "make")
    assert edit.change.replacement == "proxy= or mounts="
    assert edit.upstream_pr == "https://github.com/encode/httpx/pull/3319"
    assert {"GET /users", "scripts/run.py"} <= set(edit.entry_points)
    assert brief.tests_to_run == ["tests/test_client.py"]
    assert brief.steps[-1] == "Run tests/test_client.py"
    reset = mcp_server._installation.set(b)
    try:
        with pytest.raises(ToolError):
            mcp_server.fix_brief("acme/app", 12)  # another workspace's PR
    finally:
        mcp_server._installation.reset(reset)
