"""Static API model of a released library version, compared from the consumer's side.

Each version is loaded with griffe (ISC) in static mode only (``allow_inspection=False``): source and stub
files are parsed, never imported. Every symbol a consumer uses is resolved in both versions, including
non-public aliases, and the call's keyword and positional arguments are checked against both signatures.
Absence is only reported when nothing could still provide the name at run time; otherwise the usage is
returned as unchecked with the reason.
"""

from __future__ import annotations

import ast
import importlib
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import griffe
import httpx

from codeintent.upgrades import artifacts
from codeintent.upgrades.models import APIChange, Location, Unchecked, Usage, UsageCheck
from codeintent.upgrades.usage.distributions import _packages, _source_root

logging.getLogger("griffe").setLevel(logging.ERROR)

COMPILED = (".so", ".pyd")
BENIGN_DECORATORS = {
    "abstractmethod",
    "cache",
    "cached_property",
    "classmethod",
    "final",
    "lru_cache",
    "override",
    "property",
    "setter",
    "staticmethod",
}
QUOTED = re.compile(r"['`\"]([A-Za-z_][\w.]*)['`\"]")
DEPRECATION = re.compile(r"Deprecat|FutureWarning|Removed\w*Warning")


@dataclass(frozen=True)
class Found:
    obj: griffe.Object | None
    path: str
    external: str | None = None
    rest: tuple[str, ...] = ()


@dataclass(frozen=True)
class Missing:
    parent: griffe.Object
    path: str


@dataclass(frozen=True)
class Shimmed:
    """Only provided by a module ``__getattr__`` that warns it is deprecated."""

    path: str
    message: str
    shim: griffe.Object


@dataclass(frozen=True)
class Unknown:
    reason: str
    detail: str


@dataclass
class Signature:
    names: dict[str, griffe.Parameter]
    positional: list[str]
    var_positional: bool
    var_keyword: bool
    owner: griffe.Object


@dataclass(frozen=True)
class Warning_:
    message: str
    parameters: frozenset[str] = field(default_factory=frozenset)


class Surface:
    """One released version of a distribution, loaded lazily per top-level module."""

    def __init__(self, root: Path, modules: tuple[str, ...], version: str = ""):
        self.root = root
        self.version = version
        self.modules = tuple(sorted(modules, key=len, reverse=True))
        self._collection = griffe.ModulesCollection()
        self._loaded: dict[str, griffe.Module | None] = {}
        self._tries: dict[str, dict[str, list]] = {}

    @classmethod
    def fetch(cls, package: str, version: str, client: httpx.Client) -> Surface:
        root = _source_root(artifacts.fetch(package, version, client))
        return cls(root, tuple(dict.fromkeys(_packages(root))), version)

    def module(self, name: str) -> griffe.Module | None:
        if name not in self._loaded:
            try:
                self._loaded[name] = griffe.load(
                    name,
                    search_paths=[self.root],
                    modules_collection=self._collection,
                    allow_inspection=False,
                    force_inspection=False,
                    resolve_aliases=True,
                    resolve_implicit=True,
                    resolve_external=False,
                )
            except (ImportError, OSError, SyntaxError, griffe.GriffeError):
                self._loaded[name] = None
        return self._loaded[name]

    def location(self, obj: griffe.Object | griffe.Alias) -> Location | None:
        path = obj.filepath if not isinstance(obj.filepath, list) else None
        if path is None:
            return None
        try:
            file = str(Path(path).relative_to(self.root))
        except ValueError:
            file = Path(path).name
        return Location(file=file, line=obj.lineno)

    def lookup(
        self, symbol: str, depth: int = 0
    ) -> Found | Missing | Shimmed | Unknown:
        root = next(
            (m for m in self.modules if symbol == m or symbol.startswith(m + ".")), None
        )
        if root is None:
            return Unknown("not-in-distribution", f"{symbol} is outside this release")
        obj: griffe.Object | None = self.module(root)
        if obj is None:
            return Unknown("load-error", f"{root} could not be read statically")
        parts = symbol[len(root) + 1 :].split(".") if symbol != root else []
        for index, part in enumerate(parts):
            if obj.is_attribute or obj.is_function:
                return self._follow(obj, tuple(parts[index:]), depth)
            member = (obj.all_members if obj.is_class else obj.members).get(part)
            if member is None:
                return self._missing(obj, part)
            primary = self._primary(obj, member, part) if obj.is_module else None
            if isinstance(primary, Unknown):
                return primary
            rest = tuple(parts[index + 1 :])
            if primary is not None and not self._inside(primary):
                return Found(None, member.path, external=primary, rest=rest)
            if primary is not None:
                preferred = self.lookup(".".join((primary, *rest)), depth + 1)
                if not _accelerator(preferred):
                    return preferred
            if member.is_alias:
                try:
                    member = member.final_target
                except (griffe.AliasResolutionError, griffe.CyclicAliasError):
                    target = member.target_path
                    if self._inside(target) and target != member.path and depth < 6:
                        return self.lookup(
                            ".".join((target, *parts[index + 1 :])), depth + 1
                        )
                    return Found(
                        None,
                        member.path,
                        external=member.target_path,
                        rest=tuple(parts[index + 1 :]),
                    )
            obj = member
        return self._follow(obj, (), depth)

    def _follow(
        self, obj: griffe.Object, rest: tuple[str, ...], depth: int
    ) -> Found | Missing | Unknown:
        """Follow ``name = other.name`` assignments (which griffe keeps as attributes) and,
        for attributes read from a call's result, the function's declared return type."""
        if depth > 4:
            return Found(obj, obj.path, rest=rest)
        if obj.is_function and rest:
            target = self._annotation_class(obj.returns, obj.parent)
            if target is None and obj.returns is None:
                target = self._returned_class(obj)
        else:
            value = obj.value if obj.is_attribute else None
            is_name = isinstance(value, (griffe.ExprName, griffe.ExprAttribute))
            target = value.canonical_path if is_name else None
        if target is None or target == obj.path:
            return Found(obj, obj.path, rest=rest)
        if self._inside(target):
            return self.lookup(".".join((target, *rest)), depth + 1)
        return Found(None, obj.path, external=target, rest=rest)

    def _returned_class(self, function: griffe.Object) -> str | None:
        """For an unannotated function whose every ``return`` constructs the same class in this
        distribution (``return ProxyManager(...)``), that class."""
        tree = self.source(function)
        node = (
            next(
                (
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ),
                None,
            )
            if tree is not None
            else None
        )
        if node is None:
            return None
        returns, stack = [], list(node.body)
        while stack:
            child = stack.pop()
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
            ):
                continue
            if isinstance(child, ast.Return):
                returns.append(child.value)
            stack.extend(ast.iter_child_nodes(child))
        module = function
        while module is not None and not module.is_module:
            module = module.parent
        classes = set()
        for value in returns:
            if not isinstance(value, ast.Call) or module is None:
                return None
            if ast.unparse(value.func).endswith(("raise_from", "reraise")):
                continue
            path = self._name_in(ast.unparse(value.func), module)
            found = self.lookup(path, 5) if path and self._inside(path) else None
            if not (
                isinstance(found, Found)
                and found.obj is not None
                and found.obj.is_class
            ):
                return None
            classes.add(found.obj.path)
        return classes.pop() if len(classes) == 1 else None

    def _fields(self, cls: griffe.Object) -> set[str]:
        """Field names of a class built on ``namedtuple(...)`` or ``typing.NamedTuple(...)``."""
        fields: set[str] = set()
        for base in cls.bases:
            if not isinstance(
                base, griffe.ExprCall
            ) or not base.canonical_path.endswith(("namedtuple", "NamedTuple")):
                continue
            arguments = [
                a for a in base.arguments if not isinstance(a, griffe.ExprKeyword)
            ]
            if len(arguments) < 2:
                continue
            spec = arguments[1]
            if (
                isinstance(spec, (griffe.ExprName, griffe.ExprAttribute))
                and cls.parent is not None
            ):
                held = cls.parent.members.get(str(spec))
                spec = (
                    getattr(held, "value", None)
                    if held is not None and not held.is_alias
                    else None
                )
            try:
                tree = (
                    ast.parse(str(spec), mode="eval").body if spec is not None else None
                )
            except SyntaxError:
                tree = None
            if isinstance(tree, ast.Constant) and isinstance(tree.value, str):
                fields |= set(tree.value.replace(",", " ").split())
            elif isinstance(tree, (ast.List, ast.Tuple)):
                for element in tree.elts:
                    if isinstance(element, (ast.Tuple, ast.List)) and element.elts:
                        element = element.elts[0]
                    if isinstance(element, ast.Constant) and isinstance(
                        element.value, str
                    ):
                        fields.add(element.value)
        return fields

    def _annotation_class(self, expr, scope, depth: int = 0) -> str | None:
        """The one class an annotation names, unwrapping ``Optional``, ``X | None`` and bound TypeVars.

        Containers (``list[X]``) and real unions return None: the attribute isn't on a single known class.
        """
        if expr is None or depth > 3:
            return None
        if isinstance(expr, str):
            return self._name_in(expr.strip("'\""), scope)
        if isinstance(expr, griffe.ExprBinOp) and expr.operator == "|":
            options = [o for o in (expr.left, expr.right) if str(o) != "None"]
            return (
                self._annotation_class(options[0], scope, depth + 1)
                if len(options) == 1
                else None
            )
        if isinstance(expr, griffe.ExprSubscript):
            wrapper = str(getattr(expr.left, "canonical_path", expr.left)).split(".")[
                -1
            ]
            inner = expr.slice
            elements = (
                list(inner.elements) if isinstance(inner, griffe.ExprTuple) else [inner]
            )
            options = [e for e in elements if str(e) != "None"]
            if wrapper == "Annotated":
                options = elements[:1]
            if wrapper in ("Optional", "Union", "Annotated") and len(options) == 1:
                return self._annotation_class(options[0], scope, depth + 1)
            return None
        if not isinstance(expr, (griffe.ExprName, griffe.ExprAttribute)):
            return None
        path = expr.canonical_path
        found = self.lookup(path, 5) if self._inside(path) else None
        value = getattr(getattr(found, "obj", None), "value", None)
        if isinstance(value, griffe.ExprCall) and value.canonical_path.endswith(
            "TypeVar"
        ):
            bound = next(
                (
                    a.value
                    for a in value.arguments
                    if getattr(a, "name", None) == "bound"
                ),
                None,
            )
            return self._annotation_class(bound, found.obj.parent, depth + 1)
        return path

    def _name_in(self, dotted: str, scope) -> str | None:
        """Resolve a dotted name written as a string annotation, from the module or class it appears in."""
        head, _, tail = dotted.partition(".")
        while scope is not None and not scope.is_module and head not in scope.members:
            scope = scope.parent
        member = scope.members.get(head) if scope is not None else None
        if member is None:
            return None
        base = member.target_path if member.is_alias else member.path
        return f"{base}.{tail}" if tail else base

    def _inside(self, path: str) -> bool:
        return any(path == m or path.startswith(m + ".") for m in self.modules)

    def _primary(
        self, module: griffe.Object, member, name: str
    ) -> str | Unknown | None:
        """The ``try`` side of ``try: import name / except ImportError: fallback``, when griffe kept the fallback.

        Only standard-library or same-distribution imports count: a third-party ``try`` side may not be
        installed, so which side runs is unknown and the usage stays unchecked.
        """
        line = member.alias_lineno if member.is_alias else member.lineno
        for target, handlers in self._try_imports(module).get(name, ()):
            if line is None or not any(a <= line <= b for a, b in handlers):
                continue
            if target.split(".")[0] in sys.stdlib_module_names or self._inside(target):
                return target
            return Unknown(
                "environment-dependent",
                f"{module.path}.{name} is {target} when {target.split('.')[0]} is installed, otherwise a fallback",
            )
        return None

    def _try_imports(self, module: griffe.Object) -> dict[str, list]:
        if module.path in self._tries:
            return self._tries[module.path]
        found: dict[str, list] = {}
        tree = None
        if isinstance(module.filepath, Path):
            try:
                tree = ast.parse("\n".join(_lines(module.filepath)))
            except SyntaxError:
                tree = None
        package = (
            module.path if module.is_init_module else module.path.rpartition(".")[0]
        )
        for node in ast.walk(tree) if tree else ():
            if not isinstance(node, ast.Try) or not any(
                _catches_import_error(h) for h in node.handlers
            ):
                continue
            handlers = [(h.lineno, h.end_lineno or h.lineno) for h in node.handlers]
            for statement in node.body:
                for local, target in _imported(statement, package):
                    found.setdefault(local, []).append((target, handlers))
        self._tries[module.path] = found
        return found

    @staticmethod
    def _standard_member(cls: griffe.Object, name: str) -> str | None:
        """``builtins.str.replace`` when ``name`` comes from a standard-library base such as ``str``.

        Only standard-library classes are imported to check this, never library code; a library upgrade
        can't change them, so both releases compare equal unless the base itself changes.
        """
        for base in cls.bases:
            path = str(getattr(base, "canonical_path", base))
            module, _, attribute = path.rpartition(".")
            module = module or "builtins"
            if module.split(".")[0] not in sys.stdlib_module_names:
                continue
            try:
                owner = getattr(importlib.import_module(module), attribute)
            except (ImportError, AttributeError):
                continue
            if isinstance(owner, type) and hasattr(owner, name):
                return f"{module}.{attribute}.{name}"
        return None

    def _missing(
        self, parent: griffe.Object, name: str
    ) -> Found | Missing | Shimmed | Unknown:
        path = f"{parent.path}.{name}"
        members = parent.all_members if parent.is_class else parent.members
        if "__getattr__" in members:
            shim = members["__getattr__"]
            tree = None if shim.is_alias else self.source(shim)
            named = tree is not None and any(
                isinstance(n, ast.Constant) and n.value == name for n in ast.walk(tree)
            )
            warned = warnings_in(tree) if named else []
            if warned:
                return Shimmed(path, warned[0].message, shim)
            return Unknown(
                "dynamic-attribute",
                f"{parent.path} defines __getattr__, so {path} may still resolve",
            )
        if any(m.is_alias and m.wildcard for m in parent.members.values()):
            return Unknown("star-import", f"{parent.path} star-imports another package")
        if parent.is_module and isinstance(parent.filepath, Path):
            folder = parent.filepath.parent
            if any(f.suffix in COMPILED for f in folder.glob(f"{name}.*")):
                return Unknown("compiled-module", f"{path} is a compiled extension")
        if parent.is_class and name in self._fields(parent):
            return Found(None, path, external=f"tuple field {name}")
        inherited = self._standard_member(parent, name) if parent.is_class else None
        if inherited is not None:
            return Found(None, path, external=inherited)
        if parent.is_class and self._external_base(parent):
            return Unknown(
                "external-base",
                f"{parent.path} inherits from a class outside this release",
            )
        return Missing(parent, path)

    @staticmethod
    def _external_base(cls: griffe.Object) -> bool:
        declared = [b for b in cls.bases if str(b) not in ("object", "builtins.object")]
        try:
            return len([b for b in cls.resolved_bases if b.is_class]) < len(declared)
        except (griffe.AliasResolutionError, griffe.CyclicAliasError):
            return True

    def source(self, obj: griffe.Object) -> ast.AST | None:
        if not isinstance(obj.filepath, Path) or obj.lineno is None:
            return None
        lines = _lines(obj.filepath)
        segment = "\n".join(lines[obj.lineno - 1 : obj.endlineno or obj.lineno])
        try:
            return ast.parse(_dedent(segment))
        except SyntaxError:
            return None


def _accelerator(result) -> bool:
    """A compiled speed-up whose pure-Python fallback in the same package is the readable reference."""
    if isinstance(result, Unknown):
        return result.reason == "compiled-module"
    obj = getattr(result, "obj", None)
    return (
        obj is not None
        and isinstance(obj.filepath, Path)
        and obj.filepath.suffix == ".pyi"
    )


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(
        ast.unparse(n).split(".")[-1]
        in ("ImportError", "ModuleNotFoundError", "Exception")
        for n in names
    )


def _imported(statement: ast.stmt, package: str) -> list[tuple[str, str]]:
    """(local name, absolute target) for each name an import statement binds."""
    if isinstance(statement, ast.Import):
        return [
            (
                a.asname or a.name.split(".")[0],
                a.name if a.asname else a.name.split(".")[0],
            )
            for a in statement.names
        ]
    if not isinstance(statement, ast.ImportFrom):
        return []
    base = statement.module or ""
    if statement.level:
        parts = package.split(".")
        anchor = ".".join(parts[: len(parts) - statement.level + 1])
        base = f"{anchor}.{base}" if base else anchor
    return [
        (a.asname or a.name, f"{base}.{a.name}")
        for a in statement.names
        if a.name != "*"
    ]


_LINES: dict[Path, list[str]] = {}


def _lines(path: Path) -> list[str]:
    if path not in _LINES:
        _LINES[path] = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return _LINES[path]


def _dedent(text: str) -> str:
    lines = text.splitlines()
    indent = min(
        (len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0
    )
    return "\n".join(line[indent:] for line in lines)


def _decorators(obj: griffe.Object) -> set[str]:
    return {
        str(d.value).split("(")[0].split(".")[-1]
        for d in getattr(obj, "decorators", ())
    }


def _benign_class_decorator(cls: griffe.Object, decorator) -> bool:
    """Decorators that leave ``__init__`` as the constructor's signature.

    ``six.add_metaclass(Meta)`` only sets the metaclass, so it is benign unless ``Meta`` overrides
    ``__call__``, which could change construction.
    """
    value = decorator.value
    name = str(getattr(value, "canonical_path", value)).split("(")[0].split(".")[-1]
    if name in ("total_ordering", "final", "runtime_checkable", "unique"):
        return True
    if name != "add_metaclass" or not isinstance(value, griffe.ExprCall):
        return False
    meta = next(iter(value.arguments), None)
    path = getattr(meta, "canonical_path", None)
    module = cls.parent
    target = (
        module.members.get(path.split(".")[-1]) if path and module is not None else None
    )
    return target is not None and target.is_class and "__call__" not in target.members


def signature(obj: griffe.Object) -> Signature | None:
    """Parameters a call to ``obj`` accepts, or None when they can't be known statically."""
    owner = obj
    if obj.is_class:
        if any(not _benign_class_decorator(obj, d) for d in obj.decorators):
            return None
        members = obj.all_members
        init = members.get("__init__") or members.get("__new__")
        if init is None:
            return None
        try:
            owner = init.final_target if init.is_alias else init
        except (griffe.AliasResolutionError, griffe.CyclicAliasError):
            return None
    if not owner.is_function or _decorators(owner) - BENIGN_DECORATORS:
        return None
    parameters = list(owner.parameters)
    bound = owner.parent is not None and owner.parent.is_class
    if bound and "staticmethod" not in _decorators(owner) and parameters:
        parameters = parameters[1:]
    kinds = griffe.ParameterKind
    return Signature(
        names={
            p.name: p
            for p in parameters
            if p.kind not in (kinds.var_positional, kinds.var_keyword)
        },
        positional=[
            p.name
            for p in parameters
            if p.kind in (kinds.positional_only, kinds.positional_or_keyword)
        ],
        var_positional=any(p.kind is kinds.var_positional for p in parameters),
        var_keyword=any(p.kind is kinds.var_keyword for p in parameters),
        owner=owner,
    )


def _text(node: ast.AST) -> str:
    return " ".join(
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    )


def _is_deprecation(call: ast.Call) -> bool:
    name = ast.unparse(call.func)
    if "deprecat" in name.lower():
        return True
    return "warn" in name.lower() and any(
        DEPRECATION.search(ast.unparse(arg))
        for arg in [*call.args, *(k.value for k in call.keywords)]
    )


def warnings_in(tree: ast.AST | None) -> list[Warning_]:
    """Deprecation warnings raised in a function body, with the parameter names that trigger them."""
    if tree is None:
        return []
    found: list[Warning_] = []

    def visit(node: ast.AST, conditions: frozenset[str]):
        if isinstance(node, (ast.If, ast.While)):
            names = frozenset(
                n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)
            )
            for child in node.body:
                visit(child, conditions | names)
            for child in node.orelse:
                visit(child, conditions | names)
            return
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        if isinstance(node, ast.Call) and _is_deprecation(node):
            variables = " ".join(
                max(
                    (a for a in assigned.get(n.id, ()) if a[0] < node.lineno),
                    default=(0, ""),
                )[1]
                for n in ast.walk(node)
                if isinstance(n, ast.Name)
            ).strip()
            message = _text(node) or variables or ast.unparse(node)[:200]
            found.append(Warning_(message, conditions))
        for child in ast.iter_child_nodes(node):
            visit(child, conditions)

    root = next(
        (
            n
            for n in ast.iter_child_nodes(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        tree,
    )
    assigned: dict[str, list[tuple[int, str]]] = {}
    for node in ast.walk(root):
        if isinstance(node, ast.Assign) and _text(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).append(
                        (node.lineno, _text(node.value))
                    )
    for decorator in getattr(root, "decorator_list", ()):
        if "deprecat" in ast.unparse(decorator).lower():
            found.append(Warning_(_text(decorator) or ast.unparse(decorator)))
    for child in ast.iter_child_nodes(root):
        if child not in getattr(root, "decorator_list", ()):
            visit(child, frozenset())
    return found


def _deprecations(surface: Surface, obj: griffe.Object) -> list[Warning_]:
    targets = [obj]
    if obj.is_class:
        targets = [obj.members[n] for n in ("__init__", "__new__") if n in obj.members]
        if any("deprecat" in str(d.value).lower() for d in obj.decorators):
            return [Warning_(" ".join(str(d.value) for d in obj.decorators))]
    found = []
    for target in targets:
        if target.is_function:
            found.extend(warnings_in(surface.source(target)))
    return found


def _mentions(message: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", message) is not None


def check(old: Surface, new: Surface, usage: Usage) -> UsageCheck:
    """Compare what ``usage`` relies on between two releases."""

    def unchecked(reason: str, detail: str) -> UsageCheck:
        return UsageCheck(
            usage=usage,
            unchecked=(
                Unchecked(reason=reason, detail=detail, location=usage.location),
            ),
        )

    before = old.lookup(usage.symbol)
    if isinstance(before, Unknown):
        return unchecked(before.reason, before.detail)
    if isinstance(before, Shimmed):
        before = Found(before.shim, before.path)
    if isinstance(before, Missing):
        return unchecked(
            "not-in-old-version", f"{before.path} was not found in {old.version} either"
        )
    after = new.lookup(usage.symbol)
    if isinstance(after, Unknown):
        return unchecked(after.reason, after.detail)
    if isinstance(after, Shimmed):
        return UsageCheck(
            usage=usage,
            changes=(
                APIChange(
                    kind="deprecated",
                    symbol=after.path,
                    detail=f"{after.path} is only provided by a deprecated module __getattr__ in {new.version}",
                    message=after.message,
                    after=new.location(after.shim),
                ),
            ),
        )
    previous = before.obj and _deprecations(old, before.obj)
    if isinstance(after, Missing):
        gone = old.lookup(after.path) if after.path != before.path else before
        origin = gone.obj if isinstance(gone, Found) else None
        warned = (_deprecations(old, origin) if origin is not None else []) or previous
        hint = next((w.message for w in warned or ()), None)
        found = _replacement(old, new, after.path, origin, hint)
        return UsageCheck(
            usage=usage,
            changes=(
                APIChange(
                    kind="removed",
                    symbol=after.path,
                    detail=f"{after.path} exists in {old.version} but not in {new.version}",
                    message=hint,
                    replacement=found[0] if found else None,
                    replacement_source=found[1] if found else None,
                    before=old.location(origin) if origin is not None else None,
                ),
            ),
        )
    if before.rest or after.rest or before.obj is None or after.obj is None:
        if before.obj is not None and before.obj.is_function and before.rest:
            return unchecked(
                "return-value",
                f"{usage.symbol} reads from what {before.path} returns, which this check does not compare",
            )
        if before.external and (before.external, before.rest) == (
            after.external,
            after.rest,
        ):
            return UsageCheck(usage=usage)
        sides = [
            f"{label} {side.external or side.path}"
            + (" (outside this distribution)" if side.external else "")
            for label, side in ((old.version, before), (new.version, after))
        ]
        return unchecked(
            "external-alias",
            f"{usage.symbol} resolves to {' and '.join(sides)}, which this check does not compare",
        )
    if usage.kind == "subclass" and not after.obj.is_class:
        return unchecked(
            "dynamic-definition",
            f"{after.path} is no longer a plain class in {new.version}",
        )
    changes: list[APIChange] = []
    problems: list[Unchecked] = []
    if usage.kind == "call":
        _arguments(old, new, usage, before.obj, after.obj, changes, problems)
        changes = [_hinted(c, previous or ()) for c in changes]
        accepted_now = signature(after.obj)
        changes = [_parameter_replacement(c, accepted_now) for c in changes]
    supplied = set(usage.keywords)
    accepted = set(getattr(signature(after.obj), "names", ()))
    for warning in _deprecations(new, after.obj):
        triggers = (warning.parameters & accepted) or {
            k for k in supplied if _mentions(warning.message, k)
        }
        if warning.parameters and not triggers & supplied:
            continue
        parameter = next(iter(sorted(triggers & supplied)), None)
        already = any(w.message == warning.message for w in previous or ())
        changes.append(
            APIChange(
                kind="deprecated",
                symbol=after.path,
                parameter=parameter,
                detail=(
                    f"{after.path}({parameter}=) warns as deprecated in {new.version}"
                    if parameter
                    else f"{after.path} warns as deprecated in {new.version}"
                )
                + (f", as it already did in {old.version}" if already else ""),
                message=warning.message,
                after=new.location(after.obj),
            )
        )
    return UsageCheck(usage=usage, changes=tuple(changes), unchecked=tuple(problems))


def _stdlib_has(path: str) -> bool:
    """Whether a standard-library dotted name exists; only the standard library is imported."""
    parts = path.split(".")
    if parts[0] not in sys.stdlib_module_names:
        return False
    for split in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:split]))
        except ImportError:
            continue
        try:
            for attribute in parts[split:]:
                obj = getattr(obj, attribute)
        except AttributeError:
            return False
        return True
    return False


def _replacement(
    old: Surface, new: Surface, removed: str, before, message: str | None
) -> tuple[str, str] | None:
    """What replaces a removed symbol: a name the old deprecation message quotes that exists, or else a
    new object in the same module with the same parameters ("likely renamed")."""
    parent, _, name = removed.rpartition(".")
    skip = {removed, name, getattr(before, "path", None)}
    for token in QUOTED.findall(message or ""):
        if token in skip:
            continue
        candidates = (
            [token]
            if "." in token
            else [f"{parent}.{token}", f"{parent.split('.')[0]}.{token}"]
        )
        for candidate in candidates:
            if new._inside(candidate):
                if isinstance(new.lookup(candidate), Found):
                    return candidate, "message"
            elif _stdlib_has(candidate):
                return candidate, "message"
            elif (
                "." in token and candidate.split(".")[0] not in sys.stdlib_module_names
            ):
                return candidate, "message-unverified"
    was = (
        signature(before)
        if before is not None and (before.is_function or before.is_class)
        else None
    )
    module, earlier = new.lookup(parent), old.lookup(parent)
    if (
        was is None
        or not was.names
        or not isinstance(module, Found)
        or module.obj is None
    ):
        return None
    existing = set(getattr(getattr(earlier, "obj", None), "members", {}))
    for member in module.obj.members.values():
        if member.is_alias or member.name in existing or member.kind != before.kind:
            continue
        now = signature(member)
        if now is not None and list(now.names) == list(was.names):
            return member.path, "signature"
    return None


def _parameter_replacement(change: APIChange, now: Signature | None) -> APIChange:
    """For a removed keyword, the parameters the deprecation message names that the new release accepts."""
    if change.kind != "parameter-removed" or not change.message or now is None:
        return change
    named = [
        t
        for t in QUOTED.findall(change.message)
        if t != change.parameter and t in now.names
    ]
    if not named:
        return change
    return change.model_copy(
        update={
            "replacement": " or ".join(f"{t}=" for t in named),
            "replacement_source": "message",
        }
    )


def _hinted(change: APIChange, warnings: list[Warning_] | tuple) -> APIChange:
    """Attach the old release's deprecation message for the parameter, which usually names the replacement."""
    if change.message or not change.parameter:
        return change
    message = next(
        (
            w.message
            for w in warnings
            if change.parameter in w.parameters
            or _mentions(w.message, change.parameter)
        ),
        None,
    )
    return change.model_copy(update={"message": message}) if message else change


def _accepts(
    surface: Surface, sig: Signature, keyword: str, depth: int = 0
) -> bool | None:
    """Whether a call accepts ``keyword=``: True, False, or None when ``**kwargs`` goes somewhere unknown.

    ``**kwargs`` is followed into the calls that receive it (``super().__init__(**kwargs)``,
    ``self.method(**kwargs)``, ``Helper(**kwargs)``), a few hops deep. A body that reads the key itself
    (``kwargs.pop("timeout")``) accepts it.
    """
    parameter = sig.names.get(keyword)
    if parameter is not None:
        return parameter.kind is not griffe.ParameterKind.positional_only
    if not sig.var_keyword:
        return False
    if depth > 3:
        return None
    tree = surface.source(sig.owner)
    function = (
        next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            None,
        )
        if tree is not None
        else None
    )
    if function is None or function.args.kwarg is None:
        return None
    name = function.args.kwarg.arg
    targets, unknown = [], False
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            if any(
                k.arg is None and isinstance(k.value, ast.Name) and k.value.id == name
                for k in node.keywords
            ):
                callee = _callee(surface, sig.owner, node.func)
                if callee is None:
                    unknown = True
                else:
                    targets.append(callee)
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == name
                and node.func.attr in ("pop", "get", "setdefault")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == keyword
            ):
                return True
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == name
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == keyword
        ):
            return True
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Constant)
            and node.left.value == keyword
            and any(isinstance(c, ast.Name) and c.id == name for c in node.comparators)
        ):
            return True
    if not targets:
        return None
    results = []
    for target in targets:
        inner = signature(target)
        results.append(
            None if inner is None else _accepts(surface, inner, keyword, depth + 1)
        )
    if any(results):
        return True
    return None if unknown or None in results else False


def _callee(
    surface: Surface, owner: griffe.Object, func: ast.expr
) -> griffe.Object | None:
    """The library object a call inside ``owner`` targets, when it can be named statically."""
    cls = owner.parent if owner.parent is not None and owner.parent.is_class else None
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Call)
        and isinstance(func.value.func, ast.Name)
        and func.value.func.id == "super"
        and cls is not None
    ):
        try:
            mro = cls.mro()
        except (ValueError, griffe.AliasResolutionError, griffe.CyclicAliasError):
            return None
        for base in mro:
            member = base.members.get(func.attr)
            if member is not None:
                return _final(member)
        return None
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in ("self", "cls")
        and cls is not None
    ):
        member = cls.all_members.get(func.attr)
        return _final(member) if member is not None else None
    dotted = ast.unparse(func)
    module = owner
    while module is not None and not module.is_module:
        module = module.parent
    path = surface._name_in(dotted, module) if module is not None else None
    if path is None or not surface._inside(path):
        return None
    found = surface.lookup(path, 5)
    return found.obj if isinstance(found, Found) and not found.rest else None


def _final(member) -> griffe.Object | None:
    try:
        return member.final_target if member.is_alias else member
    except (griffe.AliasResolutionError, griffe.CyclicAliasError):
        return None


def _literal(default) -> tuple | None:
    """``(value,)`` for a literal default such as ``"scrypt"``, ``False`` or ``None``.

    Names (``DEFAULT_ALLOWED_METHODS``) and sentinels (``_Default``) are often resolved inside the body,
    so a textual change there says nothing about the effective default.
    """
    try:
        return (ast.literal_eval(str(default)),)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None


def _arguments(old, new, usage, before, after, changes, problems):
    was, now = signature(before), signature(after)
    passes = bool(usage.keywords or usage.positional)
    if was is None or now is None:
        if passes:
            problems.append(
                Unchecked(
                    reason="signature-unknown",
                    detail=f"the parameters of {after.path} can't be read statically",
                    location=usage.location,
                )
            )
        return
    where = dict(before=old.location(was.owner), after=new.location(now.owner))
    for keyword in usage.keywords:
        if _accepts(old, was, keyword) is False:
            continue
        accepted = _accepts(new, now, keyword)
        if accepted:
            continue
        if accepted is None:
            problems.append(
                Unchecked(
                    reason="kwargs-absorbed",
                    detail=f"{after.path} takes **kwargs in {new.version} and passes them somewhere this check can't follow, so {keyword}= may still be accepted",
                    location=usage.location,
                )
            )
            continue
        changes.append(
            APIChange(
                kind="parameter-removed",
                symbol=after.path,
                parameter=keyword,
                detail=f"{after.path} accepts {keyword}= in {old.version} but not in {new.version}"
                + (" (followed through **kwargs)" if now.var_keyword else ""),
                **where,
            )
        )
    count = usage.positional
    if (
        count > len(now.positional)
        and not now.var_positional
        and count <= len(was.positional)
    ):
        changes.append(
            APIChange(
                kind="parameter-removed",
                symbol=after.path,
                detail=f"{after.path} takes {len(now.positional)} positional arguments in {new.version}; the call passes {count}",
                **where,
            )
        )
    for index in range(min(count, len(was.positional), len(now.positional))):
        if was.positional[index] != now.positional[index]:
            changes.append(
                APIChange(
                    kind="parameter-moved",
                    symbol=after.path,
                    parameter=was.positional[index],
                    detail=f"positional argument {index + 1} of {after.path} is {was.positional[index]} in {old.version} but {now.positional[index]} in {new.version}",
                    **where,
                )
            )
    supplied = set(usage.keywords) | set(now.positional[:count])
    for name, parameter in now.names.items():
        if name in supplied:
            continue
        earlier = was.names.get(name)
        if parameter.required and (earlier is None or not earlier.required):
            changes.append(
                APIChange(
                    kind="parameter-required",
                    symbol=after.path,
                    parameter=name,
                    detail=f"{after.path} requires {name} in {new.version}, which the call doesn't pass",
                    **where,
                )
            )
        elif (
            earlier is not None
            and not parameter.required
            and _literal(earlier.default)
            and _literal(parameter.default)
            and _literal(earlier.default)[0] != _literal(parameter.default)[0]
        ):
            changes.append(
                APIChange(
                    kind="default-changed",
                    symbol=after.path,
                    parameter=name,
                    detail=f"the default of {name} changed from {earlier.default} to {parameter.default}",
                    **where,
                )
            )
