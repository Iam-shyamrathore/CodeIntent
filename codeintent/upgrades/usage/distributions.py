"""Import names provided by a PyPI distribution, read from its released files.

Follows deptry's approach (MIT) of reading package metadata rather than an installed environment, and
descends through namespace packages (``google`` -> ``google.cloud.storage``) so roots stay specific.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from codeintent.upgrades import artifacts

_IGNORED = {"tests", "test", "docs", "examples", "benchmarks", "scripts"}


def _source_root(unpacked: Path) -> Path:
    if any(p.suffix == ".dist-info" for p in unpacked.iterdir()):
        return unpacked
    project = next((p for p in unpacked.iterdir() if p.is_dir()), unpacked)
    return project / "src" if (project / "src").is_dir() else project


def _packages(directory: Path, prefix: str = "") -> list[str]:
    roots = []
    for child in sorted(directory.iterdir()):
        name = f"{prefix}{child.name}"
        if (
            child.is_dir()
            and child.name.isidentifier()
            and not child.name.startswith("_")
            and child.name not in _IGNORED
        ):
            if (child / "__init__.py").is_file() or (child / "__init__.pyi").is_file():
                roots.append(name)
            elif (
                not prefix
                or any(p.suffix in (".py", ".pyi") for p in child.iterdir()) is False
            ):
                roots.extend(_packages(child, name + "."))
        elif (
            child.is_file()
            and child.suffix in (".py", ".pyi", ".so", ".pyd")
            and not prefix
        ):
            stem = child.name.split(".")[0]
            if (
                stem.isidentifier()
                and stem not in ("setup", "conftest")
                and not stem.startswith("_")
            ):
                roots.append(stem)
    return roots


def import_names(name: str, version: str, client: httpx.Client) -> tuple[str, ...]:
    unpacked = artifacts.fetch(name, version, client)
    roots = _packages(_source_root(unpacked))
    return tuple(dict.fromkeys(roots))
