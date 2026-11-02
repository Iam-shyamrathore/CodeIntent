"""Durable investigations: short HTTP requests, restartable provider work."""

import logging
import os
import uuid

from codeintent import store

logger = logging.getLogger(__name__)


def submit(indexed: dict, question: str, key: str, client: str) -> dict:
    from codeintent.tasks import investigate_question

    with store.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
        row = conn.execute(
            "SELECT * FROM ci_questions WHERE cache_key=%s", (key,)
        ).fetchone()
        if row and row["status"] != "failed":
            return {"job_id": str(row["id"]), "status": row["status"]}
        store.consume_quota(
            "client:" + client[:100],
            int(os.getenv("CODEINTENT_QUESTIONS_PER_DAY", "30")),
            conn=conn,
        )
        store.consume_quota(
            "global",
            int(os.getenv("CODEINTENT_GLOBAL_QUESTIONS_PER_DAY", "300")),
            conn=conn,
        )
        ident = str(row["id"]) if row else str(uuid.uuid4())
        conn.execute(
            """INSERT INTO ci_questions(id,cache_key,index_id,question) VALUES (%s,%s,%s,%s)
            ON CONFLICT(cache_key) DO UPDATE SET status='queued',error=NULL,updated_at=now()""",
            (ident, key, indexed["id"], question),
        )
        task = investigate_question.configure(
            connection=conn, lock="question:" + key, priority=20
        ).defer(question_id=ident)
        conn.execute("UPDATE ci_questions SET task_id=%s WHERE id=%s", (task, ident))
    return {"job_id": ident, "status": "queued"}


def status(ident: str):
    with store.connection() as conn:
        row = conn.execute(
            """SELECT q.id,q.status,q.error,p.result FROM ci_questions q
            LEFT JOIN ci_reports p ON p.id=q.report_id WHERE q.id=%s""",
            (ident,),
        ).fetchone()
    if not row:
        return None
    return {
        "job_id": str(row["id"]),
        "status": row["status"],
        "detail": row["error"],
        "result": row["result"],
    }


def process(context, question_id: str):
    from codeintent.investigate import investigate

    with store.connection() as conn:
        row = conn.execute(
            "UPDATE ci_questions SET status='running',error=NULL,updated_at=now() WHERE id=%s AND status<>'ready' RETURNING *",
            (question_id,),
        ).fetchone()
    if not row:
        return
    try:
        result = store.get_cached(row["cache_key"])
        if not result:
            indexed = store.get_index(row["index_id"])
            if not indexed:
                raise ValueError("Index unavailable")
            result = store.save_report(
                investigate(
                    row["question"],
                    indexed["corpus"],
                    indexed["decisions"],
                    scope=indexed["id"],
                ),
                row["cache_key"],
            )
        with store.connection() as conn:
            conn.execute(
                "UPDATE ci_questions SET status='ready',report_id=%s,error=NULL,updated_at=now() WHERE id=%s",
                (result["report_id"], question_id),
            )
    except Exception as exc:
        logger.warning("Question %s failed (%s)", question_id, type(exc).__name__)
        with store.connection() as conn:
            conn.execute(
                "UPDATE ci_questions SET status=%s,error=%s,updated_at=now() WHERE id=%s",
                (
                    "retrying" if context.job.attempts < 3 else "failed",
                    "The evidence could not be verified. Retry shortly; saved investigations remain available.",
                    question_id,
                ),
            )
        raise RuntimeError(type(exc).__name__) from None
