"""Known vulnerability advisories for exact PyPI releases, looked up in OSV.dev.

One ``POST /v1/querybatch`` per 1,000 package versions returns advisory ids (paged per query by
``next_page_token``); each distinct id is then fetched once with ``GET /v1/vulns/{id}``. OSV
aggregates the PyPA Advisory Database (PYSEC), the GitHub Advisory Database (GHSA), OpenSSF Malicious
Packages (MAL) and others, so one issue often appears under several ids; records that alias each
other are merged, keeping the GHSA id as the primary one.

A lookup that fails for any reason is reported as ``not-checked`` with the reason, never as
``none-known``. Only successful answers are cached on disk.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from codeintent.upgrades.models import Dependency, Record

OSV = "https://api.osv.dev"
WEB = "https://osv.dev/vulnerability"
ECOSYSTEM = "PyPI"
CACHE = (
    Path(
        os.getenv(
            "CODEINTENT_ARTIFACT_CACHE",
            Path.home() / ".cache" / "codeintent" / "artifacts",
        )
    ).parent
    / "advisories"
)
CACHE_SECONDS = 12 * 3600
MAX_BATCH = 1000
MAX_PAGES = 10
MAX_DETAILS = 2000
DETAIL_WORKERS = 8
PROJECT_NAME = re.compile(r"^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$", re.IGNORECASE)
SOURCES = {
    "GHSA": "GitHub Advisory Database",
    "PYSEC": "PyPA Advisory Database",
    "MAL": "OpenSSF Malicious Packages",
    "PSF": "Python Software Foundation",
    "OSV": "OSS-Fuzz",
    "CVE": "NVD (converted by OSV.dev)",
}
PRIMARY = ("GHSA", "PYSEC")
CVSS = ("CVSS_V4", "CVSS_V3", "CVSS_V2")

Status = Literal["advisories", "none-known", "not-checked"]


class Advisory(Record):
    id: str
    aliases: tuple[str, ...] = ()
    merged: tuple[str, ...] = ()
    summary: str | None = None
    severity: str | None = None
    cvss: str | None = None
    published: str | None = None
    modified: str | None = None
    fixed: str | None = None
    listed_affected: bool | None = None
    withdrawn: bool = False
    source: str
    source_url: str | None = None
    url: str


class AdvisoryCheck(Record):
    package: str
    version: str
    status: Status
    advisories: tuple[Advisory, ...] = ()
    detail: str | None = None
    checked_at: str | None = None

    @property
    def active(self) -> tuple[Advisory, ...]:
        return tuple(a for a in self.advisories if not a.withdrawn)


class _Failure(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def not_checked(name: str, version: str, detail: str) -> AdvisoryCheck:
    return AdvisoryCheck(
        package=canonicalize_name(name),
        version=version,
        status="not-checked",
        detail=detail,
    )


def _cache_path(name: str, version: Version) -> Path:
    return CACHE / canonicalize_name(name) / f"{version}.json"


def _cached(name: str, version: Version) -> AdvisoryCheck | None:
    path = _cache_path(name, version)
    try:
        if time.time() - path.stat().st_mtime > CACHE_SECONDS:
            return None
        found = AdvisoryCheck.model_validate_json(path.read_text())
    except (OSError, ValueError):
        return None
    return None if found.status == "not-checked" else found


def _store(version: Version, result: AdvisoryCheck) -> None:
    if result.status == "not-checked":
        return
    path = _cache_path(result.package, version)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, suffix=".part", delete=False
        ) as handle:
            handle.write(result.model_dump_json())
        Path(handle.name).replace(path)
    except OSError:
        return


def _json(response: httpx.Response, what: str) -> dict:
    if response.status_code != 200:
        raise _Failure(f"OSV {what} returned HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as error:
        raise _Failure(f"OSV {what} returned invalid JSON") from error
    if not isinstance(body, dict):
        raise _Failure(f"OSV {what} returned an unexpected body")
    return body


def _post(client: httpx.Client, queries: list[dict]) -> list[dict]:
    try:
        response = client.post(f"{OSV}/v1/querybatch", json={"queries": queries})
    except httpx.HTTPError as error:
        raise _Failure(
            f"OSV querybatch failed: {type(error).__name__}: {error}"
        ) from error
    results = _json(response, "querybatch").get("results")
    if not isinstance(results, list) or len(results) != len(queries):
        raise _Failure("OSV querybatch returned a different number of results")
    return results


def _ids(client: httpx.Client, queries: list[dict]) -> list[list[str]]:
    """Advisory ids per query, following each query's own ``next_page_token``."""
    found: list[list[str]] = [[] for _ in queries]
    pending = list(range(len(queries)))
    tokens: dict[int, str] = {}
    for _ in range(MAX_PAGES):
        page = [
            {**queries[i], "page_token": tokens[i]} if i in tokens else queries[i]
            for i in pending
        ]
        tokens = {}
        for i, result in zip(pending, _post(client, page), strict=True):
            found[i] += [v["id"] for v in result.get("vulns") or [] if v.get("id")]
            if token := result.get("next_page_token"):
                tokens[i] = token
        pending = list(tokens)
        if not pending:
            return [list(dict.fromkeys(ids)) for ids in found]
    raise _Failure(f"OSV querybatch still paging after {MAX_PAGES} pages")


def _detail(client: httpx.Client, vuln_id: str) -> dict | str:
    try:
        response = client.get(f"{OSV}/v1/vulns/{vuln_id}")
        return _json(response, f"record {vuln_id}")
    except httpx.HTTPError as error:
        return f"OSV record {vuln_id} failed: {type(error).__name__}: {error}"
    except _Failure as error:
        return str(error)


def _prefix(vuln_id: str) -> str:
    return vuln_id.split("-", 1)[0].upper()


def _affected(record: dict, name: str) -> list[dict]:
    return [
        a
        for a in record.get("affected") or []
        if (a.get("package") or {}).get("ecosystem") == ECOSYSTEM
        and canonicalize_name((a.get("package") or {}).get("name", "")) == name
    ]


def _versions(values: Iterable[str]) -> list[Version]:
    parsed = []
    for value in values:
        try:
            parsed.append(Version(value))
        except (InvalidVersion, TypeError):
            continue
    return parsed


def _fixed(affected: list[dict], version: Version) -> Version | None:
    fixes = _versions(
        event["fixed"]
        for a in affected
        for r in a.get("ranges") or []
        if r.get("type") == "ECOSYSTEM"
        for event in r.get("events") or []
        if event.get("fixed")
    )
    later = [f for f in fixes if f > version]
    return min(later) if later else None


def _listed(affected: list[dict], version: Version) -> bool | None:
    listed = [a["versions"] for a in affected if a.get("versions")]
    if not listed:
        return None
    return any(version in _versions(values) for values in listed)


def _severity(record: dict, affected: list[dict]) -> tuple[str | None, str | None]:
    scores = list(record.get("severity") or []) + [
        s for a in affected for s in a.get("severity") or []
    ]
    vectors = {s.get("type"): s.get("score") for s in reversed(scores)}
    cvss = next((vectors[t] for t in CVSS if vectors.get(t)), None)
    labels = [record.get("database_specific") or {}] + [
        a.get("database_specific") or {} for a in affected
    ]
    label = next(
        (d["severity"] for d in labels if isinstance(d.get("severity"), str)), None
    )
    return label, cvss


def _source_url(record: dict, affected: list[dict]) -> str | None:
    for specific in [record.get("database_specific") or {}] + [
        a.get("database_specific") or {} for a in affected
    ]:
        if isinstance(specific.get("source"), str):
            return specific["source"]
    return None


def _url(vuln_id: str, records: list[dict]) -> str:
    references = [
        r.get("url")
        for record in records
        for r in record.get("references") or []
        if r.get("type") == "ADVISORY" and r.get("url")
    ]
    own = [u for u in references if vuln_id in u]
    return (own or references or [f"{WEB}/{vuln_id}"])[0]


def _rank(record: dict) -> tuple:
    prefix = _prefix(record["id"])
    order = PRIMARY.index(prefix) if prefix in PRIMARY else len(PRIMARY)
    return bool(record.get("withdrawn")), order, record["id"]


def _groups(records: list[dict]) -> list[list[dict]]:
    """Records whose ids or aliases overlap, transitively."""
    groups: list[tuple[set[str], list[dict]]] = []
    for record in records:
        keys = {record["id"], *(record.get("aliases") or [])}
        joined = [g for g in groups if g[0] & keys]
        for group in joined:
            keys |= group[0]
        members = [r for g in joined for r in g[1]] + [record]
        groups = [g for g in groups if g not in joined] + [(keys, members)]
    return [sorted(members, key=_rank) for _, members in groups]


def _advisory(records: list[dict], name: str, version: Version) -> Advisory:
    primary = records[0]
    affected = [a for r in records for a in _affected(r, name)]
    own = _affected(primary, name)
    label, cvss = _severity(primary, own)
    for record in records[1:]:
        found = _severity(record, _affected(record, name))
        label, cvss = label or found[0], cvss or found[1]
    fixed = _fixed(own, version) or _fixed(affected, version)
    aliases = {a for r in records for a in r.get("aliases") or []} - {primary["id"]}
    return Advisory(
        id=primary["id"],
        aliases=tuple(sorted(aliases)),
        merged=tuple(r["id"] for r in records[1:]),
        summary=primary.get("summary")
        or next((r["summary"] for r in records if r.get("summary")), None),
        severity=label,
        cvss=cvss,
        published=primary.get("published"),
        modified=max(r.get("modified") or "" for r in records) or None,
        fixed=str(fixed) if fixed else None,
        listed_affected=_listed(affected, version),
        withdrawn=all(r.get("withdrawn") for r in records),
        source=SOURCES.get(_prefix(primary["id"]), _prefix(primary["id"])),
        source_url=_source_url(primary, own),
        url=_url(primary["id"], records),
    )


def _result(
    name: str, version: str, parsed: Version, records: list[dict], checked: str
) -> AdvisoryCheck:
    package = canonicalize_name(name)
    advisories = sorted(
        (_advisory(group, package, parsed) for group in _groups(records)),
        key=lambda a: (a.withdrawn, a.published or "", a.id),
    )
    live = [a for a in advisories if not a.withdrawn]
    detail = None
    if parsed.local:
        detail = f"queried the public version {parsed.public} for local build {parsed}"
    return AdvisoryCheck(
        package=package,
        version=version,
        status="advisories" if live else "none-known",
        advisories=tuple(advisories),
        detail=detail,
        checked_at=checked,
    )


def _lookup(
    pending: list[tuple[str, str, Version]], client: httpx.Client
) -> list[AdvisoryCheck]:
    queries = [
        {
            "package": {"ecosystem": ECOSYSTEM, "name": canonicalize_name(name)},
            "version": str(parsed.public),
        }
        for name, _, parsed in pending
    ]
    try:
        ids = _ids(client, queries)
    except _Failure as error:
        return [not_checked(n, v, str(error)) for n, v, _ in pending]
    unique = list(dict.fromkeys(i for found in ids for i in found))
    wanted, skipped = unique[:MAX_DETAILS], set(unique[MAX_DETAILS:])
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
        details = dict(
            zip(wanted, pool.map(lambda i: _detail(client, i), wanted), strict=True)
        )
    checked = _now()
    results = []
    for (name, version, parsed), found in zip(pending, ids, strict=True):
        if over := [i for i in found if i in skipped]:
            reason = f"{len(over)} advisory records exceeded the per-run limit of {MAX_DETAILS}"
            results.append(not_checked(name, version, reason))
            continue
        if failed := [details[i] for i in found if isinstance(details[i], str)]:
            results.append(not_checked(name, version, failed[0]))
            continue
        records = [details[i] for i in found]
        results.append(_result(name, version, parsed, records, checked))
    return results


def check(
    dependencies: list[tuple[str, str]], client: httpx.Client
) -> list[AdvisoryCheck]:
    """Known OSV advisories for each exact ``(name, version)``, in input order."""
    results: dict[int, AdvisoryCheck] = {}
    pending: dict[tuple[str, Version], list[int]] = {}
    for index, (name, version) in enumerate(dependencies):
        if not PROJECT_NAME.match(name or ""):
            results[index] = not_checked(
                name, version, f"{name!r} is not a valid PyPI project name"
            )
            continue
        try:
            parsed = Version(version)
        except (InvalidVersion, TypeError):
            results[index] = not_checked(
                name, version, f"{version!r} is not a PEP 440 version"
            )
            continue
        if found := _cached(name, parsed):
            results[index] = found.model_copy(update={"version": version})
            continue
        pending.setdefault((canonicalize_name(name), parsed), []).append(index)
    keys = list(pending)
    for start in range(0, len(keys), MAX_BATCH):
        chunk = keys[start : start + MAX_BATCH]
        batch = [
            (name, dependencies[pending[(name, parsed)][0]][1], parsed)
            for name, parsed in chunk
        ]
        for key, result in zip(chunk, _lookup(batch, client), strict=True):
            _store(key[1], result)
            for index in pending[key]:
                results[index] = result.model_copy(
                    update={"version": dependencies[index][1]}
                )
    return [results[i] for i in range(len(dependencies))]


def check_one(name: str, version: str, client: httpx.Client) -> AdvisoryCheck:
    return check([(name, version)], client)[0]


def check_dependencies(
    dependencies: Iterable[Dependency], client: httpx.Client
) -> list[AdvisoryCheck]:
    """``check`` for scanned manifest dependencies; non-PyPI and unpinned ones are not checked."""
    dependencies = list(dependencies)
    lookups = [
        (d.name, d.locked_version)
        for d in dependencies
        if d.source == "registry" and d.locked_version
    ]
    found = iter(check(lookups, client))
    results = []
    for d in dependencies:
        if d.source != "registry":
            results.append(
                not_checked(
                    d.name,
                    d.locked_version or "",
                    f"installed from a {d.source} source, not PyPI",
                )
            )
        elif not d.locked_version:
            results.append(
                not_checked(d.name, "", "no exact version is locked or pinned")
            )
        else:
            results.append(next(found))
    return results
