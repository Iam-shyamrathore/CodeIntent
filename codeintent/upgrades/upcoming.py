"""What breaks on the next upgrade: every direct dependency, from its locked version to the latest release.

Runs the same verdict engine as a pull request, before Dependabot or Renovate opens one. Only dependencies
with an exact version (locked, or pinned with ``==``) are compared; ranges have no single installed version.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import httpx
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from codeintent.upgrades import advisories as osv
from codeintent.upgrades import manifests
from codeintent.upgrades.advisories import AdvisoryCheck
from codeintent.upgrades.models import Location, Record
from codeintent.upgrades.verdict import UpgradeVerdict, evaluate

PYPI = "https://pypi.org/pypi"
DECLARING = {"pyproject", "setup.cfg", "setup.py"}
MAX_PACKAGES = 40
Status = Literal["compared", "current", "not-locked", "not-on-pypi", "unreadable"]


class Upcoming(Record):
    package: str
    current: str | None = None
    latest: str | None = None
    status: Status
    location: Location
    verdict: UpgradeVerdict | None = None
    detail: str | None = None
    advisories: AdvisoryCheck | None = None
    """Known advisories for the version in use now, whether or not a newer release exists."""


def latest(name: str, client: httpx.Client) -> str | None:
    """The newest final release with at least one file that is not yanked."""
    response = client.get(f"{PYPI}/{canonicalize_name(name)}/json")
    if response.status_code != 200:
        return None
    versions = []
    for text, files in response.json().get("releases", {}).items():
        try:
            version = Version(text)
        except InvalidVersion:
            continue
        if not version.is_prerelease and any(not f.get("yanked") for f in files):
            versions.append(version)
    return str(max(versions)) if versions else None


def _exact(dependency) -> str | None:
    if dependency.locked_version and "," not in dependency.locked_version:
        return dependency.locked_version
    specifier = dependency.specifier.strip()
    if specifier.startswith("==") and "," not in specifier and "*" not in specifier:
        return specifier[2:].strip()
    return None


def scan(
    root: Path,
    client: httpx.Client,
    limit: int = MAX_PACKAGES,
    *,
    explain: bool = False,
) -> list[Upcoming]:
    """One entry per direct registry dependency; verdicts for those with a newer release.

    ``explain`` looks up the release range and the upstream pull request behind each finding, only for
    upgrades that have findings, since that costs GitHub API calls.
    """
    dependencies = [
        d
        for d in manifests.scan(root).dependencies
        if d.direct and d.source == "registry"
    ]
    declared = [d for d in dependencies if d.format in DECLARING]
    # A project file declares the direct dependencies; requirements files next to it are usually
    # exported locks listing every transitive package, so they only supply versions.
    chosen = declared or dependencies
    seen: dict[str, Upcoming] = {}
    pending = []
    for dependency in chosen:
        name = canonicalize_name(dependency.name)
        if name in seen:
            continue
        current = _exact(dependency) or (
            next(
                (
                    _exact(d)
                    for d in dependencies
                    if canonicalize_name(d.name) == name and _exact(d)
                ),
                None,
            )
        )
        seen[name] = Upcoming(
            package=name,
            current=current,
            status="not-locked",
            location=dependency.location,
        )
        if current is not None:
            pending.append(name)
    with ThreadPoolExecutor(max_workers=8) as pool:
        newest_of = dict(zip(pending, pool.map(lambda n: latest(n, client), pending)))
    for name in pending:
        item, newest = seen[name], newest_of[name]
        current = item.current
        if newest is None:
            status = "not-on-pypi"
        elif Version(newest) <= Version(current):
            status = "current"
        else:
            status = "compared"
        seen[name] = item.model_copy(update={"latest": newest, "status": status})
    in_use = [(name, seen[name].current) for name in pending]
    for (name, _), check in zip(in_use, osv.check(in_use, client)):
        seen[name] = seen[name].model_copy(update={"advisories": check})
    results = []
    compared = 0
    for item in seen.values():
        if item.status == "compared" and compared < limit:
            compared += 1
            verdict = evaluate(
                item.package, item.current, item.latest, root, client, release=False
            )
            if explain and verdict.findings:
                verdict = evaluate(
                    item.package, item.current, item.latest, root, client
                )
            unreadable = verdict.verdict == "not-checked" and verdict.coverage is None
            item = item.model_copy(
                update={
                    "verdict": verdict,
                    "status": "unreadable" if unreadable else "compared",
                    "detail": verdict.reason if unreadable else None,
                }
            )
        results.append(item)
    order = {"breaks": 0, "not-checked": 1, "needs-change": 2, "no-known-impact": 3}
    return sorted(
        results,
        key=lambda r: (order.get(r.verdict.verdict, 4) if r.verdict else 5, r.package),
    )
