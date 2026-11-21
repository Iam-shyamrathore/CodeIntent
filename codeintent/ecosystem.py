"""The public ecosystem graph: Python packages, their releases, the resolved dependency tree between releases,
the open-source repositories behind them, and their known advisories. All of it is public data.

    (:Package)-[:HAS_RELEASE]->(:Release)-[:DEPENDS_ON {requirement}]->(:Release)
    (:SourceRepo)-[:PUBLISHES]->(:Package)        (:Advisory)-[:AFFECTS]->(:Release)
    (:SourceRepo)-[:REQUIRES {specifier}]->(:Package)   (:SourceRepo)-[:LOCKS]->(:Release)   (seeded projects)
    (:Repository)-[:LOCKS {direct}]->(:Release)   (workspace repositories, from workspace_graph)

Sources: deps.dev (Google Open Source Insights) for resolved dependency graphs, source links and repository
facts such as stars and OpenSSF Scorecard; OSV.dev for advisories. Every release in a resolved tree is indexed
in turn, so the graph grows to the full transitive closure of whatever is watched or seeded.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from codeintent import store
from codeintent.workspace_graph import Batch

logger = logging.getLogger(__name__)
DEPS_DEV = "https://api.deps.dev/v3"
FRESH = timedelta(days=7)
MAX_TREE = 400
MAX_MANIFEST_BYTES = 2_000_000


def _get(http: httpx.Client, path: str) -> dict | None:
    response = http.get(f"{DEPS_DEV}{path}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _github(url: str | None) -> str | None:
    """``owner/name`` for a github.com URL, else None."""
    if not url or "github.com/" not in url:
        return None
    parts = url.split("github.com/", 1)[1].strip("/").removesuffix(".git").split("/")
    return (
        f"{parts[0]}/{parts[1]}" if len(parts) >= 2 and parts[0] and parts[1] else None
    )


def repository_facts(http: httpx.Client, name: str) -> dict:
    """Stars, forks, licence, description and OpenSSF Scorecard for a public GitHub repository."""
    data = _get(http, f"/projects/{quote('github.com/' + name, safe='')}") or {}
    card = data.get("scorecard") or {}
    checks = {c.get("name"): c.get("score") for c in card.get("checks") or []}
    return {
        "stars": data.get("starsCount"),
        "forks": data.get("forksCount"),
        "open_issues": data.get("openIssuesCount"),
        "license": data.get("license"),
        "description": (data.get("description") or "")[:300] or None,
        "scorecard": card.get("overallScore"),
        "maintained": checks.get("Maintained"),
    }


def pick_version(http: httpx.Client, package: str, specifier: str) -> str | None:
    """The newest final release that satisfies ``specifier`` (the default release when unconstrained)."""
    data = (
        _get(http, f"/systems/pypi/packages/{quote(canonicalize_name(package))}") or {}
    )
    try:
        allowed = SpecifierSet(specifier or "")
    except InvalidSpecifier:
        allowed = SpecifierSet()
    best = None
    for item in data.get("versions") or []:
        text = (item.get("versionKey") or {}).get("version")
        try:
            version = Version(text)
        except (InvalidVersion, TypeError):
            continue
        if version.is_prerelease or not allowed.contains(version, prereleases=False):
            continue
        if best is None or version > best:
            best = version
    return str(best) if best else None


def build_release(
    package: str,
    version: str,
    info: dict | None,
    tree: dict | None,
    facts: dict | None,
    checks: list,
) -> tuple[Batch, list[tuple[str, str]]]:
    """Nodes for one release, its resolved tree and its source repository. Also returns the tree's releases."""
    b = Batch(0)
    root = b.release(package, version)
    props = b.nodes["Release"][root[1]]
    if info:
        props.update(
            {
                "published": info.get("publishedAt"),
                "license": ", ".join(info.get("licenses") or []) or None,
                "deprecated": bool((info.get("deprecatedReason") or "").strip())
                or None,
            }
        )
        repo = next(
            (
                _github(link.get("url"))
                for link in info.get("links") or []
                if link.get("label") == "SOURCE_REPO" and _github(link.get("url"))
            ),
            None,
        )
        if repo:
            source = b.source_repo(
                repo, **{k: v for k, v in (facts or {}).items() if v is not None}
            )
            b.rel(
                "PUBLISHES",
                source,
                ("Package", b.node("Package", package, name=package)),
            )
    found: list[tuple[str, str]] = []
    if tree:
        nodes = tree.get("nodes") or []
        keys = []
        for node in nodes[:MAX_TREE]:
            key = node.get("versionKey") or {}
            name, at = canonicalize_name(key.get("name") or ""), key.get("version")
            keys.append(b.release(name, at) if name and at else None)
            if name and at:
                found.append((name, at))
        for edge in tree.get("edges") or []:
            a, z = edge.get("fromNode"), edge.get("toNode")
            if a is None or z is None or a >= len(keys) or z >= len(keys):
                continue
            if keys[a] and keys[z] and keys[a] != keys[z]:
                b.rel(
                    "DEPENDS_ON",
                    keys[a],
                    keys[z],
                    requirement=edge.get("requirement") or None,
                )
    for check in checks:
        b.advisories(check.model_dump(mode="json"))
    return b, found


def index_release(package: str, version: str, http: httpx.Client) -> dict:
    """Fetch and write one release's resolved tree, source repository and advisories; queue the tree."""
    from codeintent import graph, workspace_graph
    from codeintent.upgrades import advisories as osv

    package = canonicalize_name(package)
    path = f"/systems/pypi/packages/{quote(package)}/versions/{quote(version)}"
    info = _get(http, path)
    if info is None:
        _mark(package, version, "not-found")
        return {"status": "not-found"}
    tree = _get(http, f"{path}:dependencies")
    repo = next(
        (
            _github(link.get("url"))
            for link in info.get("links") or []
            if link.get("label") == "SOURCE_REPO" and _github(link.get("url"))
        ),
        None,
    )
    facts = repository_facts(http, repo) if repo else None
    pairs = [
        (
            canonicalize_name((n.get("versionKey") or {}).get("name") or ""),
            (n.get("versionKey") or {}).get("version"),
        )
        for n in (tree or {}).get("nodes") or []
    ]
    pairs = [(n, v) for n, v in pairs if n and v][:MAX_TREE]
    checks = osv.check(pairs or [(package, version)], http)
    batch, found = build_release(package, version, info, tree, facts, checks)
    with graph.driver() as db:
        workspace_graph.schema(db)
        counts = workspace_graph.write(db, batch)
    _mark(package, version, "indexed", dependencies=max(len(found) - 1, 0))
    queue([(n, v) for n, v in found if (n, v) != (package, version)])
    return {"status": "indexed", **counts, "tree": len(found)}


def _mark(
    package: str, version: str, status: str, *, dependencies=None, error=None
) -> None:
    with store.connection() as conn:
        conn.execute(
            """INSERT INTO ci_ecosystem_releases(package,version,status,dependencies,error,indexed_at)
            VALUES (%s,%s,%s,%s,%s,CASE WHEN %s IN ('indexed','not-found') THEN now() END)
            ON CONFLICT(package,version) DO UPDATE SET status=EXCLUDED.status,dependencies=EXCLUDED.dependencies,
              error=EXCLUDED.error,indexed_at=coalesce(EXCLUDED.indexed_at,ci_ecosystem_releases.indexed_at)""",
            (package, version, status, dependencies, error, status),
        )


def queue(pairs: list[tuple[str, str]]) -> int:
    """Queue releases not indexed in the last week (or ever). Returns how many were queued."""
    from codeintent.tasks import index_release as task

    pairs = sorted({(canonicalize_name(n), v) for n, v in pairs if n and v})
    if not pairs:
        return 0
    queued = 0
    with store.connection() as conn:
        stale = conn.execute(
            """INSERT INTO ci_ecosystem_releases(package,version)
            SELECT * FROM unnest(%s::text[],%s::text[])
            ON CONFLICT(package,version) DO UPDATE SET requested_at=now()
              WHERE ci_ecosystem_releases.status='failed'
                 OR (ci_ecosystem_releases.status='indexed' AND ci_ecosystem_releases.indexed_at < now()-%s::interval)
            RETURNING package,version""",
            ([n for n, _ in pairs], [v for _, v in pairs], f"{FRESH.days} days"),
        ).fetchall()
        for row in stale:
            try:
                with conn.transaction():
                    task.configure(
                        connection=conn,
                        queueing_lock=f"eco:{row['package']}@{row['version']}",
                        priority=-20,
                    ).defer(package=row["package"], version=row["version"])
                queued += 1
            except Exception as exc:  # AlreadyEnqueued, or the queue being unavailable
                logger.debug("Not queued (%s)", type(exc).__name__)
    return queued


# --- Seeded open-source projects -------------------------------------------------------------------


def seed_project(full_name: str, client, http: httpx.Client) -> dict:
    """Read a public GitHub project's manifests (only those files) and add what it depends on to the graph.

    ``client`` is a ``github_app.Client`` (any installation token reads public repositories).
    """
    from codeintent import graph, scans, workspace_graph
    from codeintent.github_app import manifest_root
    from codeintent.upgrades import manifests
    from codeintent.upgrades.upcoming import _exact

    meta = client.json(f"/repos/{full_name}")
    if meta.get("private"):
        raise ValueError("only public repositories are seeded")
    branch = meta["default_branch"]
    sha = client.json(f"/repos/{full_name}/branches/{branch}")["commit"]["sha"]
    tree = client.json(f"/repos/{full_name}/git/trees/{sha}", params={"recursive": "1"})
    paths = [e["path"] for e in tree.get("tree") or [] if e.get("type") == "blob"]
    roots = scans.projects(paths)
    wanted = [
        p
        for p in paths
        if manifest_root(p) in roots
        and not any(part.startswith(".") for part in p.split("/")[:-1])
        and next((e.get("size") or 0 for e in tree["tree"] if e["path"] == p), 0)
        <= MAX_MANIFEST_BYTES
    ]
    b = Batch(0)
    source = b.source_repo(
        meta["full_name"],
        stars=meta.get("stargazers_count"),
        description=(meta.get("description") or "")[:300] or None,
        seeded=True,
        ref=sha,
    )
    pairs: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="codeintent-seed-") as folder:
        root = Path(folder)
        for path in wanted:
            text = client.file_text(full_name, path, sha)
            if text is None:
                continue
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        for project in roots:
            found = manifests.scan(
                root if project == "." else root / project
            ).dependencies
            exact = {canonicalize_name(d.name): _exact(d) for d in found if _exact(d)}
            for dep in found:
                if dep.source != "registry":
                    continue
                name = canonicalize_name(dep.name)
                pkg = ("Package", b.node("Package", name, name=name))
                if dep.direct and not dep.constraint_only:
                    b.rel(
                        "REQUIRES",
                        source,
                        pkg,
                        specifier=dep.specifier or None,
                        file=(f"{project}/" if project != "." else "")
                        + dep.location.file,
                        line=dep.location.line,
                        group=dep.group,
                    )
                version = exact.get(name) or (
                    pick_version(http, name, dep.specifier) if dep.direct else None
                )
                if version:
                    b.rel(
                        "LOCKS",
                        source,
                        b.release(name, version),
                        direct=dep.direct,
                        resolved="lock" if name in exact else "newest allowed",
                    )
                    pairs.append((name, version))
    with graph.driver() as db:
        workspace_graph.schema(db)
        counts = workspace_graph.write(db, b)
    queued = queue(pairs)
    with store.connection() as conn:
        conn.execute(
            """INSERT INTO ci_ecosystem_projects(full_name,status,ref,dependencies,indexed_at)
            VALUES (%s,'indexed',%s,%s,now()) ON CONFLICT(full_name) DO UPDATE SET
              status='indexed',ref=EXCLUDED.ref,dependencies=EXCLUDED.dependencies,error=NULL,indexed_at=now()""",
            (full_name, sha, len(set(pairs))),
        )
    return {**counts, "releases": len(set(pairs)), "queued": queued}


# --- Questions the product asks --------------------------------------------------------------------


def tree(db, ws: int, repository: str, depth: int = 4) -> dict:
    """A workspace repository's dependency graph: what it locks, and what those releases pull in."""
    from codeintent.graph import run_query

    depth = max(1, min(depth, 6))
    records = run_query(
        db,
        f"""MATCH (r:Repository {{uid: $uid}})-[l:LOCKS]->(d:Release)
        OPTIONAL MATCH p = (d)-[:DEPENDS_ON*1..{depth}]->(:Release)
        WITH r, l, d, collect(p)[..60] AS paths
        RETURN d.package AS package, d.version AS version, coalesce(l.direct, true) AS direct,
          [p IN paths | [n IN nodes(p) | n.package + '@' + n.version]] AS chains""",
        uid=f"{ws}|Repository|{repository.lower()}",
    ).records
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str]] = set()
    for row in records:
        key = f"{row['package']}@{row['version']}"
        nodes.setdefault(
            key,
            {
                "id": key,
                "package": row["package"],
                "version": row["version"],
                "direct": False,
            },
        )
        nodes[key]["direct"] = nodes[key]["direct"] or bool(row["direct"])
        for chain in row["chains"]:
            for a, z in zip(chain, chain[1:]):
                for item in (a, z):
                    name, _, at = item.rpartition("@")
                    nodes.setdefault(
                        item,
                        {"id": item, "package": name, "version": at, "direct": False},
                    )
                edges.add((a, z))
    return {
        "repository": repository,
        "nodes": sorted(nodes.values(), key=lambda n: (not n["direct"], n["package"])),
        "edges": [{"source": a, "target": z} for a, z in sorted(edges)],
    }


def why(db, ws: int, repository: str, package: str) -> list[list[str]]:
    """The shortest chains from a repository's direct dependencies to ``package``: why it is installed."""
    from codeintent.graph import run_query

    records = run_query(
        db,
        """MATCH (r:Repository {uid: $uid})-[l:LOCKS]->(d:Release) WHERE coalesce(l.direct, true)
        MATCH (t:Release {package: $package})
        MATCH p = shortestPath((d)-[:DEPENDS_ON*0..8]->(t))
        RETURN [n IN nodes(p) | n.package + '@' + n.version] AS chain
        ORDER BY length(p) LIMIT 5""",
        uid=f"{ws}|Repository|{repository.lower()}",
        package=canonicalize_name(package),
    ).records
    return [r["chain"] for r in records]


def exposure(db, ws: int) -> list[dict]:
    """Known advisories on any release a workspace repository locks, with what pulls it in."""
    from codeintent.graph import run_query

    records = run_query(
        db,
        """MATCH (r:Repository {ws: $ws})-[l:LOCKS]->(v:Release)<-[:AFFECTS]-(a:Advisory)
        OPTIONAL MATCH (r)-[ld:LOCKS]->(d:Release)-[:DEPENDS_ON*1..6]->(:Release {package: v.package})
        WHERE coalesce(ld.direct, true) AND d <> v
        RETURN r.name AS repository, v.package AS package, v.version AS version,
          coalesce(l.direct, true) AS direct, a.name AS advisory, a.summary AS summary,
          a.severity AS severity, a.fixed AS fixed, a.url AS url,
          collect(DISTINCT d.package)[..5] AS pulled_in_by
        ORDER BY repository, package, advisory""",
        ws=ws,
    ).records
    return [dict(r) for r in records]


def package(db, ws: int, name: str) -> dict:
    """One package in the ecosystem: its source repository, releases, what it needs, who needs it, advisories,
    the API changes found in it, and which of your repositories and seeded projects depend on it."""
    from codeintent.graph import run_query

    name = canonicalize_name(name)
    row = run_query(
        db,
        """MATCH (p:Package {name: $name})
        OPTIONAL MATCH (s:SourceRepo)-[:PUBLISHES]->(p)
        OPTIONAL MATCH (p)-[:HAS_RELEASE]->(rel:Release)
        WITH p, s, collect(DISTINCT rel) AS releases
        OPTIONAL MATCH (p)-[:HAS_RELEASE]->(:Release)-[:DEPENDS_ON]->(dep:Release)
        WITH p, s, releases, collect(DISTINCT dep.package) AS needs
        OPTIONAL MATCH (other:Release)-[:DEPENDS_ON]->(:Release {package: $name})
        WITH p, s, releases, needs, collect(DISTINCT other.package) AS needed_by
        OPTIONAL MATCH (a:Advisory)-[:AFFECTS]->(:Release {package: $name})
        WITH p, s, releases, needs, needed_by, collect(DISTINCT a {.name, .summary, .severity, .fixed, .url}) AS advisories
        OPTIONAL MATCH (c:APIChange {package: $name})
        RETURN s {.name, .url, .stars, .forks, .license, .scorecard, .maintained, .description} AS source,
          [r IN releases | r.version] AS versions, needs, needed_by, advisories,
          collect(DISTINCT c {.name, .kind, .version, .replacement}) AS changes""",
        name=name,
    ).records
    if not row:
        return {"package": name, "known": False}
    data = dict(row[0])
    users = run_query(
        db,
        """MATCH (t:Release {package: $name})
        MATCH (x)-[l:LOCKS]->(d:Release)
        WHERE (x:SourceRepo OR (x:Repository AND x.ws = $ws))
        MATCH p = (d)-[:DEPENDS_ON*0..6]->(t)
        WITH x, min(length(p)) AS hops, collect(DISTINCT d.package)[..3] AS via
        RETURN labels(x)[0] AS kind, x.name AS name, x.stars AS stars, hops, via
        ORDER BY hops, coalesce(x.stars, 0) DESC LIMIT 100""",
        name=name,
        ws=ws,
    ).records
    data["dependents"] = [dict(u) for u in users]
    return {"package": name, "known": True, **data}
