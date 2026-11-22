"""``uv.lock`` and ``poetry.lock``: exact resolved versions and which packages are direct."""

from __future__ import annotations

import tomllib

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from codeintent.upgrades.manifests.toml_lines import TomlLines
from codeintent.upgrades.models import Dependency, Format, Issue, Location

_UV_SOURCES = {
    "registry": "registry",
    "git": "vcs",
    "url": "url",
    "path": "path",
    "directory": "path",
    "editable": "editable",
}
_POETRY_SOURCES = {"git": "vcs", "url": "url", "file": "path", "directory": "path"}


class Lock:
    format: Format

    def __init__(self, text: str, file: str):
        self.file = file
        self.dependencies: list[Dependency] = []
        self.issues: list[Issue] = []
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            self.issue("invalid-toml", str(error))
            return
        packages = data.get("package", [])
        if not isinstance(packages, list) or not all(
            isinstance(p, dict) for p in packages
        ):
            self.issue("invalid-structure", "package entries are not tables")
            return
        if self.supported(data):
            blocks = TomlLines(text).tables(("package",))
            self.read(packages, [b.keys.get("name") for b in blocks])

    def issue(self, reason: str, detail: str):
        self.issues.append(
            Issue(reason=reason, detail=detail, location=Location(file=self.file))
        )

    def record(
        self, package: dict, line: int | None, *, source: str, group: str, direct: bool
    ):
        name, version = package.get("name"), package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            return self.issue(
                "invalid-structure", "package entry without a name and version"
            )
        self.dependencies.append(
            Dependency(
                name=canonicalize_name(name),
                declared=f"{name}=={version}",
                group=group,
                direct=direct,
                source=source,
                locked_version=version,
                format=self.format,
                location=Location(file=self.file, line=line),
            )
        )
        return None


class UvLock(Lock):
    format = "uv.lock"

    def supported(self, data) -> bool:
        if data.get("version") != 1:
            self.issue(
                "unsupported-lock-version",
                f"uv.lock version {data.get('version')!r} is not supported",
            )
            return False
        return True

    @staticmethod
    def local(package: dict) -> bool:
        source = package.get("source", {})
        return isinstance(source, dict) and (
            "virtual" in source or "editable" in source
        )

    def read(self, packages: list[dict], lines: list[int | None]):
        groups: dict[str, set[str]] = {}
        for root in filter(self.local, packages):
            for entry in root.get("dependencies", []):
                groups.setdefault(canonicalize_name(entry.get("name", "")), set()).add(
                    "main"
                )
            for table, prefix in (
                ("optional-dependencies", "optional"),
                ("dev-dependencies", "group"),
            ):
                for group, entries in root.get(table, {}).items():
                    for entry in entries:
                        label = f"{prefix}:{canonicalize_name(group)}"
                        groups.setdefault(
                            canonicalize_name(entry.get("name", "")), set()
                        ).add(label)
        for package, line in zip(
            packages, lines + [None] * len(packages), strict=False
        ):
            if self.local(package):
                continue
            source = next(
                (
                    kind
                    for key, kind in _UV_SOURCES.items()
                    if key in package.get("source", {})
                ),
                "registry",
            )
            member = groups.get(canonicalize_name(str(package.get("name", ""))))
            group = ",".join(sorted(member)) if member else "transitive"
            self.record(package, line, source=source, group=group, direct=bool(member))


class PoetryLock(Lock):
    format = "poetry.lock"

    def supported(self, data) -> bool:
        raw = str(data.get("metadata", {}).get("lock-version", "1.0"))
        try:
            version = Version(raw)
        except InvalidVersion:
            version = None
        if version is None or not Version("1") <= version < Version("3"):
            self.issue(
                "unsupported-lock-version",
                f"poetry.lock lock-version {raw!r} is not supported",
            )
            return False
        return True

    def read(self, packages: list[dict], lines: list[int | None]):
        for package, line in zip(
            packages, lines + [None] * len(packages), strict=False
        ):
            kind = (
                package.get("source", {}).get("type")
                if isinstance(package.get("source"), dict)
                else None
            )
            groups = package.get("groups")
            group = (
                ",".join(sorted(groups))
                if isinstance(groups, list)
                else str(package.get("category", "main"))
            )
            self.record(
                package,
                line,
                source=_POETRY_SOURCES.get(kind, "registry"),
                group=group,
                direct=False,
            )
