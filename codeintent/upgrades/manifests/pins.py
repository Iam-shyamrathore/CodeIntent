"""Classify version constraints by how they limit upgrades."""

from __future__ import annotations

from packaging.specifiers import Specifier, SpecifierSet
from poetry.core.packages.dependency import Dependency as PoetryDependency

from codeintent.upgrades.models import Pin

_KINDS = {
    "<": "upper_bound",
    "<=": "upper_bound",
    "!=": "exclusion",
    "~=": "compatible",
    "===": "exact",
}


def canonical(specifier: str) -> str:
    return str(SpecifierSet(specifier))


def classify(specifier: str) -> tuple[Pin, ...]:
    pins = []
    for clause in (part.strip() for part in specifier.split(",")):
        if not clause:
            continue
        spec = Specifier(clause)
        if spec.operator == "==":
            kind = "wildcard" if spec.version.endswith(".*") else "exact"
        else:
            kind = _KINDS.get(spec.operator)
        if kind:
            pins.append(Pin(kind=kind, clause=clause))
    return tuple(pins)


def _pep440(constraint: str) -> str:
    rendered = PoetryDependency("x", constraint).to_pep_508()
    return rendered[rendered.index("(") + 1 : -1] if "(" in rendered else ""


def from_poetry(constraint: str) -> tuple[str, tuple[Pin, ...]]:
    """Convert a Poetry constraint (``^1.2``, ``~1.2.3``, ``1.2.3``) to a PEP 440 specifier."""
    constraint = constraint.strip()
    if "|" in constraint:
        raise ValueError(f"union constraint {constraint!r} has no PEP 440 equivalent")
    if constraint in ("", "*"):
        return "", ()
    pins = []
    for token in (part.strip() for part in constraint.split(",")):
        if token.startswith("^"):
            pins.append(Pin(kind="caret", clause=token))
        elif token.startswith("~") and not token.startswith("~="):
            pins.append(Pin(kind="tilde", clause=token))
        else:
            pins.extend(classify(_pep440(token)))
    return canonical(_pep440(constraint)), tuple(pins)
