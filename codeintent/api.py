"""Authenticated service API. The web server is the public boundary."""

from __future__ import annotations

import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from codeintent import store
from codeintent.github import canonical_repository
from codeintent.settings import production_check

logger = logging.getLogger(__name__)
gate = threading.BoundedSemaphore(2)


@asynccontextmanager
async def lifespan(app):
    production_check()
    yield


app = FastAPI(
    title="Code Intent API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)


def authenticated(x_api_key: str = Header(default="")):
    secret = os.getenv("CODEINTENT_API_SECRET", "")
    if not secret or not hmac.compare_digest(x_api_key, secret):
        raise HTTPException(401, "Service authorization required")


def operator(x_operator_key: str = Header(default=""), _=Depends(authenticated)):
    secret = os.getenv("CODEINTENT_OPERATOR_TOKEN", "")
    if not secret or not hmac.compare_digest(x_operator_key, secret):
        raise HTTPException(403, "Sign in as the workspace operator to manage imports")


class Question(BaseModel):
    question: str = Field(min_length=8, max_length=800)
    index_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    repository: str = "encode/httpx"

    @field_validator("question")
    @classmethod
    def trim(cls, value):
        if len(value.strip()) < 8:
            raise ValueError("Use a question of at least 8 characters")
        return value.strip()


class ImportRequest(BaseModel):
    repository: str
    limit: int = Field(default=12, ge=1, le=30)
    pull_requests: list[int] = Field(default_factory=list, max_length=30)
    issues: list[int] = Field(default_factory=list, max_length=10)

    @field_validator("repository")
    @classmethod
    def canonical(cls, value):
        return canonical_repository(value)

    @field_validator("pull_requests", "issues")
    @classmethod
    def numbers(cls, value):
        if any(n < 1 or n > 10000000 for n in value):
            raise ValueError("Invalid GitHub issue or pull request number")
        return list(dict.fromkeys(value))


def public_job(row):
    return {
        k: v for k, v in row.items() if k not in {"checkpoint", "options", "task_id"}
    }


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/ready", dependencies=[Depends(authenticated)])
def ready():
    try:
        with store.connection() as conn:
            conn.execute("SELECT 1 FROM ci_schema_versions LIMIT 1")
        from codeintent.graph import driver

        with driver() as db:
            db.verify_connectivity()
        return {"status": "ready"}
    except Exception:
        raise HTTPException(503, "Database or graph is unavailable") from None


@app.get("/repositories", dependencies=[Depends(authenticated)])
def repositories():
    with store.connection() as conn:
        repos = conn.execute("""SELECT r.*,i.revision,i.created_at AS indexed_at,
            jsonb_array_length(i.corpus->'documents') AS sources,i.corpus->'coverage' AS coverage
            FROM ci_repositories r LEFT JOIN ci_indexes i ON i.id=r.ready_index ORDER BY r.name""").fetchall()
        jobs = conn.execute(
            "SELECT * FROM ci_imports ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
        worker = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM procrastinate_workers WHERE last_heartbeat>now()-interval '3 minutes') AS online"
        ).fetchone()
    return {
        "repositories": repos,
        "imports": [public_job(j) for j in jobs],
        "worker_online": worker["online"],
    }


@app.post("/imports", dependencies=[Depends(operator)], status_code=202)
def create_import(body: ImportRequest):
    store.consume_quota("imports", int(os.getenv("CODEINTENT_IMPORTS_PER_DAY", "20")))
    return public_job(
        store.enqueue(body.repository, body.model_dump(exclude={"repository"}))
    )


@app.get("/imports/{ident}", dependencies=[Depends(authenticated)])
def get_import(ident: UUID, after: int = 0):
    row = store.job(str(ident))
    if not row:
        raise HTTPException(404, "Import not found")
    with store.connection() as conn:
        events = conn.execute(
            "SELECT * FROM ci_events WHERE import_id=%s AND id>%s ORDER BY id LIMIT 200",
            (ident, after),
        ).fetchall()
    return {**public_job(row), "events": events}


@app.post("/imports/{ident}/cancel", dependencies=[Depends(operator)])
def cancel(ident: UUID):
    with store.connection() as conn:
        row = conn.execute(
            "UPDATE ci_imports SET cancelled=true,status='cancelled',updated_at=now() WHERE id=%s AND status IN ('queued','running','retrying') RETURNING id",
            (ident,),
        ).fetchone()
    if not row:
        raise HTTPException(409, "Import is already finished or does not exist")
    return {"status": "cancelled"}


@app.post("/imports/{ident}/retry", dependencies=[Depends(operator)], status_code=202)
def retry(ident: UUID):
    from codeintent.tasks import import_repository

    with store.connection() as conn:
        row = conn.execute(
            "SELECT * FROM ci_imports WHERE id=%s FOR UPDATE", (ident,)
        ).fetchone()
        if not row or row["status"] not in {"failed", "cancelled"}:
            raise HTTPException(409, "Only a failed or cancelled import can be retried")
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (row["repository"],)
        )
        active = conn.execute(
            "SELECT 1 FROM ci_imports WHERE repository=%s AND id<>%s AND status IN ('queued','running','retrying')",
            (row["repository"], ident),
        ).fetchone()
        if active:
            raise HTTPException(
                409, "Another import is already running for this repository"
            )
        # Cancel queued retries of the previous attempt before enqueuing a fresh task.
        conn.execute(
            "UPDATE procrastinate_jobs SET status='cancelled' WHERE id=%s AND status='todo'",
            (row["task_id"],),
        )
        task_id = import_repository.configure(
            connection=conn, lock="repo:" + row["repository"]
        ).defer(import_id=str(ident))
        conn.execute(
            "UPDATE ci_imports SET cancelled=false,status='queued',error=NULL,task_id=%s,updated_at=now() WHERE id=%s",
            (task_id, ident),
        )
    return {"id": str(ident), "status": "queued"}


@app.get("/reports", dependencies=[Depends(authenticated)])
def reports(repository: str | None = None):
    with store.connection() as conn:
        rows = conn.execute(
            """SELECT p.id,p.question,p.created_at,p.index_id,r.name AS repository,p.result->'answer'->>'status' AS status
            FROM ci_reports p JOIN ci_indexes i ON i.id=p.index_id JOIN ci_repositories r ON r.id=i.repository_id
            WHERE (%s::text IS NULL OR r.name=%s) ORDER BY p.created_at DESC LIMIT 50""",
            (repository, repository),
        ).fetchall()
    return {"reports": rows}


@app.get("/reports/{ident}", dependencies=[Depends(authenticated)])
def report(ident: UUID):
    with store.connection() as conn:
        row = conn.execute(
            "SELECT result FROM ci_reports WHERE id=%s", (ident,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Investigation not found")
    return row["result"]


@app.get("/indexes/{scope}", dependencies=[Depends(authenticated)])
def index_details(scope: str):
    row = store.get_index(scope)
    if not row:
        raise HTTPException(404, "Index not found")
    return {
        "index_id": row["id"],
        "repository": row["corpus"]["repository"],
        "revision": row["revision"],
        "coverage": row["corpus"]["coverage"],
        "decisions": row["decisions"],
        "decision_sources": [
            s
            for s in row["corpus"]["documents"]
            if any(
                c["source_id"] == s["id"]
                for d in row["decisions"]
                for c in d["citations"]
            )
        ],
        "created_at": row["created_at"],
    }


@app.post("/investigate", dependencies=[Depends(authenticated)])
def ask(body: Question, x_client_key: str = Header(default="anonymous")):
    indexed = store.get_index(body.index_id, body.repository)
    if not indexed:
        raise HTTPException(
            409,
            "This repository has no ready index yet. Open Repositories to check its import.",
        )
    key = store.cache_key(indexed["id"], body.question)
    cached = store.get_cached(key)
    if cached:
        return {**cached, "cached": True}
    if not gate.acquire(blocking=False):
        raise HTTPException(429, "Two investigations are running. Try again shortly.")
    try:
        store.consume_quota(
            "client:" + x_client_key[:100],
            int(os.getenv("CODEINTENT_QUESTIONS_PER_DAY", "30")),
        )
        store.consume_quota(
            "global", int(os.getenv("CODEINTENT_GLOBAL_QUESTIONS_PER_DAY", "300"))
        )
        from codeintent.investigate import investigate

        result = investigate(
            body.question, indexed["corpus"], indexed["decisions"], scope=indexed["id"]
        )
        return store.save_report(result, key)
    except store.QuotaExceeded:
        raise HTTPException(
            429,
            "The daily investigation limit has been reached. Saved reports remain available.",
        ) from None
    except Exception as exc:
        logger.warning("Investigation failed (%s)", type(exc).__name__)
        raise HTTPException(
            502,
            "The evidence could not be verified. Retry shortly; saved investigations remain available.",
        ) from None
    finally:
        gate.release()


@app.exception_handler(store.QuotaExceeded)
async def quota_handler(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=429, content={"detail": "The daily import limit has been reached"}
    )
