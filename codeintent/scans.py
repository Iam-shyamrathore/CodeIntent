"""Upcoming-breakage scans of watched repositories: queueing, the scan itself and what alerts.

A scan reads the default branch, compares every direct dependency's locked version with its latest
release (``codeintent.upgrades.upcoming``) and stores the result per repository. Nothing in the
repository or its dependencies is installed, imported or run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import procrastinate
from psycopg.types.json import Jsonb

from codeintent import store

logger = logging.getLogger(__name__)
FRESH = timedelta(hours=20)
"""A repository whose default branch has not moved is not rescanned more often than this."""
MAX_TREE_ENTRIES = 100_000


def defer(conn, installation_id: int, repository: str) -> bool:
    """Queue a scan in the caller's transaction. Returns False when one is already queued."""
    from codeintent.tasks import scan_repository

    conn.execute(
        """INSERT INTO ci_repository_scans(installation_id,repository,status) VALUES (%s,%s,'queued')
        ON CONFLICT(installation_id,repository) DO UPDATE SET
          status=CASE WHEN ci_repository_scans.status='running' THEN 'running' ELSE 'queued' END,
          updated_at=now()""",
        (installation_id, repository),
    )
    try:
        # A savepoint, so a duplicate leaves the caller's transaction usable.
        with conn.transaction():
            scan_repository.configure(
                connection=conn,
                queueing_lock=f"scan:{installation_id}:{repository}",
                priority=-10,
            ).defer(installation_id=installation_id, repository=repository)
    except procrastinate.exceptions.AlreadyEnqueued:
        return False
    return True


def defer_all(conn) -> int:
    """Queue a scan for every repository of every live, unsuspended installation."""
    rows = conn.execute(
        """SELECT r.installation_id,r.full_name FROM ci_installation_repositories r
        JOIN ci_installations i ON i.id=r.installation_id AND i.deleted_at IS NULL AND NOT i.suspended
        ORDER BY r.installation_id,r.full_name"""
    ).fetchall()
    return sum(defer(conn, r["installation_id"], r["full_name"]) for r in rows)


def has_python_manifests(paths: list[str]) -> bool:
    from codeintent.github_app import manifest_root

    return any(
        manifest_root(p) is not None
        for p in paths
        if not any(part.startswith(".") for part in p.split("/"))
    )


def _finish(installation_id: int, repository: str, **fields) -> None:
    columns = ",".join(f"{name}=%s" for name in fields)
    with store.connection() as conn:
        conn.execute(
            f"UPDATE ci_repository_scans SET {columns},updated_at=now() WHERE installation_id=%s AND repository=%s",
            (*fields.values(), installation_id, repository),
        )


def run(installation_id: int, repository: str, client, pypi) -> str:
    """Scan one repository and store the result. Returns the final status.

    ``client`` is a ``github_app.Client`` for the installation; ``pypi`` an ``httpx.Client``.
    """
    from codeintent.upgrades import repository as source
    from codeintent.upgrades import upcoming

    with store.connection() as conn:
        watched = conn.execute(
            """SELECT 1 FROM ci_installation_repositories r
            JOIN ci_installations i ON i.id=r.installation_id AND i.deleted_at IS NULL AND NOT i.suspended
            WHERE r.installation_id=%s AND r.full_name=%s""",
            (installation_id, repository),
        ).fetchone()
        if not watched:
            conn.execute(
                "DELETE FROM ci_repository_scans WHERE installation_id=%s AND repository=%s",
                (installation_id, repository),
            )
            return "removed"
        previous = conn.execute(
            """SELECT status,head_sha,scanned_at FROM ci_repository_scans
            WHERE installation_id=%s AND repository=%s FOR UPDATE""",
            (installation_id, repository),
        ).fetchone()
        conn.execute(
            """INSERT INTO ci_repository_scans(installation_id,repository,status) VALUES (%s,%s,'running')
            ON CONFLICT(installation_id,repository) DO UPDATE SET status='running',error=NULL,updated_at=now()""",
            (installation_id, repository),
        )
    meta = client.json(f"/repos/{repository}")
    branch = meta.get("default_branch")
    if meta.get("archived") or not branch:
        _finish(
            installation_id, repository, status="skipped", error="archived-or-empty"
        )
        return "skipped"
    sha = client.json(f"/repos/{repository}/branches/{branch}")["commit"]["sha"]
    if (
        previous
        and previous["status"] in ("done", "skipped")
        and previous["head_sha"] == sha
        and previous["scanned_at"]
        and datetime.now(UTC) - previous["scanned_at"] < FRESH
    ):
        _finish(installation_id, repository, status=previous["status"])
        return previous["status"]
    tree = client.json(
        f"/repos/{repository}/git/trees/{sha}", params={"recursive": "1"}
    )
    paths = [
        e["path"]
        for e in (tree.get("tree") or [])[:MAX_TREE_ENTRIES]
        if e.get("type") == "blob"
    ]
    if not has_python_manifests(paths):
        _finish(
            installation_id,
            repository,
            status="skipped",
            error="no-python-manifests",
            ref=branch,
            head_sha=sha,
            items=None,
            scanned_at=datetime.now(UTC),
        )
        return "skipped"
    with source.temporary() as folder:
        root = source.download(repository, sha, Path(folder), client.token())
        items = upcoming.scan(root, pypi, explain=True)
    _finish(
        installation_id,
        repository,
        status="done",
        ref=branch,
        head_sha=sha,
        items=Jsonb([i.model_dump(mode="json") for i in items]),
        scanned_at=datetime.now(UTC),
    )
    return "done"


def fail(installation_id: int, repository: str, error: str) -> None:
    _finish(installation_id, repository, status="failed", error=error)


# --- What alerts -------------------------------------------------------------------------------


def alert_keys(item: dict) -> list[tuple[str, str]]:
    """``(key, kind)`` for each part of an upcoming item worth an alert: a breaking next release, or an
    active advisory on the version in use now. Keys name the versions, so a newer release alerts again.
    """
    keys = []
    verdict = item.get("verdict") or {}
    if verdict.get("verdict") == "breaks" and item.get("latest"):
        keys.append((f"breaks:{item['package']}@{item['latest']}", "breaks"))
    check = item.get("advisories") or {}
    if check.get("status") == "advisories":
        for advisory in check.get("advisories") or []:
            if isinstance(advisory, dict) and not advisory.get("withdrawn"):
                keys.append(
                    (
                        f"advisory:{item['package']}@{item.get('current')}:{advisory.get('id')}",
                        "advisory",
                    )
                )
    return keys
