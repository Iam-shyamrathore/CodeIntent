"""``pyproject.toml``: PEP 621 project tables, PEP 735 dependency groups, uv and Poetry tables."""

from __future__ import annotations

import tomllib

from packaging.utils import canonicalize_name

from codeintent.upgrades.manifests.common import pep508, strings
from codeintent.upgrades.manifests.pins import from_poetry
from codeintent.upgrades.manifests.toml_lines import TomlLines
from codeintent.upgrades.models import Dependency, Issue, Location

_UV_SOURCES = {"git": "vcs", "url": "url", "path": "path", "workspace": "path"}
_POETRY_SOURCES = {"git": "vcs", "url": "url", "path": "path"}


def _uv_sources(table) -> dict[str, str]:
    result = {}
    for name, spec in (table or {}).items():
        spec = spec[0] if isinstance(spec, list) and spec else spec
        if isinstance(spec, dict):
            if spec.get("editable"):
                result[canonicalize_name(name)] = "editable"
            else:
                for key, kind in _UV_SOURCES.items():
                    if key in spec:
                        result[canonicalize_name(name)] = kind
    return result


class PyProject:
    def __init__(self, text: str, file: str):
        self.file = file
        self.dependencies: list[Dependency] = []
        self.issues: list[Issue] = []
        try:
            self.data = tomllib.loads(text)
        except tomllib.TOMLDecodeError as error:
            self.data = None
            self.issue("invalid-toml", str(error))
            return
        self.lines = TomlLines(text)
        self.sources = _uv_sources(
            self.data.get("tool", {}).get("uv", {}).get("sources")
        )
        self.project()
        self.groups()
        self.poetry()

    def issue(self, reason: str, detail: str, line: int | None = None):
        self.issues.append(
            Issue(
                reason=reason,
                detail=detail,
                location=Location(file=self.file, line=line),
            )
        )

    def add(self, text: str, group: str, line: int | None):
        record = pep508(
            text, format="pyproject", file=self.file, line=line, group=group
        )
        if isinstance(record, Issue):
            return self.issues.append(record)
        if record.name in self.sources:
            record = record.model_copy(update={"source": self.sources[record.name]})
        self.dependencies.append(record)

    def array(self, value, group: str, path: tuple[str, ...], key: str):
        items = strings(value)
        if items is None:
            return self.issue(
                "invalid-structure",
                f"{'.'.join(path + (key,))} is not a list of requirements",
            )
        for text in items:
            line = self.lines.string(path, key, text)
            if line is None and len(path) > 1:
                line = self.lines.string(path[:-1], path[-1], text)
            self.add(text, group, line)

    def project(self):
        project = self.data.get("project", {})
        dynamic = project.get("dynamic", [])
        for field in ("dependencies", "optional-dependencies"):
            if field in dynamic:
                self.issue(
                    "dynamic-dependencies",
                    f"project.{field} is computed by the build backend",
                )
        if "dependencies" in project:
            self.array(project["dependencies"], "main", ("project",), "dependencies")
        for extra, value in project.get("optional-dependencies", {}).items():
            self.array(
                value,
                f"optional:{canonicalize_name(extra)}",
                ("project", "optional-dependencies"),
                extra,
            )

    def groups(self):
        for group, value in self.data.get("dependency-groups", {}).items():
            self.array(
                value,
                f"group:{canonicalize_name(group)}",
                ("dependency-groups",),
                group,
            )
        uv = self.data.get("tool", {}).get("uv", {})
        if "dev-dependencies" in uv:
            self.array(
                uv["dev-dependencies"], "group:dev", ("tool", "uv"), "dev-dependencies"
            )

    def poetry(self):
        poetry = self.data.get("tool", {}).get("poetry", {})
        tables = [
            ("main", ("tool", "poetry", "dependencies"), poetry.get("dependencies", {}))
        ]
        tables.append(
            (
                "group:dev",
                ("tool", "poetry", "dev-dependencies"),
                poetry.get("dev-dependencies", {}),
            )
        )
        for group, spec in poetry.get("group", {}).items():
            path = ("tool", "poetry", "group", group, "dependencies")
            tables.append(
                (
                    f"group:{canonicalize_name(group)}",
                    path,
                    spec.get("dependencies", {}),
                )
            )
        for group, path, table in tables:
            for name, spec in table.items():
                if name.lower() != "python":
                    self.poetry_dependency(
                        name, spec, group, self.lines.key(path, name)
                    )

    def poetry_dependency(self, name: str, spec, group: str, line: int | None):
        if isinstance(spec, list):
            return self.issue(
                "unsupported-constraint", f"{name} has multiple constraints", line
            )
        if isinstance(spec, str):
            spec = {"version": spec}
        if not isinstance(spec, dict):
            return self.issue(
                "invalid-structure", f"{name} has an unsupported dependency value", line
            )
        source = next(
            (kind for key, kind in _POETRY_SOURCES.items() if key in spec), "registry"
        )
        if spec.get("develop"):
            source = "editable"
        try:
            specifier, pins = (
                from_poetry(spec.get("version", "*"))
                if source == "registry"
                else ("", ())
            )
        except ValueError as error:
            return self.issue("unsupported-constraint", f"{name}: {error}", line)
        extras = tuple(sorted(spec.get("extras", [])))
        self.dependencies.append(
            Dependency(
                name=canonicalize_name(name),
                declared=f"{name} = {spec.get('version', source)}",
                specifier=specifier,
                marker=spec.get("markers"),
                extras=extras,
                group=group,
                source=source,
                pins=pins,
                format="pyproject",
                location=Location(file=self.file, line=line),
            )
        )
