"""Authenticated service API. The web server is the public boundary."""

from __future__ import annotations

import base64
import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from codeintent import store
from codeintent.github import canonical_repository
from codeintent.settings import production_check

logger = logging.getLogger(__name__)
gate = threading.BoundedSemaphore(2)


_mcp: dict = {}


@asynccontextmanager
async def lifespan(app):
    production_check()
    if os.getenv("CODEINTENT_MCP", "1") == "0":
        yield
        return
    from codeintent import mcp_server

    # A fresh endpoint per lifespan: its session manager can run only once.
    _mcp["app"] = mcp_server.mcp_app(
        os.getenv("CODEINTENT_MCP_TOKEN", "").strip() or None, workspaces=True
    )
    async with mcp_server.server.session_manager.run():
        yield
    _mcp.clear()


class MCPRoute:
    """Sends ``/mcp`` to the MCP endpoint (bearer-authenticated); everything else to the API."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        endpoint = _mcp.get("app")
        if scope["type"] == "http" and scope["path"] == "/mcp" and endpoint:
            await endpoint(scope, receive, send)
            return
        await self.app(scope, receive, send)


app = FastAPI(
    title="Code Intent API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(MCPRoute)


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
        from codeintent.graph import driver, run_query

        with driver() as db:
            run_query(db, "RETURN 1 AS ok")
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


def suggested_questions(decisions: list) -> list:
    """Starter questions derived from recorded decision assertions."""
    templates = {
        "introduce": "Why was {subject} introduced?",
        "remove": "Why was {subject} removed?",
        "deprecate": "Why was {subject} deprecated?",
        "restore": "Why was {subject} brought back?",
        "replace": "What replaced {subject}, and why?",
        "retain": "Why was {subject} kept in place?",
    }
    ranked = sorted(
        decisions,
        key=lambda d: (
            d.get("status") != "replaced_in_aspect" and not d.get("replacement"),
            d.get("date", ""),
        ),
        reverse=True,
    )
    suggestions, seen = [], set()
    for decision in ranked:
        subject = decision.get("subject", "").strip("` ")
        if not subject or subject.lower() in seen:
            continue
        if decision.get("replacement"):
            question = f"Was {subject} fully rolled back, or only partly?"
        else:
            question = templates.get(decision.get("action"), "").format(subject=subject)
        if question:
            suggestions.append(question)
            seen.add(subject.lower())
        if len(suggestions) == 4:
            break
    return suggestions


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
        "suggested": suggested_questions(row["decisions"]),
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
    if os.getenv("CODEINTENT_ASYNC_QUESTIONS") == "1":
        from fastapi.responses import JSONResponse

        from codeintent.questions import submit

        try:
            return JSONResponse(
                status_code=202,
                content=submit(indexed, body.question, key, x_client_key),
            )
        except store.QuotaExceeded:
            raise HTTPException(
                429,
                "The daily investigation limit has been reached. Saved reports remain available.",
            ) from None
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


@app.get("/questions/{ident}", dependencies=[Depends(authenticated)])
def question_status(ident: UUID):
    from codeintent.questions import status

    row = status(str(ident))
    if not row:
        raise HTTPException(404, "Investigation job not found")
    return row


@app.post("/github/webhook", status_code=202)
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
):
    """GitHub App deliveries: verify the raw body, record, enqueue. No slow work here."""
    import json

    from codeintent.github_app import handle_webhook, verify_signature

    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(503, "GitHub App webhooks are not configured")
    body = await request.body()
    if not verify_signature(body, secret, x_hub_signature_256):
        raise HTTPException(401, "Invalid webhook signature")
    if not x_github_event or not x_github_delivery or len(x_github_delivery) > 100:
        raise HTTPException(400, "X-GitHub-Event and X-GitHub-Delivery are required")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(400, "Webhook body must be JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(400, "Webhook body must be a JSON object")
    try:
        code, content = await run_in_threadpool(
            handle_webhook, x_github_event, x_github_delivery, payload
        )
    except Exception as exc:
        # Do not log payload contents; GitHub redelivery will retry this delivery id.
        logger.warning("Webhook %s failed (%s)", x_github_event, type(exc).__name__)
        raise HTTPException(500, "Webhook could not be recorded") from None
    return JSONResponse(status_code=code, content=content)


# --- GitHub App dashboard (read-only; the web server calls these with the service secret) ---------

GITHUB_NAME = r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,99})$"
VERDICT_ORDER = ("breaks", "not-checked", "needs-change", "no-known-impact")


def _encode_cursor(created_at, ident) -> str:
    raw = f"{created_at.isoformat()}|{ident}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, ident = raw.split("|", 1)
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is None:
            raise ValueError
        return moment, UUID(ident)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "Invalid cursor") from None


def _package_summary(row: dict) -> list[dict]:
    """One line per changed package: the verdict when decided, otherwise the manifest change."""
    verdicts = row.get("verdicts")
    if isinstance(verdicts, list) and verdicts:
        return [
            {
                "package": v.get("package"),
                "start": v.get("start"),
                "end": v.get("end"),
                "verdict": v.get("verdict"),
                "label": v.get("label"),
            }
            for v in verdicts
            if isinstance(v, dict)
        ]
    changed = (row.get("diff") or {}).get("changed") or []
    summary = []
    for change in changed:
        if not isinstance(change, dict):
            continue
        old, new = change.get("old") or {}, change.get("new") or {}
        summary.append(
            {
                "package": change.get("name"),
                "start": old.get("locked_version") or old.get("specifier") or None,
                "end": new.get("locked_version") or new.get("specifier") or None,
                "verdict": None,
                "label": None,
            }
        )
    return summary


def _pull_row(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "installation_id": row["installation_id"],
        "repository": row["repository"],
        "number": row["number"],
        "title": row["title"],
        "head_sha": row["head_sha"],
        "status": row["status"],
        "verdict": row["verdict"],
        "packages": _package_summary(row),
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _installation_scope(installations: list[int] | None) -> list[int] | None:
    """Optional `installations=` filter (repeatable): the ids a signed-in user may read."""
    if installations is None:
        return None
    if len(installations) > 100 or any(i < 1 for i in installations):
        raise HTTPException(422, "Invalid installations filter")
    return installations


def _upcoming_summary(row: dict) -> dict | None:
    if not row.get("scan_status"):
        return None
    items = [i for i in row.get("scan_items") or [] if isinstance(i, dict)]
    verdicts = [(i.get("verdict") or {}).get("verdict") for i in items]
    return {
        "status": row["scan_status"],
        "scanned_at": row["scan_at"],
        "breaks": verdicts.count("breaks"),
        "needs_change": verdicts.count("needs-change"),
        "advisories": sum(
            1
            for i in items
            if (i.get("advisories") or {}).get("status") == "advisories"
            and any(
                not a.get("withdrawn")
                for a in (i.get("advisories") or {}).get("advisories") or []
                if isinstance(a, dict)
            )
        ),
    }


@app.get("/app/installations", dependencies=[Depends(authenticated)])
def app_installations(installations: list[int] | None = Query(default=None)):
    scope = _installation_scope(installations)
    with store.connection() as conn:
        rows = conn.execute(
            """SELECT i.id,i.account_login,i.account_type,i.suspended,i.created_at,i.updated_at,
              (SELECT count(*) FROM ci_installation_repositories r WHERE r.installation_id=i.id) AS repositories,
              (SELECT count(*) FROM ci_pull_analyses a WHERE a.installation_id=i.id) AS analyses
            FROM ci_installations i WHERE i.deleted_at IS NULL
              AND (%s::bigint[] IS NULL OR i.id=ANY(%s::bigint[]))
            ORDER BY lower(i.account_login),i.id""",
            (scope, scope),
        ).fetchall()
    return {"installations": rows}


@app.get(
    "/app/installations/{installation_id}/repositories",
    dependencies=[Depends(authenticated)],
)
def app_installation_repositories(installation_id: int):
    if installation_id < 1:
        raise HTTPException(404, "Installation not found")
    with store.connection() as conn:
        installation = conn.execute(
            """SELECT id,account_login,account_type,suspended,created_at FROM ci_installations
            WHERE id=%s AND deleted_at IS NULL""",
            (installation_id,),
        ).fetchone()
        if not installation:
            raise HTTPException(404, "Installation not found")
        rows = conn.execute(
            """SELECT r.repository_id,r.full_name,r.private,r.created_at,
              (SELECT count(*) FROM ci_pull_analyses a
                WHERE a.installation_id=r.installation_id AND a.repository=r.full_name) AS analyses,
              (SELECT coalesce(jsonb_object_agg(v.verdict,v.n),'{}'::jsonb) FROM (
                SELECT a.verdict,count(*) AS n FROM ci_pull_analyses a
                WHERE a.installation_id=r.installation_id AND a.repository=r.full_name AND a.verdict IS NOT NULL
                GROUP BY a.verdict) v) AS verdict_counts,
              last.id AS last_id,last.number AS last_number,last.title AS last_title,
              last.status AS last_status,last.verdict AS last_verdict,last.created_at AS last_created_at,
              decided.id AS decided_id,decided.number AS decided_number,decided.title AS decided_title,
              decided.verdict AS decided_verdict,decided.created_at AS decided_created_at,
              s.status AS scan_status,s.scanned_at AS scan_at,s.items AS scan_items
            FROM ci_installation_repositories r
            LEFT JOIN ci_repository_scans s
              ON s.installation_id=r.installation_id AND s.repository=r.full_name
            LEFT JOIN LATERAL (
              SELECT a.id,a.number,a.title,a.status,a.verdict,a.created_at FROM ci_pull_analyses a
              WHERE a.installation_id=r.installation_id AND a.repository=r.full_name
              ORDER BY a.created_at DESC,a.id DESC LIMIT 1) last ON true
            LEFT JOIN LATERAL (
              SELECT a.id,a.number,a.title,a.verdict,a.created_at FROM ci_pull_analyses a
              WHERE a.installation_id=r.installation_id AND a.repository=r.full_name AND a.verdict IS NOT NULL
              ORDER BY a.created_at DESC,a.id DESC LIMIT 1) decided ON true
            WHERE r.installation_id=%s ORDER BY lower(r.full_name)""",
            (installation_id,),
        ).fetchall()
    repositories = []
    for row in rows:
        last = None
        if row["last_id"]:
            last = {
                "id": str(row["last_id"]),
                "number": row["last_number"],
                "title": row["last_title"],
                "status": row["last_status"],
                "verdict": row["last_verdict"],
                "created_at": row["last_created_at"],
            }
        decided = None
        if row["decided_id"]:
            decided = {
                "id": str(row["decided_id"]),
                "number": row["decided_number"],
                "title": row["decided_title"],
                "verdict": row["decided_verdict"],
                "created_at": row["decided_created_at"],
            }
        repositories.append(
            {
                "repository_id": row["repository_id"],
                "full_name": row["full_name"],
                "private": row["private"],
                "created_at": row["created_at"],
                "analyses": row["analyses"],
                "verdict_counts": {
                    k: row["verdict_counts"].get(k, 0) for k in VERDICT_ORDER
                },
                "last_analysis": last,
                "last_verdict": decided,
                "upcoming": _upcoming_summary(row),
            }
        )
    return {"installation": installation, "repositories": repositories}


def _homes(conn, owner: str, name: str, installation: int | None, scope) -> list[dict]:
    """The live installations watching ``owner/name`` within the caller's scope, or 404.

    Resolving through live installations only means removed or uninstalled repositories and other
    installations' data never surface.
    """
    homes = conn.execute(
        """SELECT r.installation_id,r.full_name,r.private,i.account_login FROM ci_installation_repositories r
        JOIN ci_installations i ON i.id=r.installation_id AND i.deleted_at IS NULL
        WHERE lower(r.full_name)=lower(%s) AND (%s::bigint IS NULL OR r.installation_id=%s)
          AND (%s::bigint[] IS NULL OR r.installation_id=ANY(%s::bigint[]))
        ORDER BY r.installation_id""",
        (f"{owner}/{name}", installation, installation, scope, scope),
    ).fetchall()
    if not homes:
        raise HTTPException(404, "Repository not found")
    return homes


@app.get(
    "/app/repositories/{owner}/{name}/pulls", dependencies=[Depends(authenticated)]
)
def app_repository_pulls(
    owner: str = Path(pattern=GITHUB_NAME, max_length=100),
    name: str = Path(pattern=GITHUB_NAME, max_length=100),
    installation: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=200),
    installations: list[int] | None = Query(default=None),
):
    scope = _installation_scope(installations)
    after = _decode_cursor(cursor) if cursor else None
    with store.connection() as conn:
        homes = _homes(conn, owner, name, installation, scope)
        ids = [h["installation_id"] for h in homes]
        full_name = homes[0]["full_name"]
        rows = conn.execute(
            """SELECT id,installation_id,repository,number,title,head_sha,status,verdict,verdicts,
              jsonb_build_object('changed',diff->'changed') AS diff,error,created_at,updated_at
            FROM ci_pull_analyses
            WHERE installation_id=ANY(%s) AND repository=%s
              AND (%s::timestamptz IS NULL OR (created_at,id)<(%s::timestamptz,%s::uuid))
            ORDER BY created_at DESC,id DESC LIMIT %s""",
            (
                ids,
                full_name,
                after and after[0],
                after and after[0],
                after and after[1],
                limit + 1,
            ),
        ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "repository": {
            "full_name": full_name,
            "private": any(h["private"] for h in homes),
            "installation_id": ids[0],
            "account_login": homes[0]["account_login"],
        },
        "pulls": [_pull_row(r) for r in rows],
        "next_cursor": _encode_cursor(rows[-1]["created_at"], rows[-1]["id"])
        if more
        else None,
    }


@app.get("/app/pulls/{analysis_id}", dependencies=[Depends(authenticated)])
def app_pull(analysis_id: UUID, installation: int | None = Query(default=None, ge=1)):
    with store.connection() as conn:
        row = conn.execute(
            """SELECT a.id,a.installation_id,a.repository,a.number,a.title,a.head_sha,a.base_sha,
              a.status,a.verdict,a.verdicts,a.diff,a.error,a.created_at,a.updated_at,
              i.account_login,coalesce(r.private,true) AS private
            FROM ci_pull_analyses a
            JOIN ci_installations i ON i.id=a.installation_id AND i.deleted_at IS NULL
            LEFT JOIN ci_installation_repositories r
              ON r.installation_id=a.installation_id AND r.full_name=a.repository
            WHERE a.id=%s AND (%s::bigint IS NULL OR a.installation_id=%s)""",
            (analysis_id, installation, installation),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Analysis not found")
    return {
        **_pull_row(row),
        "base_sha": row["base_sha"],
        "account_login": row["account_login"],
        "private": row["private"],
        "diff": row["diff"],
        "verdicts": row["verdicts"] if isinstance(row["verdicts"], list) else [],
    }


def _scan_row(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "installation_id": row["installation_id"],
        "repository": row["repository"],
        "status": row["status"],
        "ref": row["ref"],
        "head_sha": row["head_sha"],
        "error": row["error"],
        "scanned_at": row["scanned_at"],
        "updated_at": row["updated_at"],
        "items": row["items"] if isinstance(row.get("items"), list) else [],
    }


@app.get(
    "/app/repositories/{owner}/{name}/upcoming", dependencies=[Depends(authenticated)]
)
def app_repository_upcoming(
    owner: str = Path(pattern=GITHUB_NAME, max_length=100),
    name: str = Path(pattern=GITHUB_NAME, max_length=100),
    installations: list[int] | None = Query(default=None),
):
    """The latest upcoming-breakage scan: every direct dependency against its latest release."""
    scope = _installation_scope(installations)
    with store.connection() as conn:
        homes = _homes(conn, owner, name, None, scope)
        row = conn.execute(
            """SELECT * FROM ci_repository_scans WHERE installation_id=ANY(%s) AND repository=%s
            ORDER BY scanned_at DESC NULLS LAST,updated_at DESC LIMIT 1""",
            ([h["installation_id"] for h in homes], homes[0]["full_name"]),
        ).fetchone()
    return {"repository": homes[0]["full_name"], "scan": _scan_row(row)}


@app.post(
    "/app/repositories/{owner}/{name}/scan",
    status_code=202,
    dependencies=[Depends(authenticated)],
)
def app_repository_scan(
    owner: str = Path(pattern=GITHUB_NAME, max_length=100),
    name: str = Path(pattern=GITHUB_NAME, max_length=100),
    installations: list[int] | None = Query(default=None),
):
    from codeintent import scans

    scope = _installation_scope(installations)
    with store.connection() as conn:
        home = _homes(conn, owner, name, None, scope)[0]
        queued = scans.defer(conn, home["installation_id"], home["full_name"])
    return {"status": "queued" if queued else "already-queued"}


@app.get("/app/upcoming", dependencies=[Depends(authenticated)])
def app_upcoming(installations: list[int] | None = Query(default=None)):
    """Across watched repositories: dependencies whose latest release breaks or needs a change, and
    known advisories on the versions in use now. Worst first."""
    scope = _installation_scope(installations)
    with store.connection() as conn:
        rows = conn.execute(
            """SELECT s.installation_id,s.repository,s.status,s.scanned_at,s.items
            FROM ci_repository_scans s
            JOIN ci_installations i ON i.id=s.installation_id AND i.deleted_at IS NULL
            JOIN ci_installation_repositories r ON r.installation_id=s.installation_id AND r.full_name=s.repository
            WHERE (%s::bigint[] IS NULL OR s.installation_id=ANY(%s::bigint[]))""",
            (scope, scope),
        ).fetchall()
    findings, totals = [], {"repositories": 0, "scanned": 0, "pending": 0}
    for row in rows:
        totals["repositories"] += 1
        if row["status"] in ("queued", "running"):
            totals["pending"] += 1
        if row["scanned_at"]:
            totals["scanned"] += 1
        for item in row["items"] or []:
            if not isinstance(item, dict):
                continue
            verdict = item.get("verdict") or {}
            check = item.get("advisories") or {}
            active = [
                a.get("id")
                for a in check.get("advisories") or []
                if isinstance(a, dict) and not a.get("withdrawn")
            ]
            liftable = item.get("lift") == "can-be-lifted"
            if (
                verdict.get("verdict") not in ("breaks", "needs-change")
                and not active
                and not liftable
            ):
                continue
            findings.append(
                {
                    "repository": row["repository"],
                    "project": item.get("project") or ".",
                    "package": item.get("package"),
                    "specifier": item.get("specifier") or "",
                    "lift": item.get("lift"),
                    "current": item.get("current"),
                    "latest": item.get("latest"),
                    "verdict": verdict.get("verdict"),
                    "label": verdict.get("label"),
                    "reason": verdict.get("reason"),
                    "places": sum(
                        len(f.get("locations") or [])
                        for f in verdict.get("findings") or []
                        if isinstance(f, dict)
                    ),
                    "advisories": active,
                    "scanned_at": row["scanned_at"],
                }
            )
    rank = {"breaks": 0, "needs-change": 1}
    findings.sort(
        key=lambda f: (
            rank.get(f["verdict"], 2),
            f["lift"] != "can-be-lifted",
            -len(f["advisories"]),
            f["repository"].lower(),
            str(f["package"]),
        )
    )
    return {"totals": totals, "findings": findings[:200]}


# --- Telegram bot -------------------------------------------------------------------------------


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    background: BackgroundTasks,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    """Bot API webhook: check the secret_token header, acknowledge at once, reply in the background."""
    import json

    from codeintent import telegram

    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not secret or not os.getenv("TELEGRAM_BOT_TOKEN"):
        raise HTTPException(503, "Telegram is not configured")
    if not hmac.compare_digest(
        x_telegram_bot_api_secret_token.encode(), secret.encode()
    ):
        raise HTTPException(401, "Invalid Telegram secret token")
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(413, "Update is too large")
    try:
        update = json.loads(body)
    except ValueError:
        raise HTTPException(400, "Update must be JSON") from None
    if isinstance(update, dict):
        # Replies run after the response is sent, so Telegram never waits on the database or sendMessage.
        background.add_task(telegram.handle_update, update)
    return {"ok": True}


def _live_installation(installation_id: int) -> None:
    with store.connection() as conn:
        if (
            installation_id < 1
            or not conn.execute(
                "SELECT 1 FROM ci_installations WHERE id=%s AND deleted_at IS NULL",
                (installation_id,),
            ).fetchone()
        ):
            raise HTTPException(404, "Installation not found")


@app.post(
    "/app/installations/{installation_id}/telegram-code",
    dependencies=[Depends(authenticated)],
)
def app_telegram_code(installation_id: int):
    from codeintent import telegram

    _live_installation(installation_id)
    if not telegram.configured():
        raise HTTPException(503, "Telegram is not configured")
    try:
        created = telegram.new_link_code(installation_id)
    except LookupError:
        raise HTTPException(404, "Installation not found") from None
    bot = telegram.bot_username()
    return {
        "code": created["code"],
        "expires_at": created["expires_at"],
        "deep_link": f"https://t.me/{bot}?start={created['code']}",
        "group_link": f"https://t.me/{bot}?startgroup={created['code']}",
        "bot_username": bot,
    }


@app.get(
    "/app/installations/{installation_id}/telegram",
    dependencies=[Depends(authenticated)],
)
def app_telegram_chats(installation_id: int):
    from codeintent import telegram

    _live_installation(installation_id)
    return {
        "configured": telegram.configured(),
        "bot_username": telegram.bot_username() or None,
        "chats": telegram.linked_chats(installation_id),
    }


RUN_COLUMNS = """id,installation_id,kind,repository,ref,subject,status,failed_step,error,attempt,final,
  analysis_id,summary,started_at,finished_at,
  (extract(epoch FROM coalesce(finished_at,now())-started_at)*1000)::bigint AS duration_ms"""


def _run_row(row: dict) -> dict:
    return {
        **row,
        "id": str(row["id"]),
        "analysis_id": row["analysis_id"] and str(row["analysis_id"]),
    }


@app.get("/app/runs", dependencies=[Depends(authenticated)])
def app_runs(
    installations: list[int] | None = Query(default=None),
    kind: Literal["pull", "scan", "mcp"] | None = None,
    problems: bool = False,
    repository: str | None = Query(default=None, max_length=201),
    limit: int = Query(default=30, ge=1, le=100),
):
    """Recent runs, newest first; ``problems`` keeps failed and partial ones (final attempts only)."""
    scope = _installation_scope(installations)
    with store.connection() as conn:
        rows = conn.execute(
            f"""SELECT {RUN_COLUMNS} FROM ci_runs
            WHERE (%s::bigint[] IS NULL OR installation_id=ANY(%s::bigint[]))
              AND (%s::text IS NULL OR kind=%s)
              AND (%s::text IS NULL OR lower(repository)=lower(%s))
              AND (NOT %s OR (status IN ('failed','partial') AND (final OR status='partial')))
            ORDER BY started_at DESC LIMIT %s""",
            (scope, scope, kind, kind, repository, repository, problems, limit),
        ).fetchall()
    return {"runs": [_run_row(r) for r in rows]}


@app.get("/app/runs/{run_id}", dependencies=[Depends(authenticated)])
def app_run(run_id: UUID, installations: list[int] | None = Query(default=None)):
    """One run with its steps, its full result, and the other attempts of the same work."""
    scope = _installation_scope(installations)
    with store.connection() as conn:
        row = conn.execute(
            f"""SELECT {RUN_COLUMNS},input,result FROM ci_runs WHERE id=%s
              AND (%s::bigint[] IS NULL OR installation_id=ANY(%s::bigint[]))""",
            (run_id, scope, scope),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Run not found")
        steps = conn.execute(
            "SELECT seq,name,status,started_at,duration_ms,detail FROM ci_run_steps WHERE run_id=%s ORDER BY seq",
            (run_id,),
        ).fetchall()
        attempts = (
            conn.execute(
                f"SELECT {RUN_COLUMNS} FROM ci_runs WHERE analysis_id=%s ORDER BY started_at",
                (row["analysis_id"],),
            ).fetchall()
            if row["analysis_id"]
            else []
        )
        found = conn.execute(
            """SELECT repository,source,pull_number,key,severity,package,start_version,end_version,change,
              decision,places,status,first_seen,last_seen,resolved_at
            FROM ci_breaks WHERE first_run=%s OR last_run=%s ORDER BY severity,package""",
            (run_id, run_id),
        ).fetchall()
    return {
        **_run_row(row),
        "input": row["input"],
        "result": row["result"],
        "steps": steps,
        "attempts": [_run_row(a) for a in attempts],
        "breaks": found,
    }


@app.get("/app/breaks", dependencies=[Depends(authenticated)])
def app_breaks(
    installations: list[int] | None = Query(default=None),
    status: Literal["open", "resolved", "all"] = "open",
    limit: int = Query(default=200, ge=1, le=500),
):
    """Every recorded break: open ones by default, worst and newest first."""
    scope = _installation_scope(installations)
    with store.connection() as conn:
        rows = conn.execute(
            """SELECT b.installation_id,b.repository,b.source,b.pull_number,b.key,b.severity,b.package,
              b.start_version,b.end_version,b.change,b.decision,b.places,b.status,b.analysis_id,
              b.first_run,b.last_run,b.first_seen,b.last_seen,b.resolved_at,a.title AS pull_title
            FROM ci_breaks b
            JOIN ci_installation_repositories r ON r.installation_id=b.installation_id AND r.full_name=b.repository
            LEFT JOIN ci_pull_analyses a ON a.id=b.analysis_id
            WHERE (%s::bigint[] IS NULL OR b.installation_id=ANY(%s::bigint[]))
              AND (%s='all' OR (%s='open' AND b.status='open') OR (%s='resolved' AND b.status<>'open'))
            ORDER BY b.status<>'open',b.severity<>'breaks',b.last_seen DESC LIMIT %s""",
            (scope, scope, status, status, status, limit),
        ).fetchall()
    return {
        "breaks": [
            {
                **r,
                "analysis_id": r["analysis_id"] and str(r["analysis_id"]),
                "first_run": r["first_run"] and str(r["first_run"]),
                "last_run": r["last_run"] and str(r["last_run"]),
            }
            for r in rows
        ]
    }


@app.get("/app/ops", dependencies=[Depends(operator)])
def app_ops():
    """Operator view of the deployment: queue, worker, webhooks, verdicts, scans, Telegram, MCP."""
    from codeintent import ops

    with store.connection() as conn:
        return ops.snapshot(conn)


# --- MCP tokens for AI agents --------------------------------------------------------------------


@app.get(
    "/app/installations/{installation_id}/mcp-tokens",
    dependencies=[Depends(authenticated)],
)
def app_mcp_tokens(installation_id: int):
    from codeintent import mcp_tokens

    _live_installation(installation_id)
    return {"tokens": mcp_tokens.listing(installation_id)}


@app.post(
    "/app/installations/{installation_id}/mcp-tokens",
    status_code=201,
    dependencies=[Depends(authenticated)],
)
def app_mcp_token_create(installation_id: int):
    """A new token, returned once. Only its SHA-256 digest is kept."""
    from codeintent import mcp_tokens

    _live_installation(installation_id)
    try:
        return mcp_tokens.issue(installation_id)
    except LookupError:
        raise HTTPException(404, "Installation not found") from None
    except OverflowError:
        raise HTTPException(
            409, f"At most {mcp_tokens.MAX_ACTIVE} active tokens; revoke one first"
        ) from None


@app.delete(
    "/app/installations/{installation_id}/mcp-tokens/{token_id}",
    status_code=204,
    dependencies=[Depends(authenticated)],
)
def app_mcp_token_revoke(installation_id: int, token_id: UUID):
    from codeintent import mcp_tokens

    _live_installation(installation_id)
    if not mcp_tokens.revoke(installation_id, str(token_id)):
        raise HTTPException(404, "Token not found")


@app.exception_handler(store.QuotaExceeded)
async def quota_handler(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=429, content={"detail": "The daily import limit has been reached"}
    )
