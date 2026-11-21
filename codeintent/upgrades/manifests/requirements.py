"""pip requirements files, parsed with pip-requirements-parser (MIT, aboutcode-org).

Includes (``-r``/``-c``) are followed here rather than by the library so that every path stays
inside the repository and include cycles terminate.
"""

from __future__ import annotations

from pathlib import Path

from packaging.utils import canonicalize_name
from pip_requirements_parser import RequirementsFile

from codeintent.upgrades.manifests import files
from codeintent.upgrades.manifests.common import url_source
from codeintent.upgrades.manifests.pins import canonical, classify
from codeintent.upgrades.models import Dependency, Issue, Location


class Requirements:
    def __init__(self, root: Path):
        self.root = root
        self.parsed: set[Path] = set()
        self.dependencies: list[Dependency] = []
        self.issues: list[Issue] = []

    def issue(self, reason: str, detail: str, file: str, line: int | None = None):
        self.issues.append(
            Issue(reason=reason, detail=detail, location=Location(file=file, line=line))
        )

    def parse(
        self, path: Path, *, constraint: bool = False, stack: tuple[Path, ...] = ()
    ):
        real = files.confined(self.root, path)
        if real in stack:
            return self.issue(
                "include-cycle",
                f"{path.name} includes itself",
                files.relative(self.root, stack[-1]),
            )
        if real in self.parsed:
            return
        self.parsed.add(real)
        name = files.relative(self.root, real)
        text = files.read(self.root, path)
        templated = {
            n for n, line in enumerate(text.splitlines(), start=1) if "${" in line
        }
        for number in sorted(templated):
            self.issue(
                "environment-variable",
                "requirement depends on an environment variable",
                name,
                number,
            )
        parsed = RequirementsFile.from_file(str(real), include_nested=False)
        for invalid in parsed.invalid_lines:
            if invalid.line_number not in templated:
                self.issue(
                    "unparseable-requirement",
                    invalid.error_message,
                    name,
                    invalid.line_number,
                )
        for requirement in parsed.requirements:
            if requirement.line_number not in templated:
                self.add(requirement, name, constraint)
        for option in parsed.options:
            for key, nested_constraint in (
                ("requirements", constraint),
                ("constraints", True),
            ):
                for target in option.options.get(key, []):
                    self.include(
                        real,
                        target,
                        nested_constraint,
                        stack + (real,),
                        name,
                        option.line_number,
                    )

    def include(
        self,
        parent: Path,
        target: str,
        constraint: bool,
        stack,
        name: str,
        line: int | None,
    ):
        path = parent.parent / target
        try:
            files.confined(self.root, path)
        except files.Unreadable:
            return self.issue(
                "include-outside-repository",
                f"include {target!r} leaves the repository",
                name,
                line,
            )
        if not path.is_file():
            return self.issue(
                "include-missing",
                f"included file {target!r} does not exist",
                name,
                line,
            )
        self.parse(path, constraint=constraint, stack=stack)

    def add(self, requirement, name: str, constraint: bool):
        if not requirement.name:
            return
        link = requirement.link.url if requirement.link else None
        if link:
            source = url_source(link)
        elif requirement.is_local_path:
            source = "path"
        else:
            source = "editable" if requirement.is_editable else "registry"
        specifier = (
            canonical(str(requirement.specifier)) if requirement.specifier else ""
        )
        req = requirement.req
        self.dependencies.append(
            Dependency(
                name=canonicalize_name(requirement.name),
                declared=str(req) if req else (requirement.line or "").strip(),
                specifier=specifier,
                marker=str(requirement.marker) if requirement.marker else None,
                extras=tuple(sorted(req.extras)) if req else (),
                direct=not constraint,
                constraint_only=constraint,
                source=source,
                pins=classify(str(requirement.specifier))
                if requirement.specifier
                else (),
                format="requirements",
                location=Location(file=name, line=requirement.line_number),
            )
        )
