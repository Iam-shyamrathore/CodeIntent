"""Durable staged imports. PostgreSQL is the ledger; Neo4j is a rebuildable projection."""

from __future__ import annotations

import logging

import procrastinate

from codeintent import store
from codeintent.settings import required

logger = logging.getLogger(__name__)
app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(
        conninfo=required("DATABASE_URL"), min_size=1, max_size=6
    )
)


@app.task(
    name="import_repository",
    queue="imports",
    pass_context=True,
    retry=procrastinate.RetryStrategy(max_attempts=3, wait=30),
)
def import_repository(context, import_id: str):
    from codeintent.github import CollectionError, GitHub
    from codeintent.graph import embed_corpus, index_id, project, project_decisions
    from codeintent.parsing import parse_sources
    from codeintent.temporal import extract_decisions

    row = store.job(import_id)
    if not row or row["status"] == "ready":
        return
    try:
        if row["cancelled"]:
            raise store.Cancelled()
        checkpoint = row["checkpoint"]
        corpus = checkpoint.get("corpus")
        if not corpus:
            github = GitHub(row["repository"])
            try:
                corpus = github.collect(
                    row["options"],
                    lambda stage, percent, message: store.progress(
                        import_id, stage, percent, message
                    ),
                )
            finally:
                github.close()
            store.progress(
                import_id,
                "captured",
                50,
                f"Captured {len(corpus['documents'])} immutable source snapshots",
                checkpoint={"corpus": corpus},
            )
        scope = index_id(corpus)
        store.progress(
            import_id,
            "parsing",
            55,
            "Reading symbols, local calls and recorded file renames",
        )
        parsed = parse_sources(corpus["documents"])
        decisions = checkpoint.get("decisions")
        if decisions is None:
            store.progress(
                import_id,
                "decisions",
                62,
                "Extracting decisions and checking supporting passages",
            )
            decisions = extract_decisions(corpus)
            store.progress(
                import_id,
                "decisions",
                68,
                f"{len(decisions)} source-backed decision assertions",
                checkpoint={"decisions": decisions},
            )
        store.save_index(corpus, decisions, scope)
        store.progress(
            import_id, "projecting", 72, "Projecting scoped evidence relationships"
        )
        project(corpus, parsed)
        project_decisions(corpus, decisions)
        store.progress(
            import_id, "embedding", 82, "Building the searchable evidence index"
        )
        embed_corpus(corpus)
        store.progress(
            import_id, "validating", 96, "Checking source counts and index isolation"
        )
        from codeintent.graph import driver, run_query

        with driver() as db:
            records, _, _ = run_query(
                db,
                "MATCH (n:CIEntity {index_id:$scope,kind:'source'}) RETURN count(n) AS count,count(n.embedding) AS embeddings",
                scope=scope,
            )
            if records[0]["count"] != len(corpus["documents"]) or records[0][
                "embeddings"
            ] != len(corpus["documents"]):
                raise ValueError("Incomplete graph projection")
        store.publish(import_id, scope)
    except store.Cancelled:
        with store.connection() as conn:
            conn.execute(
                "UPDATE ci_imports SET status='cancelled',stage='cancelled',updated_at=now() WHERE id=%s",
                (import_id,),
            )
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, CollectionError)
            else "An indexing stage failed. Retry resumes from captured sources; check server logs for the error category."
        )
        # Never log exception contents: upstream messages can contain credential-bearing URLs.
        logger.warning("Import %s failed (%s)", import_id, type(exc).__name__)
        with store.connection() as conn:
            conn.execute(
                "UPDATE ci_imports SET status=%s,error=%s,updated_at=now() WHERE id=%s",
                (
                    "retrying" if context.job.attempts < 3 else "failed",
                    message,
                    import_id,
                ),
            )
            conn.execute(
                "INSERT INTO ci_events(import_id,stage,message) VALUES (%s,%s,%s)",
                (import_id, "failed", message),
            )
        raise RuntimeError(type(exc).__name__) from None


@app.task(
    name="investigate_question",
    queue="investigations",
    pass_context=True,
    retry=procrastinate.RetryStrategy(max_attempts=3, wait=30),
)
def investigate_question(context, question_id: str):
    from codeintent.questions import process

    process(context, question_id)


@app.task(
    name="analyze_pull_request",
    queue="pulls",
    pass_context=True,
    retry=procrastinate.RetryStrategy(max_attempts=3, wait=30),
)
def analyze_pull_request(context, analysis_id: str):
    import os
    from pathlib import Path

    import httpx
    from psycopg.types.json import Jsonb

    from codeintent import breaks, runs
    from codeintent import github_app as gh
    from codeintent.upgrades import advisories, report, repository
    from codeintent.upgrades.verdict import evaluate

    with store.connection() as conn:
        row = conn.execute(
            "UPDATE ci_pull_analyses SET status='running',error=NULL,updated_at=now() WHERE id=%s AND status IN ('queued','retrying','running') RETURNING *",
            (analysis_id,),
        ).fetchone()
    if not row:
        return
    repo, number, head = row["repository"], row["number"], row["head_sha"]
    public = os.getenv("CODEINTENT_PUBLIC_URL", "").rstrip("/")
    report_url = f"{public}/pulls/{analysis_id}" if public else None
    client = gh.Client.for_installation(row["installation_id"])
    check_id = row.get("check_run_id")
    attempts = context.job.attempts or 0
    final = attempts >= 3
    try:
        with runs.recorded(
            "pull",
            installation_id=row["installation_id"],
            repository=repo,
            ref=head,
            subject=f"#{number}",
            analysis_id=analysis_id,
            attempt=attempts + 1,
            final=final,
        ) as run:
            with run.step("read the dependency changes") as note:
                diff = gh.dependency_changes(
                    client, repo, number, row["base_sha"], head
                )
                note["detail"] = (
                    f"{len(diff['files'])} manifest file(s), {len(diff.get('changed') or [])} change(s)"
                )
            if not diff["files"]:
                with store.connection() as conn:
                    conn.execute(
                        "UPDATE ci_pull_analyses SET status='skipped',diff=%s,updated_at=now() WHERE id=%s",
                        (Jsonb(diff), analysis_id),
                    )
                run.finish(
                    "skipped", summary={"reason": "no Python dependency changed"}
                )
                return
            with run.step("open the check run"):
                title = client.json(f"/repos/{repo}/pulls/{number}").get("title")
                check_id = check_id or gh.create_check(client, repo, head)
            with store.connection() as conn:
                conn.execute(
                    "UPDATE ci_pull_analyses SET status='diffed',diff=%s,title=%s,check_run_id=%s,updated_at=now() WHERE id=%s",
                    (Jsonb(diff), title, check_id, analysis_id),
                )
            pairs, added = gh.upgrades(diff)
            verdicts, new_packages, root = [], [], None
            with (
                httpx.Client(timeout=60, follow_redirects=True) as pypi,
                repository.using(client.token),
                repository.temporary() as folder,
            ):
                if pairs:
                    with run.step("download the repository"):
                        root = repository.download(
                            repo, head, Path(folder), client.token()
                        )
                    for name, a, b in pairs[:20]:
                        with run.step(f"compare {name} {a} → {b}") as note:
                            verdict = evaluate(name, a, b, root, pypi)
                            note["detail"] = f"{verdict.label}: {verdict.reason}"
                        verdicts.append(verdict)
                if added:
                    with run.step("check advisories for new packages"):
                        for name, version in added[:20]:
                            checks = (
                                advisories.check([(name, version)], pypi)
                                if version
                                else []
                            )
                            new_packages.append((name, version, checks))
                dumped = [v.model_dump(mode="json") for v in verdicts]
                with run.step("record breaks") as note, store.connection() as conn:
                    counts = breaks.record(
                        conn,
                        installation_id=row["installation_id"],
                        repository=repo,
                        source="pull",
                        verdicts=dumped,
                        root=root,
                        run_id=run.id,
                        pull_number=number,
                        analysis_id=analysis_id,
                    )
                    note["detail"] = (
                        f"{counts['found']} found, {counts['fixed']} fixed since the last push"
                    )
                traced = _trace(
                    run, row["installation_id"], repo, head, root, pypi, verdicts
                )
            notes = [
                f"{name}: one side is a version range, not an exact version, so there is no pair to compare."
                for name in gh.unresolved(diff)
            ]
            body = report.comment(
                verdicts,
                new_packages,
                report_url,
                notes,
                graph=traced,
                pull=f"{repo}#{number}",
            )
            with run.step("write the comment"):
                with store.connection() as conn:
                    previous = conn.execute(
                        "SELECT comment_id FROM ci_pull_analyses WHERE repository=%s AND number=%s AND comment_id IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
                        (repo, number),
                    ).fetchone()
                comment_id = gh.upsert_comment(
                    client,
                    repo,
                    number,
                    body,
                    previous["comment_id"] if previous else None,
                )
            result = report.check_output(verdicts, body)
            with run.step("complete the check run") as note:
                check_id = gh.complete_check(
                    client,
                    repo,
                    head,
                    check_id,
                    result["conclusion"],
                    result["output"],
                    report_url,
                )
                note["detail"] = result["conclusion"]
            worst = report.worst(verdicts) if verdicts else None
            with store.connection() as conn:
                conn.execute(
                    "UPDATE ci_pull_analyses SET status='reported',verdicts=%s,verdict=%s,check_run_id=%s,comment_id=%s,updated_at=now() WHERE id=%s",
                    (Jsonb(dumped), worst, check_id, comment_id, analysis_id),
                )
            unreadable = [
                v.package
                for v in verdicts
                if v.verdict == "not-checked" and v.coverage is None
            ]
            run.finish(
                "partial" if unreadable else "succeeded",
                summary={
                    "verdict": worst,
                    "packages": [
                        {
                            "package": v.package,
                            "from": v.start,
                            "to": v.end,
                            "verdict": v.verdict,
                        }
                        for v in verdicts
                    ],
                    "added": [n for n, _, _ in new_packages],
                    "unreadable": unreadable,
                    "conclusion": result["conclusion"],
                },
                result={
                    "verdicts": dumped,
                    "usages": {v.package: runs.usage_rows(v) for v in verdicts},
                    "graph": traced,
                },
            )
        try:
            notify_telegram.defer(analysis_id=analysis_id)
        except Exception as exc:
            # Alerts are best-effort: never fail or retry the analysis because of Telegram.
            logger.warning(
                "Could not queue Telegram alert for %s (%s)",
                analysis_id,
                type(exc).__name__,
            )
    except Exception as exc:
        # Exception text may echo upstream responses; store and log only the category.
        logger.warning("Pull analysis %s failed (%s)", analysis_id, type(exc).__name__)
        if check_id:
            try:
                gh.complete_check(
                    client,
                    repo,
                    head,
                    check_id,
                    "neutral",
                    {
                        "title": "CodeIntent could not finish this check",
                        "summary": f"The analysis stopped ({type(exc).__name__}). "
                        + (
                            "It will not be retried."
                            if final
                            else "It will be retried."
                        ),
                    },
                    report_url,
                )
            except Exception:
                logger.warning("Could not update check run for %s", analysis_id)
        with store.connection() as conn:
            conn.execute(
                "UPDATE ci_pull_analyses SET status=%s,error=%s,updated_at=now() WHERE id=%s",
                ("failed" if final else "retrying", type(exc).__name__, analysis_id),
            )
        raise RuntimeError(type(exc).__name__) from None
    finally:
        client.close()


def _trace(run, installation_id: int, repo: str, head: str, root, pypi, verdicts):
    """Ask the workspace graph where each upgraded package reaches the code and what its broken lines
    take down. Builds the repository's code map first if no scan has yet. Best effort: without the graph
    the comment simply has no such sections."""
    from codeintent import scans, workspace_graph
    from codeintent.graph import shared

    if not (verdicts and workspace_graph.configured()):
        return {}
    try:
        with run.step("trace through the graph") as note:
            with store.connection() as conn:
                stored = conn.execute(
                    "SELECT projected_at FROM ci_code_maps WHERE installation_id=%s AND repository=%s",
                    (installation_id, repo),
                ).fetchone()
            if stored is None and root is not None:
                # No scan has mapped the default branch yet: map this head instead, until one does.
                scans.save_map(installation_id, repo, head, root, pypi)
            traced = {}
            with shared() as db:
                if stored is None or stored["projected_at"] is None:
                    workspace_graph.project_map(installation_id, repo, db)
                for v in verdicts:
                    places = list(
                        {
                            (loc.file, loc.line): {"file": loc.file, "line": loc.line}
                            for f in v.findings
                            for loc in f.locations
                        }.values()
                    )
                    traced[v.package] = {
                        "reach": workspace_graph.reach(
                            db, installation_id, repo, v.package
                        ),
                        "blast": workspace_graph.blast(
                            db, installation_id, repo, places
                        ),
                    }
            note["detail"] = "; ".join(
                f"{name}: {t['reach']['uses']} use(s), {len(t['reach']['through'])} chain(s), "
                f"{sum(len(b['callers']) for b in t['blast'])} caller(s)"
                for name, t in traced.items()
            )
            return traced
    except Exception as exc:
        logger.warning("Graph trace for %s failed (%s)", repo, type(exc).__name__)
        run.failed_step = None
        return {}


@app.task(
    name="notify_telegram",
    queue="pulls",
    retry=procrastinate.RetryStrategy(max_attempts=3, wait=60),
)
def notify_telegram(analysis_id: str):
    from codeintent import telegram

    try:
        telegram.notify(analysis_id)
    except Exception as exc:
        # Never log exception text: it could describe the request; the token is never in it.
        logger.warning(
            "Telegram alert for %s failed (%s)", analysis_id, type(exc).__name__
        )
        raise RuntimeError(type(exc).__name__) from None


@app.task(
    name="scan_repository",
    queue="scans",
    retry=procrastinate.RetryStrategy(max_attempts=2, wait=300),
)
def scan_repository(installation_id: int, repository: str):
    """Upcoming breakage for one repository's default branch, then alert linked chats about anything new."""
    from codeintent import scans

    try:
        status = scans.run_isolated(installation_id, repository)
    except Exception as exc:
        # Exception text may echo upstream responses; store and log only the category.
        category = (
            exc.args[0]
            if isinstance(exc, scans.ScanError) and exc.args
            else type(exc).__name__
        )
        logger.warning("Repository scan failed (%s)", category)
        scans.fail(installation_id, repository, category)
        raise RuntimeError(category) from None
    if status == "done":
        try:
            notify_upcoming.defer(installation_id=installation_id)
        except Exception as exc:
            logger.warning("Could not queue upcoming alert (%s)", type(exc).__name__)


@app.periodic(cron="23 3 * * *")
@app.task(name="scan_all_repositories", queue="maintenance")
def scan_all_repositories(timestamp: int):
    """Daily: new releases appear without any change to the repository, so every watched one is rescanned."""
    from codeintent import github_app as gh
    from codeintent import scans

    with store.connection() as conn:
        installations = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM ci_installations WHERE deleted_at IS NULL AND NOT suspended"
            ).fetchall()
        ]
    for installation_id in installations:
        client = gh.Client.for_installation(installation_id)
        try:
            repositories = gh.accessible_repositories(client)
            with store.connection() as conn:
                changed = gh.reconcile(conn, installation_id, repositories)
            if changed["added"] or changed["removed"]:
                logger.info(
                    "Installation %s: %s repositories added, %s removed since the last webhook",
                    installation_id,
                    len(changed["added"]),
                    len(changed["removed"]),
                )
        except Exception as exc:
            # Keep the recorded list; a later sweep tries again.
            logger.warning(
                "Could not list repositories of installation %s (%s)",
                installation_id,
                type(exc).__name__,
            )
        finally:
            client.close()
    with store.connection() as conn:
        queued = scans.defer_all(conn)
    logger.info("Queued %s repository scans", queued)


@app.task(
    name="notify_upcoming",
    queue="pulls",
    retry=procrastinate.RetryStrategy(max_attempts=3, wait=60),
)
def notify_upcoming(installation_id: int):
    from codeintent import telegram

    try:
        telegram.notify_upcoming(installation_id)
    except Exception as exc:
        logger.warning("Upcoming alert failed (%s)", type(exc).__name__)
        raise RuntimeError(type(exc).__name__) from None


@app.task(
    name="project_run",
    queue="maintenance",
    retry=procrastinate.RetryStrategy(max_attempts=5, wait=60),
)
def project_run(run_id: str):
    """Copy a finished run into its workspace graph in Neo4j."""
    from codeintent import workspace_graph

    if not workspace_graph.configured():
        return
    try:
        counts = workspace_graph.project(run_id)
    except Exception as exc:
        logger.warning("Graph projection of %s failed (%s)", run_id, type(exc).__name__)
        raise RuntimeError(type(exc).__name__) from None
    if counts:
        logger.info(
            "Projected run %s: %s nodes, %s relationships",
            run_id,
            counts["nodes"],
            counts["relationships"],
        )


@app.task(
    name="index_release",
    queue="ecosystem",
    retry=procrastinate.RetryStrategy(max_attempts=3, wait=120),
)
def index_release(package: str, version: str):
    """Add one public release, its resolved dependency tree, source repository and advisories to the graph."""
    import httpx

    from codeintent import ecosystem, workspace_graph

    if not workspace_graph.configured():
        return
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as http:
            ecosystem.index_release(package, version, http)
    except Exception as exc:
        logger.warning(
            "Indexing %s %s failed (%s)", package, version, type(exc).__name__
        )
        ecosystem._mark(package, version, "failed", error=type(exc).__name__)
        raise RuntimeError(type(exc).__name__) from None


@app.task(
    name="seed_project",
    queue="ecosystem",
    retry=procrastinate.RetryStrategy(max_attempts=2, wait=300),
)
def seed_project(full_name: str):
    """Add a public open-source project and everything it depends on to the ecosystem graph."""
    import httpx

    from codeintent import ecosystem
    from codeintent import github_app as gh

    with store.connection() as conn:
        installation = conn.execute(
            "SELECT id FROM ci_installations WHERE deleted_at IS NULL AND NOT suspended ORDER BY id LIMIT 1"
        ).fetchone()
    if not installation:
        return
    client = gh.Client.for_installation(installation["id"])
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as http:
            ecosystem.seed_project(full_name, client, http)
    except Exception as exc:
        logger.warning("Seeding %s failed (%s)", full_name, type(exc).__name__)
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO ci_ecosystem_projects(full_name,status,error) VALUES (%s,'failed',%s)
                ON CONFLICT(full_name) DO UPDATE SET status='failed',error=EXCLUDED.error""",
                (full_name, type(exc).__name__),
            )
        raise RuntimeError(type(exc).__name__) from None
    finally:
        client.close()


@app.periodic(cron="*/10 * * * *")
@app.task(name="ecosystem_sweep", queue="maintenance")
def ecosystem_sweep(timestamp: int):
    from codeintent import ecosystem

    queued = ecosystem.sweep()
    if queued:
        logger.info("Re-queued %s ecosystem releases", queued)


@app.periodic(cron="*/5 * * * *")
@app.task(name="project_pending_runs", queue="maintenance")
def project_pending_runs(timestamp: int):
    """Catch up runs whose projection never happened (Neo4j unreachable, or queued before a restart)."""
    from codeintent import runs

    with store.connection() as conn:
        pending = conn.execute(
            """SELECT id FROM ci_runs WHERE finished_at IS NOT NULL AND projected_at IS NULL
              AND finished_at < now()-interval '2 minutes' ORDER BY finished_at LIMIT 50"""
        ).fetchall()
    for row in pending:
        runs.queue_projection(str(row["id"]))


@app.periodic(cron="*/10 * * * *")
@app.task(name="ops_watch", queue="maintenance")
def ops_watch(timestamp: int):
    """Tell the operator's Telegram chat about jobs that failed for good in the last ten minutes."""
    from datetime import UTC, datetime, timedelta

    from codeintent import ops, telegram

    chat = ops.operator_chat()
    if chat is None or not telegram.configured():
        return
    since = datetime.fromtimestamp(timestamp, UTC) - timedelta(minutes=10)
    with store.connection() as conn:
        lines = ops.problems(conn, since)
    if lines:
        telegram.send(
            chat,
            "<b>CodeIntent operations</b>\n"
            + "\n".join(f"• {telegram.esc(line)}" for line in lines),
        )


@app.periodic(cron="17 */6 * * *")
@app.task(name="graph_keepalive", queue="maintenance")
def graph_keepalive(timestamp: int):
    from codeintent import graph

    with graph.driver() as db:
        graph.run_query(db, "RETURN 1")


@app.periodic(cron="* * * * *")
@app.task(name="worker_heartbeat", queue="maintenance")
def heartbeat(timestamp: int):
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_workers(name) VALUES ('imports') ON CONFLICT(name) DO UPDATE SET heartbeat=now()"
        )
        # Use Procrastinate worker liveness metadata for orphan recovery, rather than guessing from task duration.
        rows = conn.execute("""SELECT j.id FROM procrastinate_jobs j LEFT JOIN procrastinate_workers w ON w.id=j.worker_id
            WHERE j.status='doing' AND j.task_name IN ('import_repository','investigate_question','analyze_pull_request','scan_repository') AND (j.worker_id IS NULL OR w.last_heartbeat < now()-interval '3 minutes')""").fetchall()
        for row in rows:
            conn.execute(
                "UPDATE procrastinate_jobs SET status='todo',worker_id=NULL,abort_requested=false,scheduled_at=now() WHERE id=%s AND status='doing'",
                (row["id"],),
            )
