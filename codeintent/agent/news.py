"""Security news: an agent searches the web (Serper) for security reports about the packages a workspace
locks, often days before advisory databases list them.

The agent only searches and reads pages. A report counts only if it names a package it was asked about,
with the link of a page it actually read in that session. CodeIntent's own code then decides whether the
locked version falls in the reported range, whether OSV.dev already lists it, which repositories and files
use the package (from the workspace graph), and whether to alert Telegram.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from codeintent import runs, store
from codeintent.agent import harness
from codeintent.agent.tools import Session, search_configured, toolbox

logger = logging.getLogger(__name__)

MAX_PACKAGES = 24
BATCH = 6
IDS = re.compile(
    r"^(CVE-\d{4}-\d{4,}|GHSA(-[23456789cfghjmpqrvwx]{4}){3}|PYSEC-\d{4}-\d+)$", re.I
)


class Report(BaseModel):
    package: str
    title: str
    summary: str = Field(description="Two sentences at most, from the page.")
    ids: list[str] = Field(
        default=[], description="CVE, GHSA or PYSEC ids the page gives."
    )
    affected: str = Field(
        default="",
        description="PEP 440 specifier of affected versions, if the page states it.",
    )
    fixed_in: str = ""
    severity: Literal["critical", "high", "medium", "low", "unknown"] = "unknown"
    published: str = ""
    url: str = Field(
        description="The page this comes from; one you read with read_page."
    )


class Reports(BaseModel):
    items: list[Report]


def check(session: Session, asked: set[str]):
    def problems(answer: Reports) -> list[str]:
        out = []
        for r in answer.items:
            if canonicalize_name(r.package) not in asked:
                out.append(
                    f"{r.package} is not one of the packages you were asked about"
                )
            if r.url not in session.read_urls:
                out.append(
                    f"{r.url} was not read with read_page in this session; read it or drop the item"
                )
            for ident in r.ids:
                if not IDS.match(ident):
                    out.append(f"{ident} is not a CVE, GHSA or PYSEC id")
            if r.affected:
                try:
                    SpecifierSet(r.affected)
                except InvalidSpecifier:
                    out.append(
                        f"'{r.affected}' is not a PEP 440 specifier; leave it empty if unsure"
                    )
        return out

    return problems


def affects(spec: str, versions: set[str]) -> str:
    if not spec:
        return "maybe"
    try:
        allowed = SpecifierSet(spec)
        return (
            "yes"
            if any(allowed.contains(Version(v), prereleases=True) for v in versions)
            else "no"
        )
    except (InvalidSpecifier, InvalidVersion):
        return "maybe"


def key(report: dict) -> str:
    if report.get("ids"):
        return sorted(i.upper() for i in report["ids"])[0]
    return "url:" + hashlib.sha256(report["url"].encode()).hexdigest()[:16]


def locked(installation_id: int) -> dict[str, dict]:
    """Each direct dependency of the workspace: its locked versions, the repositories and OSV's ids."""
    with store.connection() as conn:
        rows = conn.execute(
            """SELECT s.repository,s.items FROM ci_repository_scans s
            JOIN ci_installation_repositories r ON r.installation_id=s.installation_id AND r.full_name=s.repository
            WHERE s.installation_id=%s AND s.status='done' AND s.items IS NOT NULL""",
            (installation_id,),
        ).fetchall()
    found: dict[str, dict] = {}
    for row in rows:
        for item in row["items"] or []:
            if not isinstance(item, dict) or not item.get("current"):
                continue
            entry = found.setdefault(
                canonicalize_name(item["package"]),
                {"versions": set(), "repositories": set(), "osv": set()},
            )
            entry["versions"].add(item["current"])
            entry["repositories"].add(row["repository"])
            for a in (item.get("advisories") or {}).get("advisories") or []:
                entry["osv"].update(
                    i.upper() for i in [a.get("id"), *(a.get("aliases") or [])] if i
                )
    return found


def scan(installation_id: int) -> dict:
    """Search the web for each locked package, store what is new and alert on what affects the workspace."""
    if not (harness.configured() and search_configured()):
        return {"skipped": "agents or web search are not configured"}
    packages = locked(installation_id)
    if not packages:
        return {"skipped": "no scanned dependencies"}
    chosen = sorted(packages, key=lambda p: (-len(packages[p]["repositories"]), p))[
        :MAX_PACKAGES
    ]
    stored, fresh, traces = 0, [], []
    with runs.recorded(
        "agent",
        installation_id=installation_id,
        repository=None,
        subject="security news",
    ) as run:
        for start in range(0, len(chosen), BATCH):
            batch = chosen[start : start + BATCH]
            listed = "\n".join(
                f"- {p} (locked: {', '.join(sorted(packages[p]['versions']))})"
                for p in batch
            )
            with run.step(f"search the web for {', '.join(batch)}") as note:
                session = Session()
                answer, trace = harness.run(
                    "news",
                    f"Packages:\n{listed}\n\nFind security reports about these packages.",
                    tools=toolbox(session, "web"),
                    answer=Reports,
                    role="news",
                    check=check(session, set(batch)),
                    budget=16,
                )
                traces.append(trace.as_dict())
                items = answer.items if answer else []
                note["detail"] = f"{len(items)} report(s) ({trace.outcome})"
            for report in items:
                data = report.model_dump()
                name = canonicalize_name(report.package)
                entry = packages[name]
                ids = {i.upper() for i in report.ids}
                with store.connection() as conn:
                    row = conn.execute(
                        """INSERT INTO ci_security_news(installation_id,package,key,item,affects,in_osv,repositories)
                        VALUES(%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(installation_id,package,key) DO UPDATE
                        SET item=EXCLUDED.item,affects=EXCLUDED.affects,in_osv=EXCLUDED.in_osv,
                            repositories=EXCLUDED.repositories,last_seen=now()
                        RETURNING (xmax = 0) AS inserted, affects, in_osv, key""",
                        (
                            installation_id,
                            name,
                            key(data),
                            Jsonb(data),
                            affects(report.affected, entry["versions"]),
                            bool(ids & entry["osv"]),
                            sorted(entry["repositories"]),
                        ),
                    ).fetchone()
                stored += 1
                if row["inserted"]:
                    fresh.append((name, row["key"]))
        alerts = _alert(installation_id)
        run.finish(
            summary={
                "packages": len(chosen),
                "reports": stored,
                "new": len(fresh),
                "alerts": alerts,
            },
            result={"agents": traces},
        )
    return {
        "packages": len(chosen),
        "reports": stored,
        "new": len(fresh),
        "alerts": alerts,
    }


def _files(installation_id: int, repository: str, package: str) -> list[str]:
    from codeintent import workspace_graph as wg
    from codeintent.graph import shared

    if not wg.configured():
        return []
    try:
        with shared() as db:
            return wg.reach(db, installation_id, repository, package)["files"][:3]
    except Exception:
        return []


def alert_text(row: dict) -> str:
    from codeintent import telegram as tg

    item = row["item"]
    versions = (
        "your locked version is in the reported range"
        if row["affects"] == "yes"
        else ("no affected range given; check your version")
    )
    where = []
    for repository in row["repositories"][:3]:
        files = _files(row["installation_id"], repository, row["package"])
        where.append(
            f"• {tg.esc(repository)}"
            + (
                f": {', '.join(f'<code>{tg.esc(f)}</code>' for f in files)}"
                if files
                else ""
            )
        )
    lines = [
        f"🛡 <b>Security report: {tg.esc(row['package'])}</b> (found on the web by CodeIntent's agent; "
        "not yet in OSV.dev)",
        f"<b>{tg.esc(item['title'], 200)}</b>",
        tg.esc(item.get("summary"), 400),
        f"Severity: {tg.esc(item.get('severity'))} · {versions}"
        + (f" · fixed in {tg.esc(item['fixed_in'])}" if item.get("fixed_in") else ""),
        *where,
        tg.link(item.get("url"), "Source"),
    ]
    return "\n".join(ln for ln in lines if ln)


def _alert(installation_id: int) -> int:
    """Claim and send each unalerted report that may affect the workspace and OSV does not list yet."""
    from codeintent import telegram as tg

    if not tg.configured():
        return 0
    with store.connection() as conn:
        chats = [
            r["chat_id"]
            for r in conn.execute(
                "SELECT chat_id FROM ci_telegram_chats WHERE installation_id=%s",
                (installation_id,),
            ).fetchall()
        ]
        if not chats:
            return 0
        rows = conn.execute(
            """UPDATE ci_security_news SET alerted_at=now()
            WHERE installation_id=%s AND alerted_at IS NULL AND affects IN ('yes','maybe') AND NOT in_osv
            RETURNING *""",
            (installation_id,),
        ).fetchall()
    sent = 0
    for row in rows:
        try:
            for chat in chats:
                tg.send(chat, alert_text(row))
            sent += 1
        except Exception as error:
            logger.warning("News alert failed (%s)", type(error).__name__)
            with store.connection() as conn:
                conn.execute(
                    "UPDATE ci_security_news SET alerted_at=NULL WHERE installation_id=%s AND package=%s AND key=%s",
                    (installation_id, row["package"], row["key"]),
                )
    return sent
