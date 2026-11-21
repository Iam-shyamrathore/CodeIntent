"""Breaks ledger: each change found to break (or need a change in) a repository, and what became of it.

A pull request's breaks stay with that pull request: fixed when a later push no longer has them, merged or
closed with it. A scan's breaks belong to the default branch: fixed when a later scan no longer finds them.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

from psycopg.types.json import Jsonb

MAX_PLACES = 50
MAX_CODE = 600


MAX_LINES = 8


def _depth(text: str) -> int:
    """Open minus closed brackets on one line, ignoring brackets inside simple string literals."""
    text = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "", text.split("#", 1)[0])
    return sum(text.count(c) for c in "([{") - sum(text.count(c) for c in ")]}")


def code_at(root: Path | None, file: str, line: int | None) -> str | None:
    """The statement starting at ``file:line`` under ``root``: that line, plus the following ones while
    brackets stay open (at most ``MAX_LINES``), dedented and clipped. None if unreadable."""
    if root is None or not line:
        return None
    path = (root / file).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return None
    taken, depth = [], 0
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for number, text in enumerate(handle, 1):
                if number < line:
                    continue
                taken.append(text.rstrip("\n"))
                depth += _depth(text)
                if depth <= 0 or len(taken) >= MAX_LINES:
                    break
    except OSError:
        return None
    if not taken:
        return None
    code = textwrap.dedent("\n".join(taken)).strip()
    return code if len(code) <= MAX_CODE else code[: MAX_CODE - 1] + "…"


def key(verdict: dict, change: dict) -> str:
    return (
        f"{verdict['package']}@{verdict['end']}:{change.get('kind')}:"
        f"{change.get('symbol')}:{change.get('parameter') or ''}"
    )


def _decision(verdict: dict, change: dict, index: int) -> dict | None:
    decisions = [d for d in verdict.get("decisions") or [] if isinstance(d, dict)]
    wanted = (change.get("symbol"), change.get("parameter"), change.get("kind"))
    for decision in decisions:
        k = decision.get("change_key") or {}
        if (k.get("symbol"), k.get("parameter"), k.get("kind")) == wanted:
            return decision
    return decisions[index] if index < len(decisions) else None


def rows(verdicts: list[dict], root: Path | None) -> list[dict]:
    """One row per finding across ``verdicts`` (``UpgradeVerdict`` dicts), with the code at each place."""
    found = []
    for verdict in verdicts:
        for index, finding in enumerate(verdict.get("findings") or []):
            change = finding.get("change") or {}
            decision = _decision(verdict, change, index)
            found.append(
                {
                    "key": key(verdict, change),
                    "severity": finding.get("severity") or "needs-change",
                    "package": verdict["package"],
                    "start_version": verdict["start"],
                    "end_version": verdict["end"],
                    "change": change | {"guarded": bool(finding.get("guarded"))},
                    "decision": decision,
                    "places": [
                        {
                            "file": loc.get("file"),
                            "line": loc.get("line"),
                            "code": code_at(
                                root, loc.get("file") or "", loc.get("line")
                            ),
                        }
                        for loc in (finding.get("locations") or [])[:MAX_PLACES]
                    ],
                }
            )
    return found


def record(
    conn,
    *,
    installation_id: int,
    repository: str,
    source: str,
    verdicts: list[dict],
    root: Path | None,
    run_id: str,
    pull_number: int = 0,
    analysis_id: str | None = None,
) -> dict:
    """Upsert this run's breaks and resolve the ones it no longer finds. Returns counts."""
    found = rows(verdicts, root)
    for row in found:
        conn.execute(
            """INSERT INTO ci_breaks(installation_id,repository,source,pull_number,key,severity,package,
              start_version,end_version,change,decision,places,analysis_id,first_run,last_run)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(installation_id,repository,source,pull_number,key) DO UPDATE SET
              severity=EXCLUDED.severity,start_version=EXCLUDED.start_version,change=EXCLUDED.change,
              decision=EXCLUDED.decision,places=EXCLUDED.places,analysis_id=EXCLUDED.analysis_id,
              last_run=EXCLUDED.last_run,last_seen=now(),status='open',resolved_at=NULL""",
            (
                installation_id,
                repository,
                source,
                pull_number,
                row["key"],
                row["severity"],
                row["package"],
                row["start_version"],
                row["end_version"],
                Jsonb(row["change"]),
                Jsonb(row["decision"]) if row["decision"] else None,
                Jsonb(row["places"]),
                analysis_id,
                run_id,
                run_id,
            ),
        )
    resolved = conn.execute(
        """UPDATE ci_breaks SET status='fixed',resolved_at=now(),last_run=%s
        WHERE installation_id=%s AND repository=%s AND source=%s AND pull_number=%s
          AND status='open' AND NOT (key = ANY(%s)) RETURNING key""",
        (
            run_id,
            installation_id,
            repository,
            source,
            pull_number,
            [r["key"] for r in found],
        ),
    ).fetchall()
    return {"found": len(found), "fixed": len(resolved)}


def pull_closed(
    conn, installation_id: int, repository: str, number: int, merged: bool
) -> int:
    """A pull request was merged or closed: its open breaks go with it. Returns how many."""
    return len(
        conn.execute(
            """UPDATE ci_breaks SET status=%s,resolved_at=now()
            WHERE installation_id=%s AND repository=%s AND source='pull' AND pull_number=%s AND status='open'
            RETURNING key""",
            ("merged" if merged else "closed", installation_id, repository, number),
        ).fetchall()
    )
