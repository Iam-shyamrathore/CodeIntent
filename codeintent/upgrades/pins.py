"""Why a dependency is pinned, and whether the pin can be lifted.

A pin is a deliberate restriction in a manifest: an upper bound, an exclusion, ``~=``/``^``/``~``, a wildcard,
or ``==`` in a project file. ``==`` lines in requirements files are version locks, not pins.

Where a pin came from is read from git: blame the declaring line, then walk back through commits that only
touched the line (a reformat or a version bump) to the commit that added the restricting clause, and the pull
request it was merged in. Whether it can be lifted is decided by the verdict engine on the upgrade the pin
blocks, never guessed from text.
"""

from __future__ import annotations

import re
from typing import Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from codeintent.upgrades.models import Pin, Record

DECLARING = {"pyproject", "setup.cfg", "setup.py"}
MAX_HOPS = 8
MAX_TEXT = 600
Lift = Literal["can-be-lifted", "keep", "unknown"]


class PinOrigin(Record):
    commit: str
    commit_url: str | None = None
    date: str | None = None
    author: str | None = None
    message: str
    """The commit message, clipped: the author's own words for why the line changed."""
    pr_number: int | None = None
    pr_title: str | None = None
    pr_url: str | None = None
    pr_body: str | None = None


def deliberate(pins: tuple[Pin, ...], fmt: str) -> tuple[Pin, ...]:
    """The restricting clauses a person chose, as opposed to a lock-style ``==``."""
    return tuple(p for p in pins if p.kind != "exact" or fmt in DECLARING)


def allows(specifier: str, version: str | None) -> bool | None:
    """Whether ``version`` satisfies ``specifier``; None when either is not PEP 440."""
    if not version:
        return None
    try:
        return SpecifierSet(specifier).contains(Version(version), prereleases=True)
    except (InvalidSpecifier, InvalidVersion):
        return None


def lift(blocks: bool | None, verdict: str | None) -> tuple[Lift | None, str]:
    """Lift status from the verdict on the upgrade the pin blocks."""
    if blocks is None:
        return (
            "unknown",
            "the specifier or version is not in a form that can be compared",
        )
    if not blocks:
        return None, "the pin allows the latest release"
    if verdict == "no-known-impact":
        return (
            "can-be-lifted",
            "the latest release changes nothing your code uses",
        )
    if verdict in ("breaks", "needs-change"):
        return "keep", "the latest release changes code you use"
    if verdict is None:
        return "unknown", "there is no exact current version to compare with"
    return "unknown", "some uses could not be checked against the latest release"


def _clip(text: str | None) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def _name_pattern(package: str) -> re.Pattern:
    parts = re.split(r"[-_.]+", canonicalize_name(package))
    return re.compile(
        r"(?<![A-Za-z0-9._-])"
        + r"[-_.]+".join(map(re.escape, parts))
        + r"(?![A-Za-z0-9]|[-_.][A-Za-z0-9])",
        re.IGNORECASE,
    )


def line_with(text: str, package: str, clause: str) -> int | None:
    """The 1-based line declaring ``package`` with ``clause`` (whitespace ignored), if exactly one."""
    name, wanted = _name_pattern(package), re.sub(r"\s+", "", clause)
    found = [
        n
        for n, line in enumerate(text.splitlines(), 1)
        if name.search(line) and wanted in re.sub(r"\s+", "", line)
    ]
    return found[0] if len(found) == 1 else None


def origin(
    repo,
    sha: str,
    path: str,
    line: int,
    package: str,
    clause: str,
    parent_repo=None,
) -> tuple[PinOrigin | None, str | None]:
    """The commit (and pull request) that added ``clause`` to ``package`` at ``path:line`` as of ``sha``.

    ``repo`` is an ``upstream.Repo``; ``parent_repo`` the repository a fork was made from, where the pull
    request usually lives. Returns ``(origin, None)`` or ``(None, reason)``.
    """
    for _ in range(MAX_HOPS):
        ranges = repo.blame(sha, path)
        if not ranges:
            return None, "git blame is unavailable for this file"
        oid = next(
            (
                r["commit"]["oid"]
                for r in ranges
                if r["startingLine"] <= line <= r["endingLine"]
            ),
            None,
        )
        commit = repo.commit(oid) if oid else None
        if not commit:
            return None, "the commit behind this line could not be read"
        parent = commit["parents"][0] if commit.get("parents") else None
        earlier = repo.content(parent, path) if parent else None
        before = line_with(earlier, package, clause) if earlier else None
        if before is None:
            pr = repo.pr_for(commit) or (
                parent_repo.pr_for(commit) if parent_repo else None
            )
            return (
                PinOrigin(
                    commit=commit["sha"],
                    commit_url=commit.get("html_url"),
                    date=commit.get("date"),
                    author=commit.get("author"),
                    message=_clip(commit.get("message")) or "",
                    pr_number=pr.get("number") if pr else None,
                    pr_title=pr.get("title") if pr else None,
                    pr_url=pr.get("html_url") if pr else None,
                    pr_body=_clip(pr.get("body")) if pr else None,
                ),
                None,
            )
        sha, line = parent, before
    return None, f"the pin is older than {MAX_HOPS} edits of its line"
