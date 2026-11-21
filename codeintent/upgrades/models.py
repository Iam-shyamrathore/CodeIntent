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
    column: int | None = None


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


UsageKind = Literal["import", "reference", "annotation", "call", "subclass"]
Guard = Literal["import-error", "broad-exception", "type-checking"]
UncheckedReason = Literal[
    "compiled-module",
    "dynamic-attribute",
    "dynamic-definition",
    "dynamic-import",
    "environment-dependent",
    "external-alias",
    "external-base",
    "file-too-large",
    "kwargs-absorbed",
    "kwargs-passthrough",
    "load-error",
    "not-in-distribution",
    "not-in-old-version",
    "parse-error",
    "path-outside-repository",
    "return-value",
    "signature-unknown",
    "star-import",
]


class Usage(Record):
    symbol: str
    kind: UsageKind
    keywords: tuple[str, ...] = ()
    positional: int = 0
    via: tuple[str, ...] = ()
    guard: Guard | None = None
    location: Location


class Unchecked(Record):
    reason: UncheckedReason
    detail: str
    location: Location
    symbol: str | None = None


class UsageScan(Record):
    modules: tuple[str, ...]
    files: int
    usages: tuple[Usage, ...] = ()
    unchecked: tuple[Unchecked, ...] = ()


RepositoryEvidence = Literal["attestation", "project-urls", "deps.dev"]
TagMatch = Literal["exact-ref", "tag-list", "release-date"]


class ReleasePoint(Record):
    version: str
    published: str | None = None
    yanked: bool = False
    tag: str | None = None
    commit: str | None = None
    match: TagMatch | None = None


class ReleaseRange(Record):
    package: str
    repository: str | None = None
    evidence: RepositoryEvidence | None = None
    start: ReleasePoint
    end: ReleasePoint
    not_located: str | None = None


ChangeKind = Literal[
    "removed",
    "parameter-removed",
    "parameter-required",
    "parameter-moved",
    "default-changed",
    "deprecated",
]


ReplacementSource = Literal["message", "message-unverified", "signature"]


class APIChange(Record):
    """A difference between two releases that touches something the consumer uses."""

    kind: ChangeKind
    symbol: str
    parameter: str | None = None
    detail: str
    message: str | None = None
    message_version: str | None = None
    """The release whose source contains ``message``, when not the obvious one."""
    replacement: str | None = None
    replacement_source: ReplacementSource | None = None
    before: Location | None = None
    after: Location | None = None


class UsageCheck(Record):
    usage: Usage
    changes: tuple[APIChange, ...] = ()
    unchecked: tuple[Unchecked, ...] = ()
