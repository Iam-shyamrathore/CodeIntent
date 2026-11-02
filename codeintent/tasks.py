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


@app.periodic(cron="* * * * *")
@app.task(name="worker_heartbeat", queue="maintenance")
def heartbeat(timestamp: int):
    with store.connection() as conn:
        conn.execute(
            "INSERT INTO ci_workers(name) VALUES ('imports') ON CONFLICT(name) DO UPDATE SET heartbeat=now()"
        )
        # Use Procrastinate worker liveness metadata for orphan recovery, rather than guessing from task duration.
        rows = conn.execute("""SELECT j.id FROM procrastinate_jobs j LEFT JOIN procrastinate_workers w ON w.id=j.worker_id
            WHERE j.status='doing' AND j.task_name IN ('import_repository','investigate_question') AND (j.worker_id IS NULL OR w.last_heartbeat < now()-interval '3 minutes')""").fetchall()
        for row in rows:
            conn.execute(
                "UPDATE procrastinate_jobs SET status='todo',worker_id=NULL,abort_requested=false,scheduled_at=now() WHERE id=%s AND status='doing'",
                (row["id"],),
            )
