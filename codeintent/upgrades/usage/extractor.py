"""Find where a repository's Python code uses a library, with LibCST (MIT/PSF) scope metadata.

Imports, attribute chains, calls with their keyword arguments, module-level aliases, local subclasses
(including ``**kwargs`` forwarded to ``super().__init__``) and instances stored in variables or ``self``
attributes are resolved to the library's qualified names. Nothing is imported or executed; patterns that
cannot be followed statically are reported as unchecked.
"""

from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from importlib.metadata import version as _package_version
from pathlib import Path

import libcst as cst
from libcst.metadata import (
    MetadataWrapper,
    PositionProvider,
    QualifiedNameProvider,
    QualifiedNameSource,
)
from pydantic import ValidationError

from codeintent.upgrades import artifacts, cache
from codeintent.upgrades.manifests import files
from codeintent.upgrades.models import Location, Unchecked, Usage, UsageScan

# Bump whenever anything that changes extracted records changes (FileScan, _Prepass, helpers, models):
# it is part of every per-file cache key, so old cached results stop being used.
EXTRACTOR_VERSION = 3
LIBCST_VERSION = _package_version("libcst")
# Below this many files to parse, a process pool costs more to start than it saves.
MIN_PARALLEL_FILES = 8

SKIP_DIRS = {
    ".git",
    ".hg",
    ".venv",
    "venv",
    "env",
    ".tox",
    ".nox",
    "node_modules",
    "site-packages",
    "build",
    "dist",
    "__pycache__",
    ".mypy_cache",
    ".eggs",
}
IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError"}
BROAD_ERRORS = {"Exception", "BaseException"}
MAX_DEPTH = 8


def _value(item):
    return item() if callable(item) else item


def _dotted(node) -> str | None:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr.value}" if base else None
    return None


def _is_type_checking(test) -> bool:
    return (_dotted(test) or "").split(".")[-1] == "TYPE_CHECKING"


def _literal(node) -> str | None:
    if isinstance(node, cst.SimpleString):
        value = node.evaluated_value
        return value if isinstance(value, str) else None
    return None


def instance_key(qualified: str) -> str:
    if ".<locals>.self." in qualified:
        scope, attribute = qualified.split(".<locals>.self.", 1)
        return f"{scope.rsplit('.', 1)[0]}#self.{attribute}"
    return qualified


@dataclass(frozen=True)
class Init:
    params: frozenset[str]
    forwards: bool


@dataclass(frozen=True)
class LocalClass:
    node: cst.ClassDef
    init: Init | None


class _Calls(cst.CSTVisitor):
    def __init__(self):
        self.calls: list[cst.Call] = []

    def visit_Call(self, node: cst.Call):
        self.calls.append(node)


def _init(cls: cst.ClassDef) -> Init | None:
    for statement in cls.body.body:
        if (
            isinstance(statement, cst.FunctionDef)
            and statement.name.value == "__init__"
        ):
            params = statement.params
            named = {
                p.name.value
                for p in (*params.posonly_params, *params.params, *params.kwonly_params)
            }
            star = params.star_kwarg.name.value if params.star_kwarg else None
            visitor = _Calls()
            statement.body.visit(visitor)
            forwards = star is not None and any(
                isinstance(call.func, cst.Attribute)
                and call.func.attr.value == "__init__"
                and any(
                    a.star == "**"
                    and isinstance(a.value, cst.Name)
                    and a.value.value == star
                    for a in call.args
                )
                for call in visitor.calls
            )
            return Init(frozenset(named - {"self"}), forwards)
    return None


class FileScan(cst.CSTVisitor):
    def __init__(self, module: cst.Module, file: str, modules: tuple[str, ...]):
        super().__init__()
        self.file, self.modules = file, modules
        self.wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
        self.names = self.wrapper.resolve(QualifiedNameProvider)
        self.positions = self.wrapper.resolve(PositionProvider)
        self.aliases: dict[str, list[cst.BaseExpression]] = {}
        self.classes: dict[str, LocalClass] = {}
        self.instances: dict[str, set[str]] = {}
        self.guards: list[tuple[int, int, str]] = []
        self.fallbacks: set[str] = set()
        self.usages: dict[tuple, Usage] = {}
        self.unchecked: list[Unchecked] = []
        self.covered: set[int] = set()
        self.annotation = 0
        self.collect(self.wrapper.module.body, type_checking=False)
        self.wrapper.module.visit(_Prepass(self))
        self.wrapper.module.visit(self)

    def library(self, name: str) -> bool:
        return any(name == m or name.startswith(m + ".") for m in self.modules)

    def location(self, node) -> Location:
        start = _value(self.positions[node]).start
        return Location(file=self.file, line=start.line, column=start.column)

    def guard(self, line: int):
        inside = [g for g in self.guards if g[0] <= line <= g[1]]
        return min(inside, key=lambda g: g[1] - g[0])[2] if inside else None

    def emit(self, node, symbol: str, kind: str, **extra):
        location = self.location(node)
        root = node.func if isinstance(node, cst.Call) else node
        while isinstance(root, (cst.Attribute, cst.Call)):
            root = root.value if isinstance(root, cst.Attribute) else root.func
        fallback = isinstance(root, cst.Name) and root.value in self.fallbacks
        usage = Usage(
            symbol=symbol,
            kind=kind,
            guard="import-error" if fallback else self.guard(location.line),
            location=location,
            **extra,
        )
        self.usages.setdefault(
            (symbol, kind, location.line, location.column, usage.via), usage
        )

    def skip(self, node, reason: str, detail: str, symbol: str | None = None):
        self.unchecked.append(
            Unchecked(
                reason=reason,
                detail=detail,
                location=self.location(node),
                symbol=symbol,
            )
        )

    def collect(self, body, type_checking: bool):
        for statement in body:
            if isinstance(statement, cst.ClassDef):
                self.classes[statement.name.value] = LocalClass(
                    statement, _init(statement)
                )
            elif isinstance(statement, cst.SimpleStatementLine):
                for small in statement.body:
                    target = value = None
                    if isinstance(small, cst.Assign) and len(small.targets) == 1:
                        target, value = small.targets[0].target, small.value
                    elif isinstance(small, cst.AnnAssign) and small.value is not None:
                        target, value = small.target, small.value
                    if isinstance(target, cst.Name) and not type_checking:
                        self.aliases.setdefault(target.value, []).append(value)
            elif isinstance(statement, cst.If):
                self.collect(
                    statement.body.body,
                    type_checking or _is_type_checking(statement.test),
                )
                branch = statement.orelse
                while branch is not None:
                    self.collect(branch.body.body, type_checking)
                    branch = branch.orelse if isinstance(branch, cst.If) else None
            elif isinstance(statement, cst.Try):
                for block in (statement.body, statement.orelse, statement.finalbody):
                    if block is not None:
                        self.collect(
                            block.body
                            if isinstance(block, cst.IndentedBlock)
                            else block.body.body,
                            type_checking,
                        )
                for handler in statement.handlers:
                    self.collect(handler.body.body, type_checking)

    def resolve(self, node, depth: int = 0) -> set[tuple[str, str]]:
        if depth > MAX_DEPTH:
            return set()
        if isinstance(node, cst.BooleanOperation):
            return self.resolve(node.left, depth + 1) | self.resolve(
                node.right, depth + 1
            )
        found = set()
        for name in _value(self.names.get(node, ())) or ():
            if name.source is QualifiedNameSource.IMPORT and self.library(name.name):
                found.add(("library", name.name))
            elif name.source is QualifiedNameSource.LOCAL:
                if name.name in self.classes:
                    found.add(("local", name.name))
                for value in self.aliases.get(name.name, ()):
                    found |= self.resolve(value, depth + 1)
        return found

    def class_targets(self, local: str, seen: frozenset[str] = frozenset()) -> set[str]:
        if local in seen:
            return set()
        targets = set()
        for base in self.classes[local].node.bases:
            for kind, name in self.resolve(base.value):
                targets |= (
                    {name}
                    if kind == "library"
                    else self.class_targets(name, seen | {local})
                )
        return targets

    def created(self, node) -> set[str]:
        if isinstance(node, cst.BooleanOperation):
            return self.created(node.left) | self.created(node.right)
        if isinstance(node, cst.IfExp):
            return self.created(node.body) | self.created(node.orelse)
        if isinstance(node, cst.Call):
            classes = set()
            for kind, name in self.resolve(node.func):
                classes |= {name} if kind == "library" else self.class_targets(name)
            return classes
        return set()

    def held(self, node) -> set[str]:
        classes = set()
        for name in _value(self.names.get(node, ())) or ():
            if name.source is QualifiedNameSource.LOCAL:
                classes |= self.instances.get(instance_key(name.name), set())
        return classes

    def flow(
        self,
        node,
        local: str,
        keywords,
        positional: int,
        via: tuple[str, ...],
        star: bool,
        seen=frozenset(),
    ):
        if local in seen:
            return
        info, via = self.classes[local], via + (local,)
        if info.init is not None:
            if not info.init.forwards:
                return
            keywords, positional = (
                tuple(k for k in keywords if k not in info.init.params),
                0,
            )
        for base in info.node.bases:
            for kind, name in self.resolve(base.value):
                if kind == "library":
                    self.call(node, name, keywords, positional, via, star)
                else:
                    self.flow(
                        node, name, keywords, positional, via, star, seen | {local}
                    )

    def call(self, node, symbol: str, keywords, positional: int, via, star: bool):
        self.emit(
            node,
            symbol,
            "call",
            keywords=tuple(keywords),
            positional=positional,
            via=via,
        )
        if star:
            self.skip(
                node,
                "kwargs-passthrough",
                f"keyword arguments reach {symbol} through ** unpacking",
                symbol,
            )

    def visit_Import(self, node: cst.Import):
        for alias in node.names:
            name = _dotted(alias.name)
            if name and self.library(name):
                self.emit(node, name, "import")
        return False

    def visit_ImportFrom(self, node: cst.ImportFrom):
        module = _dotted(node.module) if node.module else None
        if node.relative or not module or not self.library(module):
            return False
        if isinstance(node.names, cst.ImportStar):
            self.skip(
                node,
                "star-import",
                f"from {module} import * hides which names are used",
            )
        else:
            for alias in node.names:
                self.emit(alias, f"{module}.{_dotted(alias.name)}", "import")
        return False

    def visit_Annotation(self, node):
        self.annotation += 1

    def leave_Annotation(self, node):
        self.annotation -= 1

    def visit_Call(self, node: cst.Call):
        keywords = tuple(a.keyword.value for a in node.args if a.keyword)
        positional = sum(1 for a in node.args if a.keyword is None and not a.star)
        star = any(a.star == "**" for a in node.args)
        dotted = _dotted(node.func)
        self.dynamic(node, dotted)
        targets = self.resolve(node.func)
        if isinstance(node.func, cst.Attribute):
            targets |= {
                ("library", f"{c}.{node.func.attr.value}")
                for c in self.held(node.func.value)
            }
        for kind, name in targets:
            if kind == "library":
                self.call(node, name, keywords, positional, (), star)
            else:
                self.flow(node, name, keywords, positional, (), star)
        if targets:
            self.covered.add(id(node.func))

    def dynamic(self, node: cst.Call, dotted: str | None):
        first = node.args[0].value if node.args else None
        if (
            dotted in ("importlib.import_module", "import_module", "__import__")
            and first is not None
        ):
            target = _literal(first)
            if target is None:
                self.skip(node, "dynamic-import", "module name is computed at runtime")
            elif self.library(target):
                self.emit(node, target, "import")
        elif dotted == "getattr" and len(node.args) >= 2:
            owners = {n for k, n in self.resolve(node.args[0].value) if k == "library"}
            owners |= self.held(node.args[0].value)
            name = _literal(node.args[1].value)
            for owner in owners:
                if name is None:
                    self.skip(
                        node,
                        "dynamic-attribute",
                        f"attribute of {owner} is chosen at runtime",
                    )
                else:
                    self.emit(node, f"{owner}.{name}", "reference")

    def reference(self, node):
        if id(node) in self.covered:
            return False
        kind = "annotation" if self.annotation else "reference"
        names = [n for k, n in self.resolve(node) if k == "library"]
        if isinstance(node, cst.Attribute):
            names += [f"{c}.{node.attr.value}" for c in self.held(node.value)]
        if names:
            self.emit(node, max(names, key=len), kind)
            return False
        return True

    def visit_Attribute(self, node: cst.Attribute):
        return self.reference(node)

    def visit_Name(self, node: cst.Name):
        return self.reference(node)

    def visit_ClassDef(self, node: cst.ClassDef):
        if node.name.value in self.classes:
            for target in self.class_targets(node.name.value):
                self.emit(node, target, "subclass", via=(node.name.value,))


def _only_raises(body) -> bool:
    return all(
        isinstance(line, cst.SimpleStatementLine)
        and all(isinstance(small, cst.Raise) for small in line.body)
        for line in body
    )


def _bound(body) -> set[str]:
    """Module-level names bound by imports or plain assignments in a block."""
    names = set()
    for line in body:
        for small in (
            getattr(line, "body", ())
            if isinstance(line, cst.SimpleStatementLine)
            else ()
        ):
            if isinstance(small, (cst.Import, cst.ImportFrom)) and not isinstance(
                small.names, cst.ImportStar
            ):
                for alias in small.names:
                    local = alias.asname.name if alias.asname else alias.name
                    dotted = _dotted(local)
                    if dotted:
                        names.add(dotted.split(".")[0])
            elif isinstance(small, cst.Assign):
                names |= {
                    t.target.value
                    for t in small.targets
                    if isinstance(t.target, cst.Name)
                }
            elif isinstance(small, cst.AnnAssign) and isinstance(
                small.target, cst.Name
            ):
                names.add(small.target.value)
    return names


class _Prepass(cst.CSTVisitor):
    """Record guarded regions and which variables or ``self`` attributes hold library instances."""

    def __init__(self, scan: FileScan):
        self.scan = scan

    def region(self, block, label: str):
        span = _value(self.scan.positions[block])
        self.scan.guards.append((span.start.line, span.end.line, label))

    def visit_Try(self, node: cst.Try):
        caught = set()
        for handler in node.handlers:
            if handler.type is None:
                caught.add("Exception")
                continue
            elements = (
                handler.type.elements
                if isinstance(handler.type, cst.Tuple)
                else [handler.type]
            )
            caught |= {
                (_dotted(e.value if isinstance(e, cst.Element) else e) or "").split(
                    "."
                )[-1]
                for e in elements
            }
        if caught & IMPORT_ERRORS:
            handlers = [h.body.body for h in node.handlers]
            if all(_only_raises(body) for body in handlers):
                return
            self.region(node.body, "import-error")
            rebound = {n for body in handlers for n in _bound(body)}
            self.scan.fallbacks |= _bound(node.body.body) & rebound
        elif caught & BROAD_ERRORS:
            self.region(node.body, "broad-exception")

    def visit_If(self, node: cst.If):
        if _is_type_checking(node.test):
            self.region(node.body, "type-checking")

    def bind(self, target, value):
        classes = self.scan.created(value)
        if classes:
            for name in _value(self.scan.names.get(target, ())) or ():
                self.scan.instances.setdefault(instance_key(name.name), set()).update(
                    classes
                )

    def visit_Assign(self, node: cst.Assign):
        for target in node.targets:
            self.bind(target.target, node.value)

    def visit_AnnAssign(self, node: cst.AnnAssign):
        if node.value is not None:
            self.bind(node.target, node.value)

    def visit_WithItem(self, node: cst.WithItem):
        if node.asname is not None:
            self.bind(node.asname.name, node.item)


def _python_files(root: Path):
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = sorted(
            d
            for d in subdirs
            if d not in SKIP_DIRS
            and not d.startswith(".")
            and not d.endswith(".egg-info")
        )
        for name in sorted(names):
            if name.endswith((".py", ".pyi")):
                yield Path(directory) / name


def _scan_text(name: str, text: str, modules: tuple[str, ...]) -> dict:
    """Usages and unchecked records of one file as JSON-ready dicts (process-pool worker; must stay top-level)."""
    try:
        module = cst.parse_module(text)
    except cst.ParserSyntaxError as error:
        found = Unchecked(
            reason="parse-error",
            detail=str(error).splitlines()[0],
            location=Location(file=name, line=error.raw_line),
        )
        return {"usages": [], "unchecked": [found.model_dump(mode="json")]}
    result = FileScan(module, name, modules)
    usages = sorted(
        result.usages.values(),
        key=lambda u: (
            u.location.line or 0,
            u.location.column or 0,
            u.symbol,
            u.kind,
            u.via,
            u.keywords,
        ),
    )
    unchecked = sorted(
        result.unchecked,
        key=lambda u: (
            u.location.line or 0,
            u.location.column or 0,
            u.reason,
            u.detail,
        ),
    )
    return {
        "usages": [u.model_dump(mode="json") for u in usages],
        "unchecked": [u.model_dump(mode="json") for u in unchecked],
    }


def _cache_key(name: str, text: str, modules: tuple[str, ...]) -> str:
    """Digest of everything a file's records depend on: extractor logic, LibCST, path, modules, contents."""
    return cache.digest(
        str(EXTRACTOR_VERSION), LIBCST_VERSION, name, "\0".join(modules), text
    )


def _cache_path(key: str) -> Path:
    return artifacts.CACHE.parent / "usage" / key[:2] / f"{key}.json"


def _workers() -> int:
    configured = os.getenv("CODEINTENT_SCAN_WORKERS")
    if configured:
        try:
            return max(1, int(configured))
        except ValueError:
            pass
    try:
        cpus = len(os.sched_getaffinity(0))
    except AttributeError:
        cpus = os.cpu_count() or 1
    return min(4, cpus)


def _scan_all(jobs: list[tuple[str, str]], modules: tuple[str, ...]) -> list[dict]:
    """``_scan_text`` for every ``(name, text)`` job, in job order; in parallel when it is worth it."""
    workers = min(_workers(), len(jobs))
    if (
        len(jobs) >= MIN_PARALLEL_FILES
        and workers > 1
        and not multiprocessing.current_process().daemon
    ):
        # Largest files first so one big file does not end up last on a single worker.
        order = sorted(range(len(jobs)), key=lambda i: -len(jobs[i][1]))
        try:
            with ProcessPoolExecutor(
                max_workers=workers, mp_context=multiprocessing.get_context("spawn")
            ) as pool:
                futures = {
                    i: pool.submit(_scan_text, jobs[i][0], jobs[i][1], modules)
                    for i in order
                }
                return [futures[i].result() for i in range(len(jobs))]
        except (BrokenProcessPool, OSError, RuntimeError):
            pass  # e.g. no fork/spawn allowed here: fall back to scanning in-process
    return [_scan_text(name, text, modules) for name, text in jobs]


Records = tuple[list[Usage], list[Unchecked]]


def _records(result) -> Records | None:
    """Validated records from a worker result or cache entry; ``None`` if it is malformed."""
    try:
        return (
            [Usage.model_validate(u) for u in result["usages"]],
            [Unchecked.model_validate(u) for u in result["unchecked"]],
        )
    except (KeyError, TypeError, ValidationError):
        return None


def scan(root: Path, modules: tuple[str, ...]) -> UsageScan:
    """Usages of ``modules`` (top-level import names of one distribution) in the repository at ``root``.

    Per-file results are cached on disk by content, so unchanged files are not parsed again; files that do
    need parsing are spread over a process pool (``CODEINTENT_SCAN_WORKERS``). Output order is the sorted
    walk order either way. Callers running this from a script need an ``if __name__ == "__main__"`` guard.
    """
    root = root.resolve()
    # One slot per file in walk order: either ready records or the index of a pending parse job.
    slots: list[Records | int] = []
    keys: list[str] = []
    jobs: list[tuple[str, str]] = []
    count = 0
    for path in _python_files(root):
        name = path.relative_to(root).as_posix()
        try:
            text = files.read(root, path)
        except files.Unreadable as error:
            found = Unchecked(
                reason=error.reason,
                detail=error.detail,
                location=Location(file=name),
            )
            slots.append(([], [found]))
            continue
        if not any(module in text for module in modules):
            continue
        count += 1
        key = _cache_key(name, text, modules)
        cached = cache.read_json(_cache_path(key))
        records = _records(cached) if cached is not None else None
        if records is not None:
            slots.append(records)
            continue
        slots.append(len(jobs))
        keys.append(key)
        jobs.append((name, text))
    fresh = _scan_all(jobs, modules)
    for key, result in zip(keys, fresh):
        cache.write_json(_cache_path(key), result)
    usages: list[Usage] = []
    unchecked: list[Unchecked] = []
    for slot in slots:
        found_usages, found_unchecked = (
            _records(fresh[slot]) if isinstance(slot, int) else slot
        )
        usages.extend(found_usages)
        unchecked.extend(found_unchecked)
    return UsageScan(
        modules=modules, files=count, usages=tuple(usages), unchecked=tuple(unchecked)
    )
