"""Static API model of a released library version, compared from the consumer's side.

Each version is loaded with griffe (ISC) in static mode only (``allow_inspection=False``): source and stub
files are parsed, never imported. Every symbol a consumer uses is resolved in both versions, including
non-public aliases, and the call's keyword and positional arguments are checked against both signatures.
Absence is only reported when nothing could still provide the name at run time; otherwise the usage is
returned as unchecked with the reason.
"""

from __future__ import annotations

import ast
import logging
import re
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
            if member.is_alias:
                try:
                    member = member.final_target
                except (griffe.AliasResolutionError, griffe.CyclicAliasError):
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
        """Follow ``name = other.name`` assignments, which griffe keeps as attributes."""
        value = obj.value if obj.is_attribute else None
        if not isinstance(value, (griffe.ExprName, griffe.ExprAttribute)) or depth > 4:
            return Found(obj, obj.path, rest=rest)
        target = value.canonical_path
        if target == obj.path:
            return Found(obj, obj.path, rest=rest)
        if any(target == m or target.startswith(m + ".") for m in self.modules):
            return self.lookup(".".join((target, *rest)), depth + 1)
        return Found(None, obj.path, external=target, rest=rest)

    def _missing(self, parent: griffe.Object, name: str) -> Missing | Shimmed | Unknown:
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
            return len(cls.resolved_bases) < len(declared)
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


def signature(obj: griffe.Object) -> Signature | None:
    """Parameters a call to ``obj`` accepts, or None when they can't be known statically."""
    owner = obj
    if obj.is_class:
        if obj.decorators:
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
        hint = next((w.message for w in previous or ()), None)
        return UsageCheck(
            usage=usage,
            changes=(
                APIChange(
                    kind="removed",
                    symbol=after.path,
                    detail=f"{after.path} exists in {old.version} but not in {new.version}",
                    message=hint,
                    before=old.location(before.obj) if before.obj else None,
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
        if keyword not in was.names and not was.var_keyword:
            continue
        if (
            keyword in now.names
            and now.names[keyword].kind is not griffe.ParameterKind.positional_only
        ):
            continue
        if now.var_keyword:
            problems.append(
                Unchecked(
                    reason="kwargs-absorbed",
                    detail=f"{after.path} takes **kwargs in {new.version}, so {keyword}= may still be accepted",
                    location=usage.location,
                )
            )
            continue
        changes.append(
            APIChange(
                kind="parameter-removed",
                symbol=after.path,
                parameter=keyword,
                detail=f"{after.path} accepts {keyword}= in {old.version} but not in {new.version}",
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
            and str(earlier.default) != str(parameter.default)
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
