"""One verdict per upgrade, decided by fixed rules over the static comparison; no model is involved.

- **Breaks you**: something the code uses is removed, or an argument it passes no longer works, and the use
  is not behind an import fallback.
- **Not checked**: a usage this analysis could not follow touches part of the library that changed.
- **Needs a change**: a deprecation, a guarded removal, or a changed literal default.
- **No known impact**: everything the code uses was compared in both releases and nothing relevant changed.
  It never means "safe".
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import griffe
import httpx
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from codeintent.upgrades import advisories as osv
from codeintent.upgrades import artifacts, manifests
from codeintent.upgrades.advisories import AdvisoryCheck
from codeintent.upgrades.models import (
    APIChange,
    Location,
    Record,
    ReleaseRange,
    Unchecked,
    UsageCheck,
)
from codeintent.upgrades.releases import locate
from codeintent.upgrades.surface import Found, Surface, check, hint_from
from codeintent.upgrades.usage import scan

Verdict = Literal["breaks", "needs-change", "not-checked", "no-known-impact"]
Severity = Literal["breaks", "needs-change"]
LABELS: dict[Verdict, str] = {
    "breaks": "Breaks you",
    "needs-change": "Needs a change",
    "not-checked": "Not checked",
    "no-known-impact": "No known impact",
}
BREAKING = {"removed", "parameter-removed", "parameter-required", "parameter-moved"}
FALLBACK_GUARDS = {"import-error", "broad-exception", "type-checking"}
GLOBAL_LIMITS = {"dynamic-import"}
"""Unknowns that can't be tied to one library (``importlib.import_module(name)``): stated, not counted."""
OPTIONAL = frozenset(
    {"simplejson", "ujson", "orjson", "chardet", "cchardet", "brotli", "brotlicffi"}
)
"""Accelerators libraries try to import first; absent unless the consumer declares or locks them."""


class Finding(Record):
    """One change, with every place in the consumer it affects."""

    severity: Severity
    change: APIChange
    guarded: bool = False
    locations: tuple[Location, ...]


class Coverage(Record):
    files: int
    usages: int
    checked: int
    unchecked: int
    unchanged_unchecked: int
    upstream_changes: int


class UpgradeVerdict(Record):
    package: str
    start: str
    end: str
    verdict: Verdict
    label: str
    reason: str
    findings: tuple[Finding, ...] = ()
    unchecked: tuple[Unchecked, ...] = ()
    limits: tuple[Unchecked, ...] = ()
    """What could not be followed but touches nothing the upgrade changed, or can't be tied to it."""
    coverage: Coverage | None = None
    release: ReleaseRange | None = None
    advisories: tuple[AdvisoryCheck, ...] = ()


def _severity(change: APIChange, guard: str | None) -> tuple[Severity, bool]:
    guarded = guard in FALLBACK_GUARDS
    if change.kind in BREAKING and not guarded:
        return "breaks", False
    return "needs-change", guarded and change.kind in BREAKING


def _findings(checks: list[UsageCheck]) -> list[Finding]:
    grouped: dict[tuple, dict] = {}
    for result in checks:
        for change in result.changes:
            severity, guarded = _severity(change, result.usage.guard)
            key = (severity, guarded, change.kind, change.symbol, change.parameter)
            entry = grouped.setdefault(key, {"change": change, "locations": []})
            if result.usage.location not in entry["locations"]:
                entry["locations"].append(result.usage.location)
    findings = [
        Finding(
            severity=key[0],
            guarded=key[1],
            change=entry["change"],
            locations=tuple(entry["locations"]),
        )
        for key, entry in grouped.items()
    ]
    order = {"breaks": 0, "needs-change": 1}
    return sorted(
        findings,
        key=lambda f: (order[f.severity], f.change.symbol, f.change.parameter or ""),
    )


def _changed(old: Surface, new: Surface, checks: list[UsageCheck]) -> dict[str, bool]:
    """Paths whose surface the upgrade changed, mapped to whether the object itself was removed.

    griffe's breakage list plus our own findings; deprecations warn but leave the surface intact.
    """
    paths: dict[str, bool] = {}
    for result in checks:
        for change in result.changes:
            if change.kind != "deprecated":
                paths[change.symbol] = (
                    paths.get(change.symbol, False) or change.kind == "removed"
                )
    for name in new.modules:
        before, after = old.module(name), new.module(name)
        if before is None or after is None:
            continue
        try:
            for breakage in griffe.find_breaking_changes(before, after):
                removed = breakage.kind is griffe.BreakageKind.OBJECT_REMOVED
                path = breakage.obj.path
                paths[path] = paths.get(path, False) or removed
        except (
            griffe.AliasResolutionError,
            griffe.CyclicAliasError,
            AttributeError,
            KeyError,
        ):
            paths[name] = True
    return paths


def _anchor(surface: Surface, symbol: str) -> str:
    """The deepest part of ``symbol`` that resolves to an object in this release."""
    parts = symbol.split(".")
    for end in range(len(parts), 0, -1):
        found = surface.lookup(".".join(parts[:end]))
        if isinstance(found, Found) and found.obj is not None:
            return found.obj.path
        if isinstance(found, Found) and found.external:
            return found.path
    return parts[0]


def _touches(anchor: str, changed: dict[str, bool]) -> bool:
    """The object itself or something inside it changed, or an enclosing object was removed."""
    return any(
        path == anchor
        or path.startswith(anchor + ".")
        or (removed and anchor.startswith(path + "."))
        for path, removed in changed.items()
    )


def _absent(root: Path) -> frozenset[str]:
    """Optional imports the consumer can't have: names not among its declared or locked dependencies."""
    declared = {canonicalize_name(d.name) for d in manifests.scan(root).dependencies}
    return frozenset(OPTIONAL - declared)


def decide(
    package: str, start: str, end: str, root: Path, old: Surface, new: Surface
) -> UpgradeVerdict:
    """The verdict for upgrading ``package`` from ``start`` to ``end`` in the code at ``root``."""
    modules = tuple(dict.fromkeys((*new.modules, *old.modules)))
    old.absent = new.absent = _absent(root)
    usages = scan(root, modules)
    checks = [check(old, new, usage) for usage in usages.usages]
    findings = _findings(checks)
    changed = _changed(old, new, checks)
    relevant: list[Unchecked] = []
    limits: list[Unchecked] = []
    for result in checks:
        if not result.unchecked:
            continue
        touched = _touches(_anchor(old, result.usage.symbol), changed)
        (relevant if touched else limits).extend(result.unchecked)
    for item in usages.unchecked:
        if item.reason in GLOBAL_LIMITS:
            touched = False
        elif item.symbol:
            touched = _touches(_anchor(old, item.symbol), changed)
        else:
            touched = bool(changed)
        (relevant if touched else limits).append(item)
    ignored = len(limits)
    unchecked_usages = sum(1 for r in checks if r.unchecked)
    coverage = Coverage(
        files=usages.files,
        usages=len(checks),
        checked=len(checks) - unchecked_usages,
        unchecked=unchecked_usages + len(usages.unchecked),
        unchanged_unchecked=ignored,
        upstream_changes=len(changed),
    )
    breaks = [f for f in findings if f.severity == "breaks"]
    if breaks:
        lines = sum(len(f.locations) for f in breaks)
        verdict: Verdict = "breaks"
        reason = f"{len(breaks)} change(s) in {package} {end} break code you use, at {lines} place(s)"
    elif relevant:
        verdict = "not-checked"
        reason = f"{len(relevant)} use(s) of {package} could not be followed, and they touch parts that changed in {end}"
    elif findings:
        verdict = "needs-change"
        reason = f"{len(findings)} change(s) in {package} {end} affect code you use but do not break it"
    elif not checks:
        verdict = "no-known-impact"
        reason = f"the code does not import {package} directly"
    else:
        verdict = "no-known-impact"
        compared = len(checks) - unchecked_usages
        reason = (
            f"all {len(checks)} use(s) of {package} were compared in {start} and {end}; none changed"
            if not limits
            else f"{compared} of {len(checks)} use(s) of {package} were compared in {start} and {end} "
            f"and none changed; {len(limits)} could not be followed, but touch nothing this upgrade changed"
        )
    return UpgradeVerdict(
        package=package,
        start=start,
        end=end,
        verdict=verdict,
        label=LABELS[verdict],
        reason=reason,
        findings=tuple(findings),
        unchecked=tuple(relevant),
        limits=tuple(limits),
        coverage=coverage,
    )


def _between(package: str, start: str, end: str, client: httpx.Client) -> str | None:
    """The newest final release after ``start`` and before ``end``."""
    response = client.get(f"https://pypi.org/pypi/{canonicalize_name(package)}/json")
    if response.status_code != 200:
        return None
    low, high, found = Version(start), Version(end), []
    for text, files in response.json().get("releases", {}).items():
        try:
            version = Version(text)
        except InvalidVersion:
            continue
        if (
            low < version < high
            and not version.is_prerelease
            and any(not f.get("yanked") for f in files)
        ):
            found.append(version)
    return str(max(found)) if found else None


def _hinted(
    result: UpgradeVerdict,
    package: str,
    start: str,
    end: str,
    new: Surface,
    client: httpx.Client,
) -> UpgradeVerdict:
    """Look for missing deprecation messages in the last release before ``end``."""
    if not any(
        f.change.kind in ("removed", "parameter-removed") and not f.change.message
        for f in result.findings
    ):
        return result
    middle = _between(package, start, end, client)
    if middle is None:
        return result
    try:
        surface = Surface.fetch(package, middle, client)
    except artifacts.ArtifactError:
        return result
    findings = tuple(
        f.model_copy(update={"change": hint_from(surface, new, f.change)})
        for f in result.findings
    )
    return result.model_copy(update={"findings": findings})


def evaluate(
    package: str,
    start: str,
    end: str,
    root: Path,
    client: httpx.Client,
    *,
    release: bool = True,
    advisory: bool = True,
) -> UpgradeVerdict:
    """Fetch both releases, decide the verdict, and attach the release range and known advisories."""
    try:
        old, new = (
            Surface.fetch(package, start, client),
            Surface.fetch(package, end, client),
        )
    except artifacts.ArtifactError as error:
        result = UpgradeVerdict(
            package=package,
            start=start,
            end=end,
            verdict="not-checked",
            label=LABELS["not-checked"],
            reason=f"the release could not be read: {error.detail}",
        )
    else:
        result = decide(package, start, end, root, old, new)
        result = _hinted(result, package, start, end, new, client)
    extra: dict = {}
    if release:
        try:
            extra["release"] = locate(package, start, end, client)
        except (httpx.HTTPError, LookupError) as error:
            extra["release"] = ReleaseRange(
                package=package,
                start={"version": start},
                end={"version": end},
                not_located=f"release lookup failed: {type(error).__name__}",
            )
    if advisory:
        extra["advisories"] = tuple(
            osv.check([(package, start), (package, end)], client)
        )
    return result.model_copy(update=extra) if extra else result
