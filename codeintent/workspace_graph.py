"""The workspace graph in Neo4j: what your code uses, what libraries changed, and why, across every run.

Workspace data (repositories, code, runs, findings, pins) carries ``ws`` (the installation id, ``0`` for the
deployment's own MCP token) and a ``uid`` that starts with it. Facts about public libraries (packages,
releases, symbols, API changes, upstream PRs, advisories, source repositories, files) are shared ``pub|``
nodes every workspace links into: what one run learns about a library answers questions in every workspace.
PostgreSQL stays the ledger; this graph is a projection of finished runs and can be rebuilt from it.

    (:Workspace)-[:WATCHES]->(:Repository)-[:CONTAINS]->(:File)-[:HAS_LINE]->(:CodeLine)-[:USES]->(:Symbol)
    (:Repository)-[:DEPENDS_ON]->(:Package)-[:HAS_RELEASE]->(:Release)<-[:LOCKS]-(:Repository)
    (:Run)-[:ANALYSED]->(:Repository)   (:Run)-[:HAD_STEP]->(:Step)   (:Run)-[:CHECKED]->(:Upgrade)
    (:Upgrade)-[:FROM|TO]->(:Release)   (:Upgrade)-[:FOUND]->(:Finding)-[:AT]->(:CodeLine)
    (:Finding)-[:CAUSED_BY]->(:APIChange)-[:AFFECTS]->(:Symbol)   (:APIChange)-[:IN_RELEASE]->(:Release)
    (:APIChange)-[:CHANGED_IN|DEPRECATED_IN]->(:PullRequest)      (:Advisory)-[:AFFECTS]->(:Release)
    (:Repository)-[:DECLARES]->(:Pin)-[:RESTRICTS]->(:Package)    (:Pin)-[:HOLDS_BACK]->(:Release)
    (:Pin)-[:ADDED_IN]->(:Commit)-[:MERGED_IN]->(:PullRequest)    (:AgentToken)-[:ASKED]->(:Run)
    (:File)-[:IMPORTS]->(:File)   (:File)-[:DEFINES]->(:Function)-[:CALLS]->(:Function)
    (:CodeLine)-[:INSIDE]->(:Function)   (from each repository's code map, ``codeintent.codemap``)

``USES`` edges come from scans of the default branch only, so they describe the code as it is, and edges
a later scan no longer sees are removed.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime

from codeintent import store

logger = logging.getLogger(__name__)

PUBLIC = frozenset(
    {
        "Package",
        "Release",
        "Symbol",
        "APIChange",
        "UpstreamPR",
        "Advisory",
        "SourceRepo",
        "Module",
    }
)
"""Facts about public open-source libraries: one shared node each, with no ``ws``. Everything else is
workspace data and carries its installation's ``ws``."""
LABELS = (
    "UpstreamPR",
    "SourceRepo",
    "Module",
    "Workspace",
    "Repository",
    "File",
    "CodeLine",
    "Package",
    "Release",
    "Symbol",
    "Run",
    "Step",
    "Upgrade",
    "Finding",
    "APIChange",
    "PullRequest",
    "Advisory",
    "Pin",
    "Commit",
    "AgentToken",
    "Function",
)
MAX_TEXT = 400


def public(symbol: str | None) -> str:
    """``httpx._client.Client`` as users import it: ``httpx.Client`` (mirrors ``publicSymbol`` in the web)."""
    parts = str(symbol or "").split(".")
    return ".".join(
        p
        for i, p in enumerate(parts)
        if i == 0 or not p.startswith("_") or p.startswith("__")
    )


def _clip(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def _location(value) -> tuple[str, int | None]:
    """``{"file", "line"}`` or ``"path:line"`` (MCP briefs) as ``(file, line)``."""
    if isinstance(value, dict):
        return str(value.get("file") or ""), value.get("line")
    path, _, line = str(value).rpartition(":")
    return (path, int(line)) if line.isdigit() and path else (str(value), None)


class Batch:
    """Nodes and relationships for one run, merged by ``uid`` in a few UNWIND statements."""

    def __init__(self, ws: int):
        self.ws = ws
        self.nodes: dict[str, dict[str, dict]] = defaultdict(dict)
        self.rels: dict[tuple[str, str, str], dict[tuple, dict]] = defaultdict(dict)

    def node(self, kind: str, key: str, /, **props) -> str:
        if kind in PUBLIC:
            uid = f"pub|{kind}|{key}"
            merged = self.nodes[kind].setdefault(uid, {"uid": uid})
        else:
            uid = f"{self.ws}|{kind}|{key}"
            merged = self.nodes[kind].setdefault(uid, {"uid": uid, "ws": self.ws})
        merged.update({k: v for k, v in props.items() if v is not None})
        return uid

    def rel(
        self, kind: str, a: tuple[str, str], b: tuple[str, str], /, **props
    ) -> None:
        group = self.rels[(a[0], kind, b[0])]
        group.setdefault((a[1], b[1]), {"a": a[1], "b": b[1], "props": {}})[
            "props"
        ].update({k: v for k, v in props.items() if v is not None})

    # Shared shapes --------------------------------------------------------------------------------

    def repository(self, name: str) -> tuple[str, str]:
        return ("Repository", self.node("Repository", name.lower(), name=name))

    def release(self, package: str, version: str) -> tuple[str, str]:
        pkg = ("Package", self.node("Package", package, name=package))
        rel = (
            "Release",
            self.node(
                "Release", f"{package}@{version}", package=package, version=version
            ),
        )
        self.rel("HAS_RELEASE", pkg, rel)
        return rel

    def code_line(
        self, repo: str, file: str, line: int | None, code: str | None = None
    ):
        r = self.repository(repo)
        f = ("File", self.node("File", f"{repo.lower()}|{file}", repo=repo, path=file))
        self.rel("CONTAINS", r, f)
        c = (
            "CodeLine",
            self.node(
                "CodeLine",
                f"{repo.lower()}|{file}|{line}",
                repo=repo,
                file=file,
                line=line,
                code=_clip(code),
                name=f"{file}:{line}" if line else file,
            ),
        )
        self.rel("HAS_LINE", f, c)
        return c

    def symbol(self, package: str, name: str) -> tuple[str, str]:
        s = (
            "Symbol",
            self.node("Symbol", f"{package}|{name}", package=package, name=name),
        )
        self.rel(
            "IN_PACKAGE", s, ("Package", self.node("Package", package, name=package))
        )
        return s

    def pull_request(
        self, repo: str, number: int, title=None, url=None
    ) -> tuple[str, str]:
        return (
            "PullRequest",
            self.node(
                "PullRequest",
                f"{repo.lower()}#{number}",
                repo=repo,
                number=number,
                title=_clip(title),
                url=url,
                name=f"{repo}#{number}",
            ),
        )

    def upstream_pr(
        self, repo: str, number: int, title=None, url=None
    ) -> tuple[str, str]:
        """A pull request in a library's public repository, linked to that repository."""
        pr = (
            "UpstreamPR",
            self.node(
                "UpstreamPR",
                f"{repo.lower()}#{number}",
                repo=repo,
                number=number,
                title=_clip(title),
                url=url,
                name=f"{repo}#{number}",
            ),
        )
        self.rel("IN_REPO", pr, self.source_repo(repo))
        return pr

    def source_repo(self, name: str, **props) -> tuple[str, str]:
        return (
            "SourceRepo",
            self.node(
                "SourceRepo",
                name.lower(),
                name=name,
                url=f"https://github.com/{name}",
                **props,
            ),
        )

    def module(self, package: str, version: str, path: str) -> tuple[str, str]:
        m = (
            "Module",
            self.node(
                "Module",
                f"{package}@{version}|{path}",
                package=package,
                version=version,
                path=path,
                name=path,
            ),
        )
        self.rel("SHIPS", self.release(package, version), m)
        return m

    def upgrade(
        self,
        run: tuple[str, str],
        run_id: str,
        repo: str | None,
        verdict: dict,
        places_of,
    ):
        package, start, end = verdict["package"], verdict["start"], verdict["end"]
        u = (
            "Upgrade",
            self.node(
                "Upgrade",
                f"{run_id}|{package}",
                package=package,
                start=start,
                end=end,
                verdict=verdict.get("verdict"),
                label=verdict.get("label"),
                reason=_clip(verdict.get("reason")),
                name=f"{package} {start} → {end}",
            ),
        )
        self.rel("CHECKED", run, u)
        self.rel("FROM", u, self.release(package, start))
        self.rel("TO", u, self.release(package, end))
        decisions = [d for d in verdict.get("decisions") or [] if isinstance(d, dict)]
        for index, finding in enumerate(verdict.get("findings") or []):
            change = finding.get("change") or {}
            symbol = public(change.get("symbol"))
            c = (
                "APIChange",
                self.node(
                    "APIChange",
                    f"{package}@{end}|{change.get('kind')}|{symbol}|{change.get('parameter') or ''}",
                    package=package,
                    version=end,
                    kind=change.get("kind"),
                    symbol=symbol,
                    parameter=change.get("parameter"),
                    detail=_clip(change.get("detail")),
                    replacement=_clip(change.get("replacement")),
                    message=_clip(change.get("message")),
                    name=f"{symbol}({change['parameter']}=)"
                    if change.get("parameter")
                    else symbol,
                ),
            )
            self.rel("AFFECTS", c, self.symbol(package, symbol))
            self.rel("IN_RELEASE", c, self.release(package, end))
            for side, at in (("before", start), ("after", end)):
                where = change.get(side) or {}
                if where.get("file"):
                    self.rel(
                        "IN_FILE",
                        c,
                        self.module(package, at, where["file"]),
                        side=side,
                        line=where.get("line"),
                    )
            f = (
                "Finding",
                self.node(
                    "Finding",
                    f"{run_id}|{package}|{index}",
                    severity=finding.get("severity"),
                    guarded=bool(finding.get("guarded")),
                    name=f"{finding.get('severity')}: {symbol}",
                ),
            )
            self.rel("FOUND", u, f)
            self.rel("CAUSED_BY", f, c)
            if repo:
                for loc in finding.get("locations") or []:
                    file, line = _location(loc)
                    if file:
                        self.rel(
                            "AT",
                            f,
                            self.code_line(repo, file, line, places_of(file, line)),
                        )
            decision = _decision(decisions, change, index)
            if decision and decision.get("pr_number") and decision.get("pr_url"):
                upstream = _repo_of(decision["pr_url"])
                quote = next(
                    (
                        q.get("text")
                        for q in decision.get("quotes") or []
                        if q.get("source_kind") != "pr-title"
                    ),
                    None,
                )
                self.rel(
                    "CHANGED_IN",
                    c,
                    self.upstream_pr(
                        upstream,
                        decision["pr_number"],
                        decision.get("pr_title"),
                        decision["pr_url"],
                    ),
                    quote=_clip(quote),
                )
                self.rel(
                    "PUBLISHES",
                    self.source_repo(upstream),
                    ("Package", self.node("Package", package, name=package)),
                )
                origin = decision.get("deprecation") or {}
                if origin.get("pr_number") and origin.get("pr_url"):
                    self.rel(
                        "DEPRECATED_IN",
                        c,
                        self.upstream_pr(
                            _repo_of(origin["pr_url"]),
                            origin["pr_number"],
                            origin.get("pr_title"),
                            origin["pr_url"],
                        ),
                    )
        for check in verdict.get("advisories") or []:
            self.advisories(check)
        return u

    def advisories(self, check: dict) -> None:
        if not isinstance(check, dict) or check.get("status") != "advisories":
            return
        release = self.release(check["package"], check["version"])
        for advisory in check.get("advisories") or []:
            if advisory.get("withdrawn"):
                continue
            a = (
                "Advisory",
                self.node(
                    "Advisory",
                    advisory["id"],
                    name=advisory["id"],
                    summary=_clip(advisory.get("summary")),
                    severity=advisory.get("severity"),
                    fixed=advisory.get("fixed"),
                    url=advisory.get("url"),
                ),
            )
            self.rel("AFFECTS", a, release)


def _decision(decisions: list[dict], change: dict, index: int) -> dict | None:
    wanted = (change.get("symbol"), change.get("parameter"), change.get("kind"))
    for decision in decisions:
        k = decision.get("change_key") or {}
        if (k.get("symbol"), k.get("parameter"), k.get("kind")) == wanted:
            return decision
    return decisions[index] if index < len(decisions) else None


def _repo_of(url: str) -> str:
    parts = url.split("github.com/", 1)[-1].split("/")
    return "/".join(parts[:2]) if len(parts) >= 2 else url


# --- From a run to a batch ----------------------------------------------------------------------


def build(
    run: dict,
    steps: list[dict],
    breaks: list[dict],
    login: str | None,
    token_hint: str | None,
) -> Batch:
    """The nodes and relationships for one finished run (rows as stored in PostgreSQL)."""
    ws = run["installation_id"] or 0
    b = Batch(ws)
    run_id = str(run["id"])
    at: datetime = run["started_at"]
    workspace = (
        "Workspace",
        b.node("Workspace", str(ws), name=login or "deployment", login=login),
    )
    r = (
        "Run",
        b.node(
            "Run",
            run_id,
            id=run_id,
            kind=run["kind"],
            subject=run["subject"],
            status=run["status"],
            failed_step=run.get("failed_step"),
            error=_clip(run.get("error")),
            attempt=run.get("attempt"),
            ref=run.get("ref"),
            at=at.isoformat(),
            name=f"{run['kind']} {run['subject']} · {run['status']}",
        ),
    )
    b.rel("RAN", workspace, r)
    repo = run.get("repository")
    if repo and "/" in repo:
        repository = b.repository(repo)
        b.rel("ANALYSED", r, repository)
        if ws:
            b.rel("WATCHES", workspace, repository)
    for step in steps:
        s = (
            "Step",
            b.node(
                "Step",
                f"{run_id}|{step['seq']}",
                name=step["name"],
                status=step["status"],
                seq=step["seq"],
                duration_ms=step["duration_ms"],
                detail=_clip(step.get("detail")),
            ),
        )
        b.rel("HAD_STEP", r, s, seq=step["seq"])
    if run["kind"] == "mcp" and token_hint:
        b.rel(
            "ASKED",
            (
                "AgentToken",
                b.node("AgentToken", token_hint, name=f"ci_mcp_…{token_hint}"),
            ),
            r,
        )
    code = {
        (p.get("file"), p.get("line")): p.get("code")
        for row in breaks
        for p in row.get("places") or []
    }

    def places_of(file, line):
        return code.get((file, line))

    result = run.get("result") or {}
    if run["kind"] == "pull":
        number = int(str(run["subject"]).lstrip("#") or 0)
        if repo and number:
            b.rel(
                "FOR_PULL",
                r,
                b.pull_request(repo, number, (run.get("summary") or {}).get("title")),
            )
        for verdict in result.get("verdicts") or []:
            b.upgrade(r, run_id, repo, verdict, places_of)
    elif run["kind"] == "scan":
        _scan(b, r, run_id, repo, result, places_of, at)
    elif (
        run["kind"] == "mcp"
        and run["subject"] == "upgrade_brief"
        and result.get("verdict")
    ):
        verdict = {
            "package": result["package"],
            "start": result["from_version"],
            "end": result["to_version"],
            "verdict": result["verdict"],
            "label": result.get("label"),
            "reason": result.get("reason"),
            "findings": result.get("findings") or [],
            "advisories": [
                {**a, "status": "advisories" if a.get("advisories") else "none-known"}
                for a in result.get("advisories") or []
                if isinstance(a, dict) and a.get("package") and a.get("version")
            ],
        }
        b.upgrade(r, run_id, repo, verdict, places_of)
    return b


def _scan(
    b: Batch, r, run_id: str, repo: str | None, result: dict, places_of, at: datetime
) -> None:
    if not repo:
        return
    repository = b.repository(repo)
    seen = at.isoformat()
    for item in result.get("items") or []:
        package = item["package"]
        pkg = ("Package", b.node("Package", package, name=package))
        where = item.get("location") or {}
        b.rel(
            "DEPENDS_ON",
            repository,
            pkg,
            specifier=item.get("specifier") or None,
            file=where.get("file"),
            line=where.get("line"),
            project=item.get("project"),
            seen=seen,
        )
        if item.get("current"):
            b.rel(
                "LOCKS",
                repository,
                b.release(package, item["current"]),
                direct=True,
                seen=seen,
            )
        if item.get("latest"):
            b.rel("LATEST", pkg, b.release(package, item["latest"]))
        if item.get("verdict"):
            b.upgrade(r, run_id, repo, item["verdict"], places_of)
        if item.get("advisories"):
            b.advisories(item["advisories"])
        if item.get("pins"):
            pin = (
                "Pin",
                b.node(
                    "Pin",
                    f"{repo.lower()}|{where.get('file')}|{package}",
                    package=package,
                    specifier=item.get("specifier"),
                    file=where.get("file"),
                    line=where.get("line"),
                    lift=item.get("lift"),
                    lift_reason=item.get("lift_reason"),
                    name=f"{package}{item.get('specifier') or ''}",
                    seen=seen,
                ),
            )
            b.rel("DECLARES", repository, pin, seen=seen)
            b.rel("RESTRICTS", pin, pkg)
            if item.get("allows_latest") is False and item.get("latest"):
                b.rel("HOLDS_BACK", pin, b.release(package, item["latest"]))
            origin = item.get("origin") or {}
            if origin.get("commit"):
                commit = (
                    "Commit",
                    b.node(
                        "Commit",
                        f"{repo.lower()}|{origin['commit']}",
                        sha=origin["commit"],
                        message=_clip(origin.get("message")),
                        author=origin.get("author"),
                        date=origin.get("date"),
                        url=origin.get("commit_url"),
                        name=(origin.get("message") or origin["commit"]).split("\n", 1)[
                            0
                        ][:80],
                    ),
                )
                b.rel("ADDED_IN", pin, commit)
                if origin.get("pr_number") and origin.get("pr_url"):
                    b.rel(
                        "MERGED_IN",
                        commit,
                        b.pull_request(
                            _repo_of(origin["pr_url"]),
                            origin["pr_number"],
                            origin.get("pr_title"),
                            origin["pr_url"],
                        ),
                    )
    for entry in result.get("locked") or []:
        b.rel(
            "LOCKS",
            repository,
            b.release(entry["package"], entry["version"]),
            direct=entry.get("direct", False),
            seen=seen,
        )
    for package, uses in (result.get("usages") or {}).items():
        for use in uses:
            if not use.get("file"):
                continue
            line = b.code_line(
                repo,
                use["file"],
                use.get("line"),
                places_of(use["file"], use.get("line")),
            )
            b.rel(
                "USES",
                line,
                b.symbol(package, public(use.get("symbol"))),
                kind=use.get("kind"),
                keywords=use.get("keywords") or [],
                seen=seen,
            )


def map_batch(ws: int, repo: str, mapped: dict, seen: str) -> Batch:
    """The nodes and relationships of one repository's code map (``codeintent.codemap``)."""
    b = Batch(ws)
    repository = b.repository(repo)
    key = repo.lower()

    def file(path: str) -> tuple[str, str]:
        return ("File", b.node("File", f"{key}|{path}", repo=repo, path=path))

    for f in mapped.get("files") or []:
        node = (
            "File",
            b.node(
                "File",
                f"{key}|{f['path']}",
                repo=repo,
                path=f["path"],
                name=f["path"],
                module=f.get("module") or None,
                test=bool(f.get("test")),
                entry=bool(f.get("entry")),
                lines=f.get("lines"),
                seen=seen,
            ),
        )
        b.rel("CONTAINS", repository, node, seen=seen)
    for i in mapped.get("imports") or []:
        b.rel(
            "IMPORTS", file(i["file"]), file(i["target"]), line=i.get("line"), seen=seen
        )

    def function(ident: str) -> tuple[str, str]:
        return ("Function", b.node("Function", f"{key}|{ident}", repo=repo))

    for fn in mapped.get("functions") or []:
        node = (
            "Function",
            b.node(
                "Function",
                f"{key}|{fn['id']}",
                repo=repo,
                file=fn["file"],
                qualname=fn["name"],
                name=f"{fn['name']}()",
                line=fn.get("line"),
                end=fn.get("end"),
                entry=fn.get("entry"),
                seen=seen,
            ),
        )
        b.rel("DEFINES", file(fn["file"]), node, seen=seen)
    for c in mapped.get("calls") or []:
        b.rel(
            "CALLS",
            function(c["caller"]),
            function(c["callee"]),
            line=c.get("line"),
            seen=seen,
        )
    for package, uses in (mapped.get("uses") or {}).items():
        for use in uses:
            line = b.code_line(repo, use["file"], use.get("line"))
            b.rel(
                "USES",
                line,
                b.symbol(package, public(use.get("symbol"))),
                kind=use.get("kind"),
                keywords=use.get("keywords") or [],
                seen=seen,
            )
            if use.get("function"):
                b.rel("INSIDE", line, function(use["function"]), seen=seen)
    return b


def project_map(installation_id: int, repository: str, db=None) -> dict | None:
    """Project a repository's stored code map into its workspace graph, replacing the previous one."""
    from contextlib import nullcontext

    from codeintent.graph import run_query, shared

    with store.connection() as conn:
        row = conn.execute(
            "SELECT map,built_at FROM ci_code_maps WHERE installation_id=%s AND repository=%s",
            (installation_id, repository),
        ).fetchone()
    if not row:
        return None
    at = row["built_at"].isoformat()
    batch = map_batch(installation_id, repository, row["map"], at)
    with nullcontext(db) if db is not None else shared() as graph:
        schema(graph)
        counts = write(graph, batch)
        uid = f"{installation_id}|Repository|{repository.lower()}"
        for query in (
            # What the new map no longer has: imports, definitions, calls, uses and functions.
            """MATCH (:Repository {uid: $uid})-[:CONTAINS]->(:File)-[e:IMPORTS|DEFINES]->()
            WHERE e.seen < $at DELETE e""",
            """MATCH (:Repository {uid: $uid})-[:CONTAINS]->(:File)-[:HAS_LINE]->(:CodeLine)-[e:USES|INSIDE]->()
            WHERE e.seen < $at DELETE e""",
            """MATCH (fn:Function {ws: $ws, repo: $repo}) WHERE fn.seen < $at DETACH DELETE fn""",
            """MATCH (:Function {ws: $ws, repo: $repo})-[e:CALLS]->() WHERE e.seen < $at DELETE e""",
        ):
            run_query(graph, query, uid=uid, at=at, ws=installation_id, repo=repository)
    with store.connection() as conn:
        conn.execute(
            "UPDATE ci_code_maps SET projected_at=now() WHERE installation_id=%s AND repository=%s",
            (installation_id, repository),
        )
    return counts


# --- Writing ------------------------------------------------------------------------------------


def configured() -> bool:
    return bool(
        os.getenv("NEO4J_URI")
        and os.getenv("NEO4J_USERNAME")
        and os.getenv("NEO4J_PASSWORD")
    )


_schema_ready = False


def schema(db) -> None:
    """Constraints and indexes, created once per process (each statement is idempotent)."""
    global _schema_ready
    from codeintent.graph import run_query

    if _schema_ready:
        return
    for label in LABELS:
        run_query(
            db,
            f"CREATE CONSTRAINT ws_{label.lower()}_uid IF NOT EXISTS FOR (n:{label}) REQUIRE n.uid IS UNIQUE",
        )
        run_query(
            db,
            f"CREATE INDEX ws_{label.lower()}_ws IF NOT EXISTS FOR (n:{label}) ON (n.ws)",
        )
    _schema_ready = True


CHUNK = 5000


def _chunks(rows: list) -> list[list]:
    return [rows[i : i + CHUNK] for i in range(0, len(rows), CHUNK)] or [[]]


def write(
    db, batch: Batch, *, repository: str | None = None, scan_at: str | None = None
) -> dict:
    """Merge the batch; after a scan, drop what the repository's default branch no longer has."""
    from codeintent.graph import run_query

    counts = {"nodes": 0, "relationships": 0}
    for label, rows in batch.nodes.items():
        for chunk in _chunks(list(rows.values())):
            run_query(
                db,
                f"UNWIND $rows AS row MERGE (n:{label} {{uid: row.uid}}) SET n += row",
                rows=chunk,
            )
        counts["nodes"] += len(rows)
    for (a, kind, b), rels in batch.rels.items():
        for chunk in _chunks(list(rels.values())):
            run_query(
                db,
                f"""UNWIND $rows AS row
                MATCH (a:{a} {{uid: row.a}}) MATCH (b:{b} {{uid: row.b}})
                MERGE (a)-[e:{kind}]->(b) SET e += row.props""",
                rows=chunk,
            )
        counts["relationships"] += len(rels)
    if repository and scan_at:
        uid = f"{batch.ws}|Repository|{repository.lower()}"
        # Uses, dependencies, locks and pins of this branch that the scan no longer saw.
        run_query(
            db,
            """MATCH (:Repository {uid: $uid})-[:CONTAINS]->(:File)-[:HAS_LINE]->(:CodeLine)-[u:USES]->()
            WHERE u.seen < $at DELETE u""",
            uid=uid,
            at=scan_at,
        )
        run_query(
            db,
            """MATCH (:Repository {uid: $uid})-[e:DEPENDS_ON|LOCKS|DECLARES]->() WHERE e.seen < $at DELETE e""",
            uid=uid,
            at=scan_at,
        )
        run_query(
            db,
            "MATCH (p:Pin {ws: $ws}) WHERE p.uid STARTS WITH $prefix AND p.seen < $at DETACH DELETE p",
            ws=batch.ws,
            prefix=f"{batch.ws}|Pin|{repository.lower()}|",
            at=scan_at,
        )
    return counts


def project(run_id: str) -> dict | None:
    """Project one finished run into its workspace graph and mark it projected. None if not projectable."""
    from codeintent.graph import shared

    with store.connection() as conn:
        run = conn.execute(
            "SELECT * FROM ci_runs WHERE id=%s AND finished_at IS NOT NULL", (run_id,)
        ).fetchone()
        if not run:
            return None
        steps = conn.execute(
            "SELECT * FROM ci_run_steps WHERE run_id=%s ORDER BY seq", (run_id,)
        ).fetchall()
        found = conn.execute(
            "SELECT places FROM ci_breaks WHERE first_run=%s OR last_run=%s",
            (run_id, run_id),
        ).fetchall()
        login = (
            conn.execute(
                "SELECT account_login FROM ci_installations WHERE id=%s",
                (run["installation_id"],),
            ).fetchone()
            or {}
        ).get("account_login")
        hint = (
            (
                conn.execute(
                    "SELECT hint FROM ci_mcp_tokens WHERE id=%s", (run["token_id"],)
                ).fetchone()
                or {}
            ).get("hint")
            if run["token_id"]
            else None
        )
    batch = build(run, steps, found, login, hint)
    scan = run["kind"] == "scan" and run["status"] in ("succeeded", "partial")
    with shared() as db:
        schema(db)
        counts = write(
            db,
            batch,
            repository=run["repository"] if scan else None,
            scan_at=run["started_at"].isoformat() if scan else None,
        )
    with store.connection() as conn:
        conn.execute("UPDATE ci_runs SET projected_at=now() WHERE id=%s", (run_id,))
    if scan and run["installation_id"]:
        project_map(run["installation_id"], run["repository"])
    if scan:
        from codeintent import ecosystem

        # Every locked release joins the public ecosystem graph, with its resolved tree.
        result = run.get("result") or {}
        ecosystem.queue(
            [(e["package"], e["version"]) for e in result.get("locked") or []]
            + [
                (i["package"], i[k])
                for i in result.get("items") or []
                for k in ("current", "latest")
                if i.get(k)
            ]
        )
    return counts


def rebuild(installation_id: int) -> int:
    """Delete a workspace's graph and project all its finished runs again, oldest first."""
    from codeintent.graph import driver, run_query

    with driver() as db:
        while True:
            deleted = run_query(
                db,
                """MATCH (n {ws: $ws}) WHERE n.uid IS NOT NULL
                WITH n LIMIT 2000 DETACH DELETE n RETURN count(*) AS n""",
                ws=installation_id,
            ).records[0]["n"]
            if not deleted:
                break
    with store.connection() as conn:
        ids = [
            str(r["id"])
            for r in conn.execute(
                "SELECT id FROM ci_runs WHERE installation_id IS NOT DISTINCT FROM %s AND finished_at IS NOT NULL ORDER BY started_at",
                (installation_id or None,),
            ).fetchall()
        ]
    for ident in ids:
        project(ident)
    with store.connection() as conn:
        repositories = [
            r["repository"]
            for r in conn.execute(
                "SELECT repository FROM ci_code_maps WHERE installation_id=%s",
                (installation_id,),
            ).fetchall()
        ]
    for repository in repositories:
        project_map(installation_id, repository)
    return len(ids)


# --- Reading: the questions the product asks the graph ----------------------------------------

PARAMETER_KINDS = ("parameter-removed", "default-changed", "deprecated")


def impact(db, ws: int, package: str, version: str | None = None) -> list[dict]:
    """Every line in the workspace that a known change in ``package`` touches, in any repository.

    A change to one parameter only counts uses that pass it; removals count every use. ``confirmed``
    marks lines a run already compared; the others were found through the graph alone.
    """
    from codeintent.graph import run_query

    records = run_query(
        db,
        """MATCH (c:APIChange {package: $package})
        WHERE $version IS NULL OR c.version = $version
        MATCH (c)-[:AFFECTS]->(s:Symbol)<-[u:USES]-(l:CodeLine {ws: $ws})<-[:HAS_LINE]-(:File)<-[:CONTAINS]-(r:Repository)
        WHERE c.parameter IS NULL OR NOT c.kind IN $parameter_kinds OR c.parameter IN u.keywords
        OPTIONAL MATCH (r)-[:LOCKS]->(locked:Release {package: $package})
        OPTIONAL MATCH (f:Finding)-[:AT]->(l)
        WHERE (f)-[:CAUSED_BY]->(c)
        RETURN r.name AS repository, l.file AS file, l.line AS line, l.code AS code, s.name AS symbol,
          c.kind AS kind, c.parameter AS parameter, c.version AS version, c.replacement AS replacement,
          c.name AS change, locked.version AS locked, count(f) > 0 AS confirmed
        ORDER BY repository, file, line""",
        ws=ws,
        package=package,
        version=version,
        parameter_kinds=list(PARAMETER_KINDS),
    ).records
    return [dict(r) for r in records]


def usages(db, ws: int, package: str, symbol: str | None = None) -> list[dict]:
    """Where the workspace's default branches use ``package`` (or one of its symbols)."""
    from codeintent.graph import run_query

    records = run_query(
        db,
        """MATCH (s:Symbol {package: $package})
        WHERE $symbol IS NULL OR s.name = $symbol OR s.name STARTS WITH $symbol + '.'
        MATCH (s)<-[u:USES]-(l:CodeLine {ws: $ws})<-[:HAS_LINE]-(:File)<-[:CONTAINS]-(r:Repository)
        RETURN r.name AS repository, l.file AS file, l.line AS line, l.code AS code, s.name AS symbol,
          u.kind AS kind, u.keywords AS keywords
        ORDER BY repository, file, line LIMIT 500""",
        ws=ws,
        package=package,
        symbol=symbol,
    ).records
    return [dict(r) for r in records]


def run_graph(db, ws: int, run_id: str) -> dict:
    """The run's neighbourhood as ``{nodes, edges}``: what it analysed, checked, found, and why."""
    from codeintent.graph import run_query

    records = run_query(
        db,
        """MATCH (run:Run {uid: $uid})
        CALL (run) {
          MATCH p = (run)-[:ANALYSED|HAD_STEP|FOR_PULL]->() RETURN p
          UNION
          MATCH p = (run)<-[:ASKED]-(:AgentToken) RETURN p
          UNION
          MATCH p = (run)-[:CHECKED]->(u:Upgrade)-[:FROM|TO]->(:Release)
          WHERE u.verdict <> 'no-known-impact' RETURN p
          UNION
          MATCH p = (run)-[:CHECKED]->(:Upgrade)-[:FOUND]->(:Finding)-[:AT]->(:CodeLine) RETURN p
          UNION
          MATCH p = (run)-[:CHECKED]->(:Upgrade)-[:FOUND]->(:Finding)-[:CAUSED_BY]->(:APIChange)
            -[:CHANGED_IN|DEPRECATED_IN]->(:UpstreamPR) RETURN p
          UNION
          MATCH p = (run)-[:CHECKED]->(:Upgrade)-[:FOUND]->(:Finding)-[:CAUSED_BY]->(:APIChange)
            -[:IN_FILE]->(:Module) RETURN p
          UNION
          MATCH p = (run)-[:CHECKED]->(:Upgrade)-[:TO]->(:Release)<-[:AFFECTS]-(:Advisory) RETURN p
          UNION
          MATCH p = (run)-[:CHECKED]->(:Upgrade)-[:FOUND]->(:Finding)-[:AT]->(:CodeLine)
            -[:INSIDE]->(:Function)<-[:CALLS*1..2]-(:Function) RETURN p
          UNION
          MATCH p = (run)-[:CHECKED]->(:Upgrade)-[:FOUND]->(:Finding)-[:AT]->(:CodeLine)
            <-[:HAS_LINE]-(:File)<-[:IMPORTS]-(:File) RETURN p
        }
        RETURN p LIMIT 400""",
        uid=f"{ws}|Run|{run_id}",
    ).records
    nodes: dict[str, dict] = {}
    edges: dict[tuple, dict] = {}
    for record in records:
        path = record["p"]
        for node in path.nodes:
            props = dict(node)
            nodes[props["uid"]] = {
                "id": props["uid"],
                "label": next(iter(node.labels)),
                "name": props.get("name") or props.get("version") or props.get("uid"),
                "props": {
                    k: v
                    for k, v in props.items()
                    if k not in ("uid", "ws") and isinstance(v, (str, int, float, bool))
                },
            }
        for rel in path.relationships:
            a, b = dict(rel.start_node)["uid"], dict(rel.end_node)["uid"]
            edges[(a, rel.type, b)] = {"source": a, "target": b, "type": rel.type}
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


# --- The PR check's questions: where a package reaches the code, and what a broken line takes down ----

MAX_REACH_LINES = 200
MAX_AFFECTED = 60


def reach(db, ws: int, repo: str, package: str) -> dict:
    """Where ``package`` reaches one repository's code: its own uses, and the chains through which
    other dependencies pull it in (from the ecosystem graph), with how much code uses each of those."""
    from codeintent.graph import run_query

    uid = f"{ws}|Repository|{repo.lower()}"
    direct = [
        dict(r)
        for r in run_query(
            db,
            """MATCH (:Repository {uid: $uid})-[:CONTAINS]->(f:File)-[:HAS_LINE]->(l:CodeLine)
                  -[u:USES]->(s:Symbol {package: $package})
            OPTIONAL MATCH (l)-[:INSIDE]->(fn:Function)
            RETURN f.path AS file, l.line AS line, l.code AS code, s.name AS symbol, u.kind AS kind,
              u.keywords AS keywords, fn.qualname AS function, coalesce(f.test, false) AS test
            ORDER BY file, line LIMIT $limit""",
            uid=uid,
            package=package,
            limit=MAX_REACH_LINES,
        ).records
    ]
    through = [
        dict(r)
        for r in run_query(
            db,
            """MATCH (r:Repository {uid: $uid})-[l:LOCKS]->(d:Release)
            WHERE coalesce(l.direct, true) AND d.package <> $package
            MATCH (t:Release {package: $package})
            MATCH p = shortestPath((d)-[:DEPENDS_ON*1..6]->(t))
            WITH r, d.package AS via, [n IN nodes(p) | n.package + '@' + n.version] AS chain
            ORDER BY size(chain)
            WITH r, via, head(collect(chain)) AS chain
            OPTIONAL MATCH (r)-[:CONTAINS]->(f:File)-[:HAS_LINE]->(cl:CodeLine)-[:USES]->(:Symbol {package: via})
            RETURN via, chain, count(DISTINCT cl) AS uses, collect(DISTINCT f.path)[..8] AS files
            ORDER BY uses DESC, size(chain), via LIMIT 20""",
            uid=uid,
            package=package,
        ).records
    ]
    files = sorted({r["file"] for r in direct})
    return {
        "package": package,
        "uses": len(direct),
        "files": files,
        "lines": direct,
        "through": through,
    }


def blast(db, ws: int, repo: str, places: list[dict], depth: int = 4) -> list[dict]:
    """For each broken ``{file, line}``: the function it is in, and everything in the repository that
    reaches it, i.e. callers up to ``depth`` calls away and files importing that file up to ``depth``
    imports away, with the tests and entry points (routes, commands, tasks, scripts) among them.

    The search goes outward one hop per query, so its cost stays bounded on dense call graphs."""
    from codeintent.graph import run_query

    key = f"{ws}|"
    prefix = f"{repo.lower()}|"
    out = []
    for place in places:
        file, line = place.get("file"), place.get("line")
        if not file:
            continue
        found = run_query(
            db,
            """MATCH (l:CodeLine {uid: $line})-[:INSIDE]->(fn:Function)
            RETURN fn.uid AS uid, fn.qualname AS name, fn.entry AS entry ORDER BY fn.line DESC LIMIT 1""",
            line=f"{key}CodeLine|{prefix}{file}|{line}",
        ).records
        if not found:
            # A line the map has no use for (or a module-level line): find the function by its range.
            found = run_query(
                db,
                """MATCH (fn:Function {ws: $ws, repo: $repo, file: $file})
                WHERE fn.line <= $at AND fn.end >= $at
                RETURN fn.uid AS uid, fn.qualname AS name, fn.entry AS entry ORDER BY fn.line DESC LIMIT 1""",
                ws=ws,
                repo=repo,
                file=file,
                at=line or 0,
            ).records
        function = dict(found[0]) if found else None
        callers: dict[str, dict] = {}
        frontier = [function["uid"]] if function else []
        for hop in range(1, depth + 1):
            if not frontier or len(callers) >= MAX_AFFECTED:
                break
            rows = run_query(
                db,
                """UNWIND $frontier AS uid
                MATCH (caller:Function)-[c:CALLS]->(:Function {uid: uid})
                MATCH (f:File)-[:DEFINES]->(caller)
                RETURN DISTINCT caller.uid AS uid, caller.qualname AS function, caller.file AS file,
                  c.line AS line, caller.entry AS entry, coalesce(f.test, false) AS test""",
                frontier=frontier,
            ).records
            frontier = []
            for r in rows:
                if r["uid"] in callers or (function and r["uid"] == function["uid"]):
                    continue
                callers[r["uid"]] = {**dict(r), "depth": hop}
                frontier.append(r["uid"])
        importers: dict[str, dict] = {}
        frontier = [f"{key}File|{prefix}{file}"]
        for hop in range(1, depth + 1):
            if not frontier or len(importers) >= MAX_AFFECTED:
                break
            rows = run_query(
                db,
                """UNWIND $frontier AS uid
                MATCH (f:File)-[i:IMPORTS]->(:File {uid: uid})
                RETURN DISTINCT f.uid AS uid, f.path AS file, coalesce(f.test, false) AS test,
                  coalesce(f.entry, false) AS entry""",
                frontier=frontier,
            ).records
            frontier = []
            for r in rows:
                if r["uid"] in importers or r["file"] == file:
                    continue
                importers[r["uid"]] = {**dict(r), "depth": hop}
                frontier.append(r["uid"])
        caller_rows = sorted(
            ({k: v for k, v in c.items() if k != "uid"} for c in callers.values()),
            key=lambda c: (c["depth"], c["file"], c["function"]),
        )[:MAX_AFFECTED]
        importer_rows = sorted(
            ({k: v for k, v in i.items() if k != "uid"} for i in importers.values()),
            key=lambda i: (i["depth"], i["file"]),
        )[:MAX_AFFECTED]
        tests = sorted(
            {c["file"] for c in caller_rows if c["test"]}
            | {i["file"] for i in importer_rows if i["test"]}
        )
        entries = [
            {"name": c["entry"], "function": c["function"], "file": c["file"]}
            for c in caller_rows
            if c.get("entry")
        ]
        if function and function.get("entry"):
            entries.insert(
                0,
                {"name": function["entry"], "function": function["name"], "file": file},
            )
        entries += [
            {"name": "script", "function": None, "file": i["file"]}
            for i in importer_rows
            if i["entry"] and not i["test"]
        ]
        out.append(
            {
                "file": file,
                "line": line,
                "function": function["name"] if function else None,
                "callers": [c for c in caller_rows if not c["test"]],
                "importers": [i for i in importer_rows if not i["test"]],
                "tests": tests,
                "entry_points": entries[:20],
            }
        )
    return out
