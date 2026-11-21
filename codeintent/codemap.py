"""The code map of one repository: its files, which of them import which, its functions and the calls
between them, its tests and entry points, and every place it uses each of its dependencies.

Structure comes from the standard library's ``ast`` and library uses from the LibCST extractor; nothing is
imported or run. Calls are resolved only where Python makes it statically certain: functions defined in
the same file, names imported from the repository's own modules, ``module.function()`` through an import,
``self.method()`` on the enclosing class, and ``Class()`` to its ``__init__``. Anything else is left out
rather than guessed, so a missing caller is possible but a wrong one is not.

The map is stored per repository in PostgreSQL and projected into the workspace graph, where the PR check
traverses it: ``(:File)-[:IMPORTS]->(:File)``, ``(:File)-[:DEFINES]->(:Function)-[:CALLS]->(:Function)``
and ``(:CodeLine)-[:INSIDE]->(:Function)``.
"""

from __future__ import annotations

import ast
import bisect
import logging
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

import httpx
from packaging.utils import canonicalize_name

from codeintent.upgrades.manifests import files
from codeintent.upgrades.usage import extractor

logger = logging.getLogger(__name__)

VERSION = 1
MAX_FILES = 3000
MAX_FUNCTIONS = 30_000
MAX_CALLS = 60_000
MAX_USES = 20_000
MAX_RESOLVED = 12
"""At most this many distributions are downloaded to learn their import names, per map."""

# Distributions whose import name is not their normalised project name.
ALIASES = {
    "pyyaml": ("yaml",),
    "beautifulsoup4": ("bs4",),
    "pillow": ("PIL",),
    "scikit-learn": ("sklearn",),
    "scikit-image": ("skimage",),
    "python-dateutil": ("dateutil",),
    "python-dotenv": ("dotenv",),
    "python-multipart": ("multipart",),
    "python-jose": ("jose",),
    "pyjwt": ("jwt",),
    "opencv-python": ("cv2",),
    "opencv-python-headless": ("cv2",),
    "protobuf": ("google.protobuf",),
    "attrs": ("attr", "attrs"),
    "psycopg2-binary": ("psycopg2",),
    "psycopg-binary": ("psycopg",),
    "pymysql": ("pymysql",),
    "mysqlclient": ("MySQLdb",),
    "msgpack-python": ("msgpack",),
    "pyzmq": ("zmq",),
    "pygithub": ("github",),
    "gitpython": ("git",),
    "typing-extensions": ("typing_extensions",),
    "importlib-metadata": ("importlib_metadata",),
    "setuptools": ("setuptools", "pkg_resources"),
    "google-cloud-storage": ("google.cloud.storage",),
    "google-api-python-client": ("googleapiclient",),
    "discord-py": ("discord",),
    "faiss-cpu": ("faiss",),
    "tree-sitter": ("tree_sitter",),
}
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
ROUTE_ANY = {"route", "api_route", "websocket"}
COMMANDS = {"command", "group", "callback"}
TASKS = {"task", "shared_task", "periodic_task", "job"}
ENTRY_FILES = {"__main__.py", "manage.py", "wsgi.py", "asgi.py"}


def is_test(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return (
        any(p in ("tests", "test", "testing") for p in parts[:-1])
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _modules(paths: list[str]) -> dict[str, str]:
    """Dotted module name -> file, for every Python file.

    A file is named from the topmost folder above it that is still a package (has ``__init__.py``), so
    ``src/app/client.py`` is ``app.client``. Its full path is registered too (``src.app.client``) for
    projects that import that way. The first file to claim a name keeps it.
    """
    present = set(paths)
    names: dict[str, str] = {}
    for path in paths:
        parts = path[: -len(Path(path).suffix)].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        start = len(parts) - 1
        while start > 0 and "/".join(parts[:start]) + "/__init__.py" in present:
            start -= 1
        for name in (".".join(parts[start:]), ".".join(parts)):
            if name:
                names.setdefault(name, path)
    return names


def _package_of(module: str, is_init: bool) -> str:
    return module if is_init else module.rpartition(".")[0]


def _dotted(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _entry(decorators: list[ast.expr]) -> str | None:
    """``GET /users`` for a route handler, ``command`` or ``task`` for CLI commands and queued jobs."""
    for decorator in decorators:
        call = decorator if isinstance(decorator, ast.Call) else None
        target = call.func if call else decorator
        attr = (
            target.attr
            if isinstance(target, ast.Attribute)
            else target.id
            if isinstance(target, ast.Name)
            else None
        )
        if not attr:
            continue
        path = None
        if call and call.args and isinstance(call.args[0], ast.Constant):
            if isinstance(call.args[0].value, str):
                path = call.args[0].value
        if attr in ROUTE_METHODS and path is not None:
            return f"{attr.upper()} {path}"
        if attr in ROUTE_ANY and path is not None:
            return f"route {path}"
        if attr in COMMANDS and isinstance(target, ast.Attribute):
            return "command"
        if attr in TASKS:
            return "task"
    return None


class _File(ast.NodeVisitor):
    """One pass over a file: its definitions, imports and the raw calls inside each function."""

    def __init__(self, module: str, is_init: bool):
        self.module = module
        self.package = _package_of(module, is_init)
        self.stack: list[str] = []
        self.classes: list[str] = []
        self.functions: list[dict] = []
        self.methods: dict[str, set[str]] = defaultdict(set)
        self.top: set[str] = set()
        self.top_classes: set[str] = set()
        # name -> ("module", dotted) or ("symbol", module, attribute)
        self.bindings: dict[str, tuple] = {}
        self.imports: list[tuple[str, int]] = []  # (dotted module or module.name, line)
        self.calls: list[
            tuple[str, str, int]
        ] = []  # (caller qualname, callee expression, line)
        self.main = False

    def _absolute(self, module: str | None, level: int) -> str | None:
        if not level:
            return module
        base = self.package.split(".") if self.package else []
        if level - 1 > len(base):
            return None
        base = base[: len(base) - (level - 1)]
        return ".".join([*base, module] if module else base) or None

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append((alias.name, node.lineno))
            if alias.asname:
                self.bindings[alias.asname] = ("module", alias.name)
            else:
                head = alias.name.split(".")[0]
                self.bindings[head] = ("module", head)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        base = self._absolute(node.module, node.level)
        if not base:
            return
        for alias in node.names:
            if alias.name == "*":
                self.imports.append((base, node.lineno))
                continue
            self.imports.append((f"{base}.{alias.name}", node.lineno))
            self.bindings[alias.asname or alias.name] = ("symbol", base, alias.name)

    def visit_ClassDef(self, node: ast.ClassDef):
        if not self.stack:
            self.top_classes.add(node.name)
        self.stack.append(node.name)
        self.classes.append(".".join(self.stack))
        self.generic_visit(node)
        self.stack.pop()

    def _function(self, node):
        qual = ".".join([*self.stack, node.name])
        if not self.stack:
            self.top.add(node.name)
        elif ".".join(self.stack) in self.classes:
            self.methods[".".join(self.stack)].add(node.name)
        self.functions.append(
            {
                "name": qual,
                "line": node.lineno,
                "end": getattr(node, "end_lineno", None) or node.lineno,
                "entry": _entry(node.decorator_list),
                "cls": ".".join(self.stack)
                if ".".join(self.stack) in self.classes
                else None,
            }
        )
        self.stack.append(node.name)
        for child in node.body:
            self._calls(child, qual)
        self.stack.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def _calls(self, node, caller: str):
        """Calls in a function body; nested definitions are visited as functions of their own."""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.visit(node)
            return
        for child in ast.iter_child_nodes(node):
            self._calls(child, caller)
        if isinstance(node, ast.Call):
            target = _dotted(node.func)
            if target:
                self.calls.append((caller, target, node.lineno))

    def visit_If(self, node: ast.If):
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
        ):
            self.main = True
        self.generic_visit(node)


def _scripts(root: Path) -> set[str]:
    """Modules named by ``[project.scripts]`` in any pyproject.toml (``pkg.cli:main`` -> ``pkg.cli``)."""
    found: set[str] = set()
    for path in root.rglob("pyproject.toml"):
        if any(p in extractor.SKIP_DIRS for p in path.relative_to(root).parts):
            continue
        try:
            data = tomllib.loads(files.read(root, path))
        except (files.Unreadable, tomllib.TOMLDecodeError, OSError):
            continue
        for target in ((data.get("project") or {}).get("scripts") or {}).values():
            if isinstance(target, str):
                found.add(target.split(":")[0].strip())
    return found


def _import_names(
    dependencies: dict[str, str | None],
    external: set[str],
    client: httpx.Client | None,
) -> dict[str, tuple[str, ...]]:
    """Import names of each dependency the code imports, matched to the top-level modules it imports."""
    from codeintent.upgrades.usage.distributions import import_names

    found: dict[str, tuple[str, ...]] = {}
    for name in dependencies:
        key = canonicalize_name(name)
        candidates = ALIASES.get(key, ()) + (key.replace("-", "_"),)
        if key.startswith("python-"):
            candidates += (key[7:].replace("-", "_"),)
        matched = tuple(c for c in candidates if c.split(".")[0] in external)
        if matched:
            found[key] = matched
    unmatched = external - {m.split(".")[0] for ms in found.values() for m in ms}
    if not (client and unmatched):
        return found
    resolved = 0
    for name, version in dependencies.items():
        key = canonicalize_name(name)
        if key in found or not version or resolved >= MAX_RESOLVED:
            continue
        resolved += 1
        try:
            names = import_names(name, version, client)
        except Exception as error:
            logger.info("No import names for %s (%s)", name, type(error).__name__)
            continue
        matched = tuple(n for n in names if n.split(".")[0] in unmatched)
        if matched:
            found[key] = matched
    return found


def build(
    root: Path,
    dependencies: dict[str, str | None],
    client: httpx.Client | None = None,
) -> dict:
    """The code map of the repository at ``root``; ``dependencies`` maps each package to its version."""
    root = root.resolve()
    paths: list[str] = []
    texts: dict[str, str] = {}
    for path in extractor._python_files(root):
        if path.suffix != ".py":
            continue
        name = path.relative_to(root).as_posix()
        try:
            texts[name] = files.read(root, path)
        except files.Unreadable:
            continue
        paths.append(name)
        if len(paths) == MAX_FILES:
            break
    truncated = len(paths) == MAX_FILES
    modules = _modules(paths)
    module_of = {path: name for name, path in reversed(list(modules.items()))}
    scripts = _scripts(root)
    parsed: dict[str, _File] = {}
    for path in paths:
        visitor = _File(module_of.get(path, ""), path.endswith("__init__.py"))
        try:
            visitor.visit(ast.parse(texts[path], filename=path))
        except (SyntaxError, ValueError, RecursionError):
            continue
        parsed[path] = visitor
    local_tops = {name.split(".")[0] for name in modules}
    stdlib = set(sys.stdlib_module_names)

    def local(dotted: str) -> tuple[str, str] | None:
        """(file, rest) for the longest module prefix of ``dotted`` defined in the repository."""
        parts = dotted.split(".")
        for cut in range(len(parts), 0, -1):
            path = modules.get(".".join(parts[:cut]))
            if path:
                return path, ".".join(parts[cut:])
        return None

    out_files, imports, external_by_file = [], [], defaultdict(set)
    functions: list[dict] = []
    defined: dict[str, dict[str, str]] = {}
    for path, f in parsed.items():
        name = Path(path).name
        module = module_of.get(path, "")
        out_files.append(
            {
                "path": path,
                "module": module,
                "test": is_test(path),
                "entry": bool(name in ENTRY_FILES or f.main or module in scripts),
                "lines": texts[path].count("\n") + 1,
            }
        )
        seen = set()
        for dotted, line in f.imports:
            hit = local(dotted)
            top = dotted.split(".")[0]
            if hit and hit[0] != path:
                if hit[0] not in seen:
                    seen.add(hit[0])
                    imports.append({"file": path, "target": hit[0], "line": line})
            elif not hit and top not in stdlib and top not in local_tops and top:
                external_by_file[path].add(top)
        ids = defined.setdefault(path, {})
        for fn in f.functions:
            if len(functions) == MAX_FUNCTIONS:
                truncated = True
                break
            ident = f"{path}:{fn['name']}"
            ids[fn["name"]] = ident
            functions.append({"id": ident, "file": path, **fn})

    def callee(f: _File, path: str, caller: str, target: str) -> str | None:
        ids = defined.get(path, {})
        head, _, rest = target.partition(".")
        if head == "self" and rest and "." not in rest:
            cls = next((fn["cls"] for fn in f.functions if fn["name"] == caller), None)
            if cls and rest in f.methods.get(cls, ()):
                return ids.get(f"{cls}.{rest}")
            return None
        if head in f.top and not rest:
            return ids.get(head)
        if head in f.top_classes:
            return ids.get(f"{target}.__init__" if not rest else target) or (
                ids.get(f"{head}.__init__") if not rest else None
            )
        binding = f.bindings.get(head)
        if not binding:
            return None
        if binding[0] == "module":
            hit = local(binding[1] + (f".{rest}" if rest else ""))
        else:
            _, module, attr = binding
            hit = local(f"{module}.{attr}" + (f".{rest}" if rest else ""))
        if not hit or not hit[1]:
            return None
        there = defined.get(hit[0], {})
        return there.get(hit[1]) or there.get(f"{hit[1]}.__init__")

    calls, seen_calls = [], set()
    for path, f in parsed.items():
        ids = defined.get(path, {})
        for caller, target, line in f.calls:
            source = ids.get(caller)
            found = source and callee(f, path, caller, target)
            if not found or found == source or (source, found) in seen_calls:
                continue
            seen_calls.add((source, found))
            calls.append({"caller": source, "callee": found, "line": line})
            if len(calls) == MAX_CALLS:
                truncated = True
                break

    external = set().union(*external_by_file.values()) if external_by_file else set()
    packages = _import_names(dependencies, external, client)
    uses: dict[str, list[dict]] = {}
    if packages:
        owner = {
            module: package for package, names in packages.items() for module in names
        }
        ranges: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
        for fn in functions:
            ranges[fn["file"]].append((fn["line"], fn["end"], fn["id"]))
        starts = {k: [r[0] for r in sorted(v)] for k, v in ranges.items()}
        ranges = {k: sorted(v) for k, v in ranges.items()}

        def inside(file: str, line: int | None) -> str | None:
            """The innermost function containing ``line``."""
            if not line or file not in ranges:
                return None
            best = None
            for start, end, ident in ranges[file][
                : bisect.bisect_right(starts[file], line)
            ]:
                if start <= line <= end:
                    best = ident
            return best

        scan = extractor.scan(root, tuple(sorted(owner)))
        count = 0
        for usage in scan.usages:
            module = next(
                (
                    m
                    for m in sorted(owner, key=len, reverse=True)
                    if usage.symbol == m or usage.symbol.startswith(m + ".")
                ),
                None,
            )
            if module is None or not usage.location.file:
                continue
            uses.setdefault(owner[module], []).append(
                {
                    "symbol": usage.symbol,
                    "kind": usage.kind,
                    "keywords": list(usage.keywords),
                    "file": usage.location.file,
                    "line": usage.location.line,
                    "function": inside(usage.location.file, usage.location.line),
                }
            )
            count += 1
            if count == MAX_USES:
                truncated = True
                break
    matched = {m.split(".")[0] for names in packages.values() for m in names}
    return {
        "version": VERSION,
        "files": out_files,
        "imports": imports,
        "functions": [
            {k: fn[k] for k in ("id", "file", "name", "line", "end", "entry")}
            for fn in functions
        ],
        "calls": calls,
        "packages": {k: list(v) for k, v in packages.items()},
        "uses": uses,
        "unmatched": sorted(external - matched),
        "truncated": truncated,
    }


def dependencies_of(root: Path) -> dict[str, str | None]:
    """Every registry package the repository declares or locks, with its exact version where known."""
    from codeintent.upgrades import manifests
    from codeintent.upgrades.upcoming import _exact

    found: dict[str, str | None] = {}
    for project in [root, *_nested(root)]:
        for d in manifests.scan(project).dependencies:
            if d.source != "registry":
                continue
            key = canonicalize_name(d.name)
            version = _exact(d)
            if version or key not in found:
                found[key] = version or found.get(key)
    return found


def _nested(root: Path) -> list[Path]:
    """Folders below the root holding their own Python project (monorepos)."""
    out = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if len(rel.parts) > 3 or any(
            p in extractor.SKIP_DIRS or p.startswith(".") for p in rel.parts
        ):
            continue
        if path.is_file() and path.name in (
            "pyproject.toml",
            "requirements.txt",
            "uv.lock",
            "poetry.lock",
        ):
            if path.parent != root and path.parent not in out:
                out.append(path.parent)
    return out
