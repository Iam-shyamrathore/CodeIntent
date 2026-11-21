"""Operations: what the deployment is doing now, and what an operator should be told about.

Everything here is read from the PostgreSQL ledger and Procrastinate's own tables; nothing is sampled.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)
STALLED = timedelta(minutes=5)
BACKLOG = timedelta(minutes=30)


def _counts(conn, query: str, params: tuple = ()) -> dict[str, int]:
    return {r["key"]: r["n"] for r in conn.execute(query, params).fetchall()}


def snapshot(conn) -> dict:
    """Queue, worker, webhook, verdict, scan, Telegram and MCP figures for the last 24 hours."""
    now = datetime.now(UTC)
    heartbeat = conn.execute(
        "SELECT max(last_heartbeat) AS at, count(*) FILTER (WHERE last_heartbeat > now()-interval '1 minute') AS live FROM procrastinate_workers"
    ).fetchone()
    oldest = conn.execute(
        "SELECT min(scheduled_at) AS at FROM procrastinate_jobs WHERE status='todo' AND (scheduled_at IS NULL OR scheduled_at <= now())"
    ).fetchone()["at"]
    return {
        "at": now,
        "worker": {
            "live": heartbeat["live"],
            "last_heartbeat": heartbeat["at"],
            "stalled": heartbeat["at"] is None or now - heartbeat["at"] > STALLED,
        },
        "queue": {
            "waiting": _counts(
                conn,
                "SELECT task_name AS key,count(*) AS n FROM procrastinate_jobs WHERE status='todo' GROUP BY 1",
            ),
            "running": _counts(
                conn,
                "SELECT task_name AS key,count(*) AS n FROM procrastinate_jobs WHERE status='doing' GROUP BY 1",
            ),
            "oldest_waiting": oldest,
            "failed_24h": failures(conn, now - timedelta(hours=24)),
        },
        "webhooks_24h": _counts(
            conn,
            "SELECT status AS key,count(*) AS n FROM ci_webhook_deliveries WHERE received_at > now()-interval '24 hours' GROUP BY 1",
        ),
        "analyses_24h": _counts(
            conn,
            "SELECT coalesce(verdict,status) AS key,count(*) AS n FROM ci_pull_analyses WHERE created_at > now()-interval '24 hours' GROUP BY 1",
        ),
        "scans": _counts(
            conn,
            "SELECT status AS key,count(*) AS n FROM ci_repository_scans GROUP BY 1",
        ),
        "telegram": {
            "chats": conn.execute(
                "SELECT count(*) AS n FROM ci_telegram_chats"
            ).fetchone()["n"],
            "alerts_24h": conn.execute(
                """SELECT (SELECT count(*) FROM ci_telegram_alerts WHERE sent_at > now()-interval '24 hours')
                  + (SELECT count(*) FROM ci_upcoming_alerts WHERE sent_at > now()-interval '24 hours') AS n"""
            ).fetchone()["n"],
        },
        "mcp": conn.execute(
            """SELECT count(*) FILTER (WHERE revoked_at IS NULL) AS active,
              count(*) FILTER (WHERE last_used_at > now()-interval '24 hours') AS used_24h FROM ci_mcp_tokens"""
        ).fetchone(),
    }


def failures(conn, since: datetime) -> dict[str, int]:
    """Jobs that failed for good (no retry left) since ``since``, by task."""
    return _counts(
        conn,
        """SELECT j.task_name AS key,count(DISTINCT j.id) AS n FROM procrastinate_events e
        JOIN procrastinate_jobs j ON j.id=e.job_id
        WHERE e.type='failed' AND e.at > %s AND j.status='failed' GROUP BY 1""",
        (since,),
    )


def problems(conn, since: datetime) -> list[str]:
    """Plain-text lines an operator should act on: final job failures since ``since``, and a backlog.

    This runs on the worker, so a stalled worker cannot report itself; ``snapshot`` shows that instead.
    The backlog line is reported in the first ten minutes of each hour only.
    """
    now = datetime.now(UTC)
    lines = [
        f"{n} {task} job{'s' if n != 1 else ''} failed with no retry left"
        for task, n in sorted(failures(conn, since).items())
    ]
    oldest = conn.execute(
        "SELECT min(scheduled_at) AS at FROM procrastinate_jobs WHERE status='todo' AND scheduled_at <= now()"
    ).fetchone()["at"]
    if oldest and now - oldest > BACKLOG and now.minute < 10:
        lines.append(
            f"The oldest waiting job has waited {int((now - oldest).total_seconds() // 60)} minutes"
        )
    return lines


def operator_chat() -> int | None:
    value = os.getenv("TELEGRAM_OPERATOR_CHAT_ID", "").strip()
    try:
        return int(value) if value else None
    except ValueError:
        logger.warning("TELEGRAM_OPERATOR_CHAT_ID is not a chat id")
        return None
