"""Durable staged imports. PostgreSQL is the ledger; Neo4j is a rebuildable projection."""

from __future__ import annotations

import logging

import procrastinate

from codeintent import store
from codeintent.settings import required

logger = logging.getLogger(__name__)
app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(
        conninfo=required("DATABASE_URL"), min_size=1, max_size=4
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
    try:
        diff = gh.dependency_changes(client, repo, number, row["base_sha"], head)
        if not diff["files"]:
            with store.connection() as conn:
                conn.execute(
                    "UPDATE ci_pull_analyses SET status='skipped',diff=%s,updated_at=now() WHERE id=%s",
                    (Jsonb(diff), analysis_id),
                )
            return
        title = client.json(f"/repos/{repo}/pulls/{number}").get("title")
        check_id = check_id or gh.create_check(client, repo, head)
        with store.connection() as conn:
            conn.execute(
                "UPDATE ci_pull_analyses SET status='diffed',diff=%s,title=%s,check_run_id=%s,updated_at=now() WHERE id=%s",
                (Jsonb(diff), title, check_id, analysis_id),
            )
        pairs, added = gh.upgrades(diff)
        verdicts, new_packages = [], []
        with (
            httpx.Client(timeout=60, follow_redirects=True) as pypi,
            repository.using(client.token),
        ):
            if pairs:
                with repository.temporary() as folder:
                    root = repository.download(repo, head, Path(folder), client.token())
                    verdicts = [
                        evaluate(name, a, b, root, pypi) for name, a, b in pairs[:20]
                    ]
            for name, version in added[:20]:
                checks = advisories.check([(name, version)], pypi) if version else []
                new_packages.append((name, version, checks))
        notes = [
            f"{name}: one side is a version range, not an exact version, so there is no pair to compare."
            for name in gh.unresolved(diff)
        ]
        body = report.comment(verdicts, new_packages, report_url, notes)
        with store.connection() as conn:
            previous = conn.execute(
                "SELECT comment_id FROM ci_pull_analyses WHERE repository=%s AND number=%s AND comment_id IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
                (repo, number),
            ).fetchone()
        comment_id = gh.upsert_comment(
            client, repo, number, body, previous["comment_id"] if previous else None
        )
        result = report.check_output(verdicts, body)
        check_id = gh.complete_check(
            client,
            repo,
            head,
            check_id,
            result["conclusion"],
            result["output"],
            report_url,
        )
        with store.connection() as conn:
            conn.execute(
                "UPDATE ci_pull_analyses SET status='reported',verdicts=%s,verdict=%s,check_run_id=%s,comment_id=%s,updated_at=now() WHERE id=%s",
                (
                    Jsonb([v.model_dump(mode="json") for v in verdicts]),
                    report.worst(verdicts) if verdicts else None,
                    check_id,
                    comment_id,
                    analysis_id,
                ),
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
        final = context.job.attempts >= 3
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
