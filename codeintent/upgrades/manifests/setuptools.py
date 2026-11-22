"""``setup.cfg`` and ``setup.py``, read statically. ``setup.py`` is parsed, never executed."""

from __future__ import annotations

import ast
import re

from packaging.utils import canonicalize_name

from codeintent.upgrades.manifests.common import pep508
from codeintent.upgrades.models import Dependency, Issue, Location

_SECTION = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
_KEY = re.compile(r"^(?P<key>[A-Za-z0-9_.\-]+)\s*[=:]\s*(?P<value>.*)$")


class Collected:
    def __init__(self, file: str):
        self.file = file
        self.dependencies: list[Dependency] = []
        self.issues: list[Issue] = []

    def issue(self, reason: str, detail: str, line: int | None = None):
        self.issues.append(
            Issue(
                reason=reason,
                detail=detail,
                location=Location(file=self.file, line=line),
            )
        )

    def add(self, text: str, group: str, line: int | None, format):
        record = pep508(text, format=format, file=self.file, line=line, group=group)
        (self.issues if isinstance(record, Issue) else self.dependencies).append(record)


def setup_cfg(text: str, file: str) -> Collected:
    out = Collected(file)
    section = key = None
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        header = _SECTION.match(raw)
        if header:
            section, key = header["name"].strip(), None
            continue
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if not raw[0].isspace():
            match = _KEY.match(raw)
            key = match["key"] if match else None
            value = match["value"].strip() if match else ""
        else:
            value = stripped
        group = None
        if section == "options" and key == "install_requires":
            group = "main"
        elif section == "options.extras_require" and key:
            group = f"optional:{canonicalize_name(key)}"
        if group and value:
            if value.startswith(("file:", "attr:")):
                out.issue(
                    "non-literal-setup-argument",
                    f"{key} uses the {value.split(':')[0]}: directive",
                    number,
                )
            else:
                out.add(value, group, number, "setup.cfg")
    return out


def _literal_strings(node, assignments) -> list[ast.Constant] | None:
    if isinstance(node, ast.Name) and node.id in assignments:
        node = assignments[node.id]
    if isinstance(node, (ast.List, ast.Tuple)) and all(
        isinstance(item, ast.Constant) and isinstance(item.value, str)
        for item in node.elts
    ):
        return list(node.elts)
    return None


def setup_py(text: str, file: str) -> Collected:
    out = Collected(file)
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        out.issue("invalid-python", str(error), error.lineno)
        return out
    assignments = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            assignments[node.targets[0].id] = node.value
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            getattr(node.func, "id", None) == "setup"
            or getattr(node.func, "attr", None) == "setup"
        )
    ]
    for call in calls:
        for keyword in call.keywords:
            if keyword.arg == "install_requires":
                _collect(out, keyword.value, "main", assignments)
            elif keyword.arg == "extras_require":
                value = assignments.get(
                    getattr(keyword.value, "id", None), keyword.value
                )
                if not isinstance(value, ast.Dict):
                    out.issue(
                        "non-literal-setup-argument",
                        "extras_require is not a literal dict",
                        keyword.value.lineno,
                    )
                    continue
                for name, items in zip(value.keys, value.values, strict=True):
                    if isinstance(name, ast.Constant) and isinstance(name.value, str):
                        _collect(
                            out,
                            items,
                            f"optional:{canonicalize_name(name.value)}",
                            assignments,
                        )
                    else:
                        out.issue(
                            "non-literal-setup-argument",
                            "extras_require key is not a literal",
                            value.lineno,
                        )
    return out


def _collect(out: Collected, node, group: str, assignments):
    items = _literal_strings(node, assignments)
    if items is None:
        return out.issue(
            "non-literal-setup-argument",
            f"{group} requirements are computed at build time",
            node.lineno,
        )
    for item in items:
        out.add(item.value.strip(), group, item.lineno, "setup.py")
    return None
