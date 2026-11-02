"""PostgreSQL source ledger and transactional queue submission."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from codeintent.settings import ROOT, required


@contextmanager
def connection():
    with psycopg.connect(
        required("DATABASE_URL"), row_factory=dict_row, connect_timeout=10
    ) as conn:
        conn.execute("SET statement_timeout='30s'")
        yield conn


def migrate():
    from procrastinate.schema import SchemaManager

    with connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(783462519)")
        if not conn.execute(
            "SELECT to_regclass('procrastinate_jobs') AS name"
        ).fetchone()["name"]:
            conn.execute(SchemaManager.get_schema())
        for file in sorted((ROOT / "migrations").glob("*.sql")):
            version = int(file.name.split("_")[0])
            exists = conn.execute(
                "SELECT to_regclass('ci_schema_versions') AS name"
            ).fetchone()["name"]
            if (
                exists
                and conn.execute(
                    "SELECT 1 FROM ci_schema_versions WHERE version=%s", (version,)
                ).fetchone()
            ):
                continue
            conn.execute(file.read_text())
            conn.execute(
                "INSERT INTO ci_schema_versions(version) VALUES (%s)", (version,)
            )


def enqueue(repository: str, options: dict) -> dict:
    from codeintent.tasks import import_repository

    with connection() as conn:
        # Serialize creation per repository to make repeated submissions idempotent.
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (repository,)
        )
        existing = conn.execute(
            "SELECT * FROM ci_imports WHERE repository=%s AND status IN ('queued','running','retrying')",
            (repository,),
        ).fetchone()
        if existing:
            return existing
        ident = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO ci_imports(id,repository,options) VALUES (%s,%s,%s)",
            (ident, repository, Jsonb(options)),
        )
        task_id = import_repository.configure(
            connection=conn, lock=f"repo:{repository}"
        ).defer(import_id=ident)
        conn.execute("UPDATE ci_imports SET task_id=%s WHERE id=%s", (task_id, ident))
        return conn.execute("SELECT * FROM ci_imports WHERE id=%s", (ident,)).fetchone()


def job(ident: str) -> dict | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM ci_imports WHERE id=%s", (ident,)).fetchone()


def progress(
    ident: str,
    stage: str,
    percent: int,
    message: str,
    *,
    checkpoint: dict | None = None,
):
    with connection() as conn:
        row = conn.execute(
            "SELECT cancelled FROM ci_imports WHERE id=%s FOR UPDATE", (ident,)
        ).fetchone()
        if not row or row["cancelled"]:
            raise Cancelled()
        conn.execute(
            "UPDATE ci_imports SET status='running',stage=%s,progress=%s,error=NULL,updated_at=now(),checkpoint=checkpoint || %s WHERE id=%s",
            (stage, percent, Jsonb(checkpoint or {}), ident),
        )
        conn.execute(
            "INSERT INTO ci_events(import_id,stage,message) VALUES (%s,%s,%s)",
            (ident, stage, message),
        )


class Cancelled(Exception):
    pass


def save_index(corpus: dict, decisions: list, scope: str, *, publish: bool = False):
    with connection() as conn:
        conn.execute(
            "INSERT INTO ci_repositories(id,name) VALUES (%s,%s) ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name",
            (corpus["repository_id"], corpus["repository"]),
        )
        conn.execute(
            "INSERT INTO ci_indexes(id,repository_id,revision,corpus,decisions) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
            (
                scope,
                corpus["repository_id"],
                corpus["revision"],
                Jsonb(corpus),
                Jsonb(decisions),
            ),
        )
        if publish:
            conn.execute(
                "UPDATE ci_indexes SET published_at=COALESCE(published_at,now()) WHERE id=%s",
                (scope,),
            )
            conn.execute(
                "UPDATE ci_repositories SET ready_index=%s WHERE id=%s",
                (scope, corpus["repository_id"]),
            )


def publish(ident: str, scope: str):
    with connection() as conn:
        row = conn.execute(
            "SELECT cancelled FROM ci_imports WHERE id=%s FOR UPDATE", (ident,)
        ).fetchone()
        if row["cancelled"]:
            raise Cancelled()
        conn.execute(
            "UPDATE ci_indexes SET published_at=COALESCE(published_at,now()) WHERE id=%s",
            (scope,),
        )
        conn.execute(
            "UPDATE ci_repositories SET ready_index=%s WHERE id=(SELECT repository_id FROM ci_indexes WHERE id=%s)",
            (scope, scope),
        )
        conn.execute(
            "UPDATE ci_imports SET status='ready',stage='ready',progress=100,index_id=%s,updated_at=now() WHERE id=%s",
            (scope, ident),
        )
        conn.execute(
            "INSERT INTO ci_events(import_id,stage,message) VALUES (%s,'ready','Index published. Ready for questions.')",
            (ident,),
        )


def get_index(scope: str | None = None, repository: str | None = None) -> dict | None:
    with connection() as conn:
        if scope:
            return conn.execute(
                "SELECT * FROM ci_indexes WHERE id=%s AND published_at IS NOT NULL",
                (scope,),
            ).fetchone()
        return conn.execute(
            "SELECT i.* FROM ci_indexes i JOIN ci_repositories r ON r.ready_index=i.id WHERE r.name=%s",
            (repository or "encode/httpx",),
        ).fetchone()


def cache_key(scope: str, question: str) -> str:
    import os

    return hashlib.sha256(
        json.dumps(
            [
                scope,
                question.strip(),
                os.getenv("VERTEX_GENERATION_MODEL", "gemini-2.5-flash"),
                "evidence-v3",
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def get_cached(key: str):
    with connection() as conn:
        row = conn.execute(
            "SELECT result FROM ci_reports WHERE cache_key=%s", (key,)
        ).fetchone()
        return row["result"] if row else None


def save_report(result: dict, key: str) -> dict:
    result = {**result, "report_id": str(uuid.uuid4())}
    with connection() as conn:
        row = conn.execute(
            "INSERT INTO ci_reports(id,index_id,question,result,cache_key) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(cache_key) DO UPDATE SET cache_key=EXCLUDED.cache_key RETURNING result",
            (
                result["report_id"],
                result["index_id"],
                result["question"],
                Jsonb(result),
                key,
            ),
        ).fetchone()
        return row["result"]


def consume_quota(bucket: str, limit: int):
    # The counter increment and limit check happen under the same row lock.
    with connection() as conn:
        row = conn.execute(
            "INSERT INTO ci_usage(bucket,count) VALUES (%s,1) ON CONFLICT(bucket,day) DO UPDATE SET count=ci_usage.count+1 WHERE ci_usage.count < %s RETURNING count",
            (bucket, limit),
        ).fetchone()
        if not row:
            raise QuotaExceeded()


class QuotaExceeded(Exception):
    pass
