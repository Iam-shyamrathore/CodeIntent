"""Typed records shared by the upgrade verdict engine."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Format = Literal[
    "requirements", "pyproject", "uv.lock", "poetry.lock", "setup.cfg", "setup.py"
]
Source = Literal["registry", "url", "vcs", "path", "editable"]
PinKind = Literal[
    "exact", "wildcard", "upper_bound", "exclusion", "compatible", "caret", "tilde"
]
IssueReason = Literal[
    "dynamic-dependencies",
    "environment-variable",
    "file-too-large",
    "include-cycle",
    "include-missing",
    "include-outside-repository",
    "invalid-python",
    "invalid-structure",
    "invalid-toml",
    "non-literal-setup-argument",
    "path-outside-repository",
    "unparseable-requirement",
    "unsupported-constraint",
    "unsupported-lock-version",
]


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Location(Record):
    file: str
    line: int | None = None


class Pin(Record):
    kind: PinKind
    clause: str


class Dependency(Record):
    name: str
    declared: str
    specifier: str = ""
    marker: str | None = None
    extras: tuple[str, ...] = ()
    group: str = "main"
    direct: bool = True
    constraint_only: bool = False
    source: Source = "registry"
    locked_version: str | None = None
    pins: tuple[Pin, ...] = ()
    format: Format
    location: Location


class Issue(Record):
    reason: IssueReason
    detail: str
    location: Location


class ManifestScan(Record):
    dependencies: tuple[Dependency, ...] = ()
    issues: tuple[Issue, ...] = ()
