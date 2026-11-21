"""Find and parse a repository's Python dependency declarations and lock files."""

from __future__ import annotations

from pathlib import Path

from codeintent.upgrades.manifests import files
from codeintent.upgrades.manifests.locks import PoetryLock, UvLock
from codeintent.upgrades.manifests.pyproject import PyProject
from codeintent.upgrades.manifests.requirements import Requirements
from codeintent.upgrades.manifests.setuptools import setup_cfg, setup_py
from codeintent.upgrades.models import Dependency, Issue, Location, ManifestScan

_TOML = {"pyproject.toml": PyProject, "uv.lock": UvLock, "poetry.lock": PoetryLock}
_SETUPTOOLS = {"setup.cfg": setup_cfg, "setup.py": setup_py}
_LOCKS = ("uv.lock", "poetry.lock")


REQUIREMENT_PATTERNS = ("*requirements*.txt", "*requirements*.in", "requirements*.lock")


def _requirement_files(root: Path) -> list[Path]:
    found = [path for pattern in REQUIREMENT_PATTERNS for path in root.glob(pattern)]
    folder = root / "requirements"
    if folder.is_dir():
        found += [*folder.glob("*.txt"), *folder.glob("*.in")]
    return sorted(found)


def _locked_versions(dependencies: list[Dependency]) -> dict[str, str]:
    versions: dict[str, set[str]] = {}
    for dependency in dependencies:
        if dependency.format in _LOCKS and dependency.locked_version:
            versions.setdefault(dependency.name, set()).add(dependency.locked_version)
    return {
        name: next(iter(found)) for name, found in versions.items() if len(found) == 1
    }


def _merge(dependencies: list[Dependency]) -> list[Dependency]:
    locked = _locked_versions(dependencies)
    declared = {d.name for d in dependencies if d.format not in _LOCKS and d.direct}
    merged = []
    for dependency in dependencies:
        if dependency.format in _LOCKS:
            if dependency.format == "poetry.lock" and dependency.name in declared:
                dependency = dependency.model_copy(update={"direct": True})
        elif dependency.locked_version is None:
            exact = [
                p.clause[2:]
                for p in dependency.pins
                if p.kind == "exact" and p.clause.startswith("==")
            ]
            version = locked.get(dependency.name) or (
                exact[0] if len(exact) == 1 else None
            )
            dependency = dependency.model_copy(update={"locked_version": version})
        merged.append(dependency)
    return merged


def scan(root: Path) -> ManifestScan:
    """Parse every supported manifest under ``root`` without executing or importing anything."""
    root = root.resolve()
    dependencies: list[Dependency] = []
    issues: list[Issue] = []
    requirements = Requirements(root)

    def guarded(path: Path, parse):
        try:
            parse()
        except files.Unreadable as error:
            issues.append(
                Issue(
                    reason=error.reason,
                    detail=error.detail,
                    location=Location(file=path.name),
                )
            )

    for name, parser in {**_TOML, **_SETUPTOOLS}.items():
        path = root / name
        if path.is_file() or path.is_symlink():

            def parse(path=path, name=name, parser=parser):
                result = parser(files.read(root, path), files.relative(root, path))
                dependencies.extend(result.dependencies)
                issues.extend(result.issues)

            guarded(path, parse)
    for path in _requirement_files(root):
        guarded(path, lambda path=path: requirements.parse(path))
    dependencies.extend(requirements.dependencies)
    issues.extend(requirements.issues)
    ordered = sorted(
        _merge(dependencies),
        key=lambda d: (d.location.file, d.location.line or 0, d.name),
    )
    return ManifestScan(dependencies=tuple(ordered), issues=tuple(issues))
