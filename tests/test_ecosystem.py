"""The public ecosystem graph, built from recorded deps.dev answers for httpx 0.28.1 (fetched on 22 Nov 2026).

``build_release`` is pure. The queries run against Postgres and Neo4j (CODEINTENT_RUN_INTEGRATION=1, as in CI).
"""

from __future__ import annotations

import json
import os
import random
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from codeintent import ecosystem, store, workspace_graph
from codeintent.upgrades.advisories import AdvisoryCheck

FIXTURES = Path(__file__).parent / "fixtures" / "ecosystem"
INFO = json.loads((FIXTURES / "httpx-0.28.1.json").read_text())
TREE = json.loads((FIXTURES / "httpx-0.28.1-dependencies.json").read_text())
PROJECT = json.loads((FIXTURES / "github-encode-httpx.json").read_text())
FACTS = {
    "stars": PROJECT["starsCount"],
    "license": PROJECT["license"],
    "scorecard": PROJECT["scorecard"]["overallScore"],
}
# A made-up advisory on h11 0.16.0, so exposure through httpcore can be traced.
H11 = AdvisoryCheck.model_validate(
    {
        "package": "h11",
        "version": "0.16.0",
        "status": "advisories",
        "advisories": [
            {
                "id": "TEST-h11-0001",
                "summary": "Test advisory",
                "fixed": "0.17.0",
                "source": "test",
                "url": "https://osv.dev/vulnerability/TEST-h11-0001",
            }
        ],
    }
)


def test_a_release_becomes_its_resolved_tree_and_source_repository():
    batch, found = ecosystem.build_release("httpx", "0.28.1", INFO, TREE, FACTS, [H11])
    assert sorted(found) == [
        ("anyio", "4.16.0"),
        ("certifi", "2026.10.23"),
        ("h11", "0.16.0"),
        ("httpcore", "1.0.9"),
        ("httpx", "0.28.1"),
        ("idna", "3.20.0"),
        ("typing-extensions", "4.16.0"),
    ]
    edges = batch.rels[("Release", "DEPENDS_ON", "Release")]
    pairs = {(a.split("|")[-1], b.split("|")[-1]) for a, b in edges}
    assert ("httpcore@1.0.9", "h11@0.16.0") in pairs
    assert len(pairs) == 8
    assert edges[("pub|Release|httpx@0.28.1", "pub|Release|httpcore@1.0.9")][
        "props"
    ] == {"requirement": "==1.*"}
    source = batch.nodes["SourceRepo"]["pub|SourceRepo|encode/httpx"]
    assert (source["stars"], source["scorecard"]) == (15788, 4.9)
    assert (
        batch.nodes["Release"]["pub|Release|httpx@0.28.1"]["license"] == "BSD-3-Clause"
    )
    assert all(uid.startswith("pub|") for rows in batch.nodes.values() for uid in rows)


def test_github_links_are_read_as_owner_and_name():
    assert ecosystem._github("https://github.com/encode/httpx.git/") == "encode/httpx"
    assert ecosystem._github("https://gitlab.com/x/y") is None


integration = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_INTEGRATION") != "1", reason="requires Postgres and Neo4j"
)


@pytest.fixture
def world(monkeypatch):
    """httpx 0.28.1's tree in the graph, and one workspace repository that locks httpx and h11."""
    from codeintent.graph import driver

    original = os.environ.get("DATABASE_URL") or pytest.skip("DATABASE_URL is not set")
    name = "ci_test_" + uuid.uuid4().hex
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    monkeypatch.setenv(
        "DATABASE_URL",
        psycopg.conninfo.make_conninfo(original, options=f"-c search_path={name}"),
    )
    store.migrate()
    ws = random.randint(3 * 10**9, 4 * 10**9)
    batch, _ = ecosystem.build_release("httpx", "0.28.1", INFO, TREE, FACTS, [H11])
    repo = workspace_graph.Batch(ws)
    repository = repo.repository("acme/app")
    for package, version, direct in (
        ("httpx", "0.28.1", True),
        ("h11", "0.16.0", False),
    ):
        repo.rel("LOCKS", repository, repo.release(package, version), direct=direct)
    seeded = workspace_graph.Batch(0)
    project = seeded.source_repo("example/cli", stars=10, seeded=True)
    seeded.rel("LOCKS", project, seeded.release("httpcore", "1.0.9"), direct=True)
    with driver() as db:
        workspace_graph.schema(db)
        for b in (batch, repo, seeded):
            workspace_graph.write(db, b)
        yield db, ws
        from codeintent.graph import run_query

        run_query(db, "MATCH (n {ws: $ws}) DETACH DELETE n", ws=ws)
        run_query(db, "MATCH (n:SourceRepo {name: 'example/cli'}) DETACH DELETE n")
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


@integration
def test_why_a_transitive_package_is_installed(world):
    db, ws = world
    assert ecosystem.why(db, ws, "acme/app", "h11") == [
        ["httpx@0.28.1", "httpcore@1.0.9", "h11@0.16.0"]
    ]
    assert ecosystem.why(db, ws, "acme/app", "httpx") == [["httpx@0.28.1"]]


@integration
def test_the_tree_and_the_advisories_it_brings_in(world):
    db, ws = world
    found = ecosystem.tree(db, ws, "acme/app", depth=3)
    ids = {n["id"] for n in found["nodes"]}
    assert {"httpx@0.28.1", "httpcore@1.0.9", "h11@0.16.0", "anyio@4.16.0"} <= ids
    assert {"source": "httpcore@1.0.9", "target": "h11@0.16.0"} in found["edges"]
    assert (
        next(n for n in found["nodes"] if n["id"] == "httpx@0.28.1")["direct"] is True
    )
    (exposed,) = [
        e for e in ecosystem.exposure(db, ws) if e["advisory"] == "TEST-h11-0001"
    ]
    assert (exposed["package"], exposed["direct"], exposed["fixed"]) == (
        "h11",
        False,
        "0.17.0",
    )
    assert exposed["pulled_in_by"] == ["httpx"]


@integration
def test_dependents_span_your_repositories_and_open_source_projects(world):
    db, ws = world
    found = ecosystem.package(db, ws, "h11")
    by_name = {d["name"]: d for d in found["dependents"]}
    assert by_name["acme/app"]["hops"] == 0  # locks h11 itself
    assert by_name["example/cli"]["kind"] == "SourceRepo"
    assert by_name["example/cli"]["hops"] == 1
    assert "httpcore" in found["needed_by"]
    assert found["advisories"][0]["name"] == "TEST-h11-0001"
    other = ecosystem.package(db, ws + 1, "h11")
    assert "acme/app" not in {d["name"] for d in other["dependents"]}
    assert ecosystem.package(db, ws, "httpx")["source"]["name"] == "encode/httpx"


def test_scans_record_every_locked_release(tmp_path):
    from codeintent import scans

    (tmp_path / "requirements.txt").write_text("httpx==0.28.1\nh11==0.16.0\n")
    locked = scans._locked(tmp_path)
    assert [(e["package"], e["version"]) for e in locked] == [
        ("h11", "0.16.0"),
        ("httpx", "0.28.1"),
    ]


@pytest.fixture
def ledger(monkeypatch):
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


def jobs() -> list[str]:
    with store.connection() as conn:
        return sorted(
            r["queueing_lock"]
            for r in conn.execute(
                "SELECT queueing_lock FROM procrastinate_jobs WHERE task_name='index_release' AND status='todo'"
            ).fetchall()
        )


@integration
def test_every_queued_release_gets_exactly_one_job_even_after_a_lost_one(ledger):
    assert ecosystem.queue([("httpx", "0.28.1"), ("h11", "0.16.0")]) == 2
    assert ecosystem.queue([("httpx", "0.28.1")]) == 0  # already waiting
    assert jobs() == ["eco:h11@0.16.0", "eco:httpx@0.28.1"]
    # A row marked queued whose job was lost: asking again, or the sweep, queues it.
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_ecosystem_releases(package,version) VALUES ('idna','3.20.0')"
        )
    assert ecosystem.sweep() == 1
    assert ecosystem.queue([("idna", "3.20.0")]) == 0
    assert jobs() == ["eco:h11@0.16.0", "eco:httpx@0.28.1", "eco:idna@3.20.0"]
