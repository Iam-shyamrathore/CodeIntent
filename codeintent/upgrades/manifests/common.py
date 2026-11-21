"""Shared construction of dependency records from PEP 508 strings."""

from __future__ import annotations

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from codeintent.upgrades.manifests.pins import canonical, classify
from codeintent.upgrades.models import Dependency, Format, Issue, Location

_VCS = ("git+", "hg+", "svn+", "bzr+")


def url_source(url: str) -> str:
    if url.startswith(_VCS):
        return "vcs"
    return "path" if url.startswith("file:") else "url"


def pep508(
    text: str,
    *,
    format: Format,
    file: str,
    line: int | None,
    group: str = "main",
    source: str | None = None,
) -> Dependency | Issue:
    try:
        requirement = Requirement(text)
    except InvalidRequirement as error:
        return Issue(
            reason="unparseable-requirement",
            detail=str(error),
            location=Location(file=file, line=line),
        )
    specifier = str(requirement.specifier)
    return Dependency(
        name=canonicalize_name(requirement.name),
        declared=text.strip(),
        specifier=canonical(specifier),
        marker=str(requirement.marker) if requirement.marker else None,
        extras=tuple(sorted(requirement.extras)),
        group=group,
        source=source
        or (url_source(requirement.url) if requirement.url else "registry"),
        pins=classify(specifier),
        format=format,
        location=Location(file=file, line=line),
    )


def strings(value) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(item, (str, dict)) for item in value):
        return [item for item in value if isinstance(item, str)]
    return None
