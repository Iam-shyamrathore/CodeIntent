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

from codeintent import runs, store

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
                # One scan at a time across the worker: each loads many library releases.
                lock="repository-scans",
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


MAX_PROJECTS = 8
SKIPPED_FOLDERS = {"node_modules", "site-packages", "vendor", "third_party", "fixtures"}


def projects(paths: list[str]) -> list[str]:
    """Folders holding a Python project's manifests, shallowest first, at most ``MAX_PROJECTS``.

    Hidden and vendored folders are left out; ``"."`` is the repository root.
    """
    from codeintent.github_app import manifest_root

    roots = {
        root
        for p in paths
        if not any(
            part.startswith(".") or part in SKIPPED_FOLDERS
            for part in p.split("/")[:-1]
        )
        and (root := manifest_root(p)) is not None
    }
    return sorted(roots, key=lambda r: (r != ".", r.count("/"), r))[:MAX_PROJECTS]


def has_python_manifests(paths: list[str]) -> bool:
    return bool(projects(paths))


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
    with runs.recorded(
        "scan",
        installation_id=installation_id,
        repository=repository,
        subject="default branch",
    ) as run:
        return _scan(installation_id, repository, client, pypi, previous, run)


def _scan(installation_id: int, repository: str, client, pypi, previous, run) -> str:
    from codeintent import breaks
    from codeintent.upgrades import repository as source
    from codeintent.upgrades import upcoming

    with run.step("read the repository") as note:
        response = client.get(f"/repos/{repository}")
        if response.status_code == 404:
            # No longer readable by this installation (deselected, deleted or made private elsewhere):
            # re-read the installation's list from GitHub rather than trusting a missed webhook.
            from codeintent.github_app import accessible_repositories, reconcile

            with store.connection() as conn:
                changed = reconcile(
                    conn, installation_id, accessible_repositories(client)
                )
            fail(installation_id, repository, "not-found")
            note["detail"] = (
                f"not readable by the App any more; {len(changed['removed'])} repositories dropped"
            )
            run.finish(
                "skipped",
                summary={"reason": "the App can no longer read this repository"},
            )
            return "removed"
        response.raise_for_status()
        meta = response.json()
        branch = meta.get("default_branch")
        note["detail"] = f"default branch {branch}"
    if meta.get("archived") or not branch:
        _finish(
            installation_id, repository, status="skipped", error="archived-or-empty"
        )
        run.finish("skipped", summary={"reason": "archived or empty"})
        return "skipped"
    with run.step("read the latest commit") as note:
        sha = client.json(f"/repos/{repository}/branches/{branch}")["commit"]["sha"]
        note["detail"] = sha[:12]
    with store.connection() as conn:
        conn.execute("UPDATE ci_runs SET ref=%s WHERE id=%s", (sha, run.id))
    if (
        previous
        and previous["status"] in ("done", "skipped")
        and previous["head_sha"] == sha
        and previous["scanned_at"]
        and datetime.now(UTC) - previous["scanned_at"] < FRESH
    ):
        _finish(installation_id, repository, status=previous["status"])
        run.finish("skipped", summary={"reason": "unchanged since the last scan"})
        return previous["status"]
    with run.step("find Python projects") as note:
        tree = client.json(
            f"/repos/{repository}/git/trees/{sha}", params={"recursive": "1"}
        )
        paths = [
            e["path"]
            for e in (tree.get("tree") or [])[:MAX_TREE_ENTRIES]
            if e.get("type") == "blob"
        ]
        found = projects(paths)
        note["detail"] = ", ".join(found) or "none"
    if not found:
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
        run.finish("skipped", summary={"reason": "no Python manifest or lock file"})
        return "skipped"
    with source.temporary() as folder:
        with run.step("download the repository"):
            root = source.download(repository, sha, Path(folder), client.token())
        items = []
        for project in found:
            with run.step(
                f"compare dependencies of {'the root project' if project == '.' else project}"
            ) as note:
                found_items = upcoming.scan(
                    root if project == "." else root / project,
                    pypi,
                    explain=True,
                    source=(repository, sha),
                    project=project,
                )
                compared = [i for i in found_items if i.verdict]
                note["detail"] = (
                    f"{len(found_items)} dependencies, {len(compared)} with a newer release, "
                    f"{sum(1 for i in compared if i.verdict.verdict == 'breaks')} breaking"
                )
            items += found_items
        dumped = [i.model_dump(mode="json") for i in items]
        with run.step("record breaks") as note, store.connection() as conn:
            counts = breaks.record(
                conn,
                installation_id=installation_id,
                repository=repository,
                source="scan",
                verdicts=[i["verdict"] for i in dumped if i.get("verdict")],
                root=root,
                run_id=run.id,
            )
            note["detail"] = (
                f"{counts['found']} found, {counts['fixed']} no longer found"
            )
    _finish(
        installation_id,
        repository,
        status="done",
        ref=branch,
        head_sha=sha,
        items=Jsonb(dumped),
        scanned_at=datetime.now(UTC),
    )
    verdicts = [i["verdict"]["verdict"] for i in dumped if i.get("verdict")]
    unreadable = [i["package"] for i in dumped if i.get("status") == "unreadable"]
    run.finish(
        "partial" if unreadable else "succeeded",
        summary={
            "branch": branch,
            "projects": found,
            "dependencies": len(dumped),
            "breaks": verdicts.count("breaks"),
            "needs_change": verdicts.count("needs-change"),
            "not_checked": verdicts.count("not-checked"),
            "liftable_pins": sum(1 for i in dumped if i.get("lift") == "can-be-lifted"),
            "unreadable": unreadable,
        },
        result={"items": dumped},
    )
    return "done"


class ScanError(Exception):
    """A scan failed; ``args[0]`` is only the failure's category (its class name), safe to store."""


def run_installation(installation_id: int, repository: str) -> str:
    """``run`` with the installation's own GitHub client and token, for a child process."""
    import httpx

    from codeintent import github_app as gh
    from codeintent.upgrades import repository as source

    client = gh.Client.for_installation(installation_id)
    try:
        with (
            httpx.Client(timeout=60, follow_redirects=True) as pypi,
            source.using(client.token),
        ):
            return run(installation_id, repository, client, pypi)
    except Exception as exc:
        # Exception text may echo upstream responses, and not every exception survives pickling.
        raise ScanError(type(exc).__name__) from None
    finally:
        client.close()


def run_isolated(installation_id: int, repository: str) -> str:
    """``run_installation`` in a fresh process, so every library it loaded is freed when it ends.

    A scan reads dozens of releases; in a long-lived worker that memory stays allocated.
    """
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        return pool.submit(run_installation, installation_id, repository).result()


def fail(installation_id: int, repository: str, error: str) -> None:
    _finish(installation_id, repository, status="failed", error=error)


# --- What alerts -------------------------------------------------------------------------------


def alert_keys(item: dict) -> list[tuple[str, str]]:
    """``(key, kind)`` for each part of an upcoming item worth an alert: a breaking next release, a pin the
    latest release no longer needs, or an active advisory on the version in use now. Keys name the versions,
    so a newer release alerts again.
    """
    keys = []
    verdict = item.get("verdict") or {}
    if verdict.get("verdict") == "breaks" and item.get("latest"):
        keys.append((f"breaks:{item['package']}@{item['latest']}", "breaks"))
    if item.get("lift") == "can-be-lifted" and item.get("latest"):
        keys.append((f"lift:{item['package']}@{item['latest']}", "lift"))
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
