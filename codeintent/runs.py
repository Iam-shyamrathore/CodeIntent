"""Runs: one recorded attempt at a pull request check, repository scan or MCP call, with timed steps.

    with runs.recorded("scan", installation_id=1, repository="acme/app", subject="main") as run:
        with run.step("download"):
            ...
        run.finish(summary={...}, result={...})

A step that raises is recorded as failed with only its exception's class name (exception text may echo
upstream responses), the run is marked failed at that step, and the exception propagates.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from codeintent import store

logger = logging.getLogger(__name__)
MAX_DETAIL = 500


def category(exc: BaseException) -> str:
    """What is safe to store about a failure: an explicit category, else the exception's class name."""
    if explicit := getattr(exc, "category", None):
        return str(explicit)
    return type(exc).__name__


class Run:
    def __init__(self, ident: str, kind: str):
        self.id = ident
        self.kind = kind
        self.seq = 0
        self.finished = False
        self.failed_step: str | None = None

    def _record(self, name: str, status: str, started: datetime, ms: int, detail):
        self.seq += 1
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO ci_run_steps(run_id,seq,name,status,started_at,duration_ms,detail)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    self.id,
                    self.seq,
                    name,
                    status,
                    started,
                    ms,
                    (detail or None) and str(detail)[:MAX_DETAIL],
                ),
            )

    @contextmanager
    def step(self, name: str, detail: str | None = None) -> Iterator[dict]:
        """Time one step. Assign ``note["detail"]`` inside the block to record what it found."""
        started, clock, note = datetime.now(UTC), time.monotonic(), {"detail": detail}
        try:
            yield note
        except BaseException as exc:
            self.failed_step = self.failed_step or name
            self._record(
                name,
                "failed",
                started,
                int((time.monotonic() - clock) * 1000),
                category(exc),
            )
            raise
        self._record(
            name, "ok", started, int((time.monotonic() - clock) * 1000), note["detail"]
        )

    def skip(self, name: str, detail: str) -> None:
        self._record(name, "skipped", datetime.now(UTC), 0, detail)

    def finish(
        self,
        status: str = "succeeded",
        *,
        summary: dict | None = None,
        result=None,
        error: str | None = None,
        final: bool | None = None,
    ) -> None:
        with store.connection() as conn:
            conn.execute(
                """UPDATE ci_runs SET status=%s,summary=coalesce(%s,summary),result=coalesce(%s,result),
                error=%s,failed_step=%s,final=coalesce(%s,final),finished_at=now() WHERE id=%s""",
                (
                    status,
                    Jsonb(summary) if summary is not None else None,
                    Jsonb(result) if result is not None else None,
                    error,
                    self.failed_step if status in ("failed", "partial") else None,
                    final,
                    self.id,
                ),
            )
        self.finished = True


@contextmanager
def recorded(
    kind: str,
    *,
    installation_id: int | None,
    repository: str | None,
    subject: str,
    ref: str | None = None,
    analysis_id: str | None = None,
    token_id: str | None = None,
    input: dict | None = None,
    attempt: int = 1,
    final: bool = True,
) -> Iterator[Run]:
    """Record a run around the block; an exception marks it failed and propagates."""
    ident = str(uuid.uuid4())
    with store.connection() as conn:
        conn.execute(
            """INSERT INTO ci_runs(id,installation_id,kind,repository,ref,subject,analysis_id,token_id,input,attempt,final)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                ident,
                installation_id,
                kind,
                repository,
                ref,
                subject[:300],
                analysis_id,
                token_id,
                Jsonb(input) if input is not None else None,
                attempt,
                final,
            ),
        )
    run = Run(ident, kind)
    try:
        yield run
    except BaseException as exc:
        if not run.finished:
            try:
                run.finish("failed", error=category(exc))
            except Exception:
                logger.warning("Could not record the failure of run %s", ident)
        queue_projection(ident)
        raise
    if not run.finished:
        run.finish()
    queue_projection(ident)


def queue_projection(run_id: str) -> None:
    """Copy the run into the workspace graph: at once in worker processes (checks, scans, agents), where
    jobs queued from inside a running job were being lost; as a queued job from the API (MCP calls), so an
    agent's answer never waits on Neo4j. The periodic catch-up covers anything that slips through."""
    import os

    if os.getenv("CODEINTENT_PROCESS") == "worker":
        try:
            from codeintent import workspace_graph

            if workspace_graph.configured():
                workspace_graph.project(run_id)
            return
        except Exception as exc:
            logger.warning("Could not project run %s (%s)", run_id, type(exc).__name__)
            return
    try:
        from codeintent.tasks import project_run

        with store.connection() as conn:
            project_run.configure(connection=conn).defer(run_id=run_id)
    except Exception as exc:
        # The periodic catch-up projects it later; a run never fails because of the graph.
        logger.warning("Could not queue the graph projection (%s)", type(exc).__name__)


MAX_USAGES = 2000


def usage_rows(verdict) -> list[dict]:
    """Every use of an ``UpgradeVerdict``'s package, compact, for the run's result and the graph."""
    return [
        {
            "symbol": u.symbol,
            "kind": u.kind,
            "keywords": list(u.keywords),
            "file": u.location.file,
            "line": u.location.line,
        }
        for u in verdict.usages[:MAX_USAGES]
    ]
