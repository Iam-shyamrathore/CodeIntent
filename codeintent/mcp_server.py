"""CodeIntent over MCP: deterministic upgrade briefs for AI coding agents.

Every tool downloads a public GitHub repository as a source tarball (never executed), reads its
manifests and lock files, and answers from the same engine as the GitHub App's PR comments. Nothing
here generates text with a model: briefs and steps are derived by fixed rules from the findings.

Serve it with ``python -m scripts.mcp_server`` (streamable HTTP at ``/mcp``). Every HTTP request
must carry ``Authorization: Bearer $CODEINTENT_MCP_TOKEN``.
"""

from __future__ import annotations

import functools
import hmac
import inspect
import logging
import os
import re
import threading
import time
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, asynccontextmanager, contextmanager, nullcontext
from contextvars import ContextVar
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from codeintent.upgrades import advisories as osv
from codeintent.upgrades import artifacts, manifests, repository
from codeintent.upgrades import pins as pin_history
from codeintent.upgrades.advisories import AdvisoryCheck
from codeintent.upgrades.models import Dependency, ManifestScan
from codeintent.upgrades.pins import PinOrigin
from codeintent.upgrades.verdict import Finding, UpgradeVerdict, evaluate

logger = logging.getLogger("codeintent.mcp")
_installation: ContextVar[int | None] = ContextVar("mcp_installation", default=None)
"""The GitHub App installation whose workspace token authenticated this request, if any."""
_token_id: ContextVar[str | None] = ContextVar("mcp_token", default=None)
_run: ContextVar[Any] = ContextVar("mcp_run", default=None)
"""The ``runs.Run`` recording the current tool call, if recording is available."""

PYPI = "https://pypi.org/pypi"
MAX_DEPENDENCIES = 300
MAX_STEPS = 60
MAX_LISTED = 50
LATEST_TTL = 3600.0
LATEST_WORKERS = 8
HTTP_TIMEOUT = httpx.Timeout(60, connect=15)
BUSY_WAIT_SECONDS = 60
SLOTS = threading.BoundedSemaphore(int(os.getenv("CODEINTENT_MCP_CONCURRENCY", "2")))
"""Concurrent repository analyses; each one downloads a tarball and may scan with a process pool."""

REPO = re.compile(
    r"^(?:https?://github\.com/)?(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<name>[A-Za-z0-9._-]{1,100}?)(?:\.git)?/?(?:@(?P<ref>[^\s@]{1,200}))?$"
)
REF = re.compile(r"^[A-Za-z0-9._/+-]{1,200}$")
PROJECT = re.compile(r"^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$", re.IGNORECASE)
LOCKS = {"uv.lock", "poetry.lock"}

RepoArg = Annotated[
    str,
    Field(
        description=(
            "Public GitHub repository as 'owner/name' or 'owner/name@ref' (ref = branch, tag or "
            "commit SHA; default branch HEAD when omitted). Example: 'openai/openai-python@v1.54.4'."
        ),
        min_length=3,
        max_length=300,
    ),
]
PackageArg = Annotated[
    str,
    Field(
        description="PyPI project name, e.g. 'httpx' (case and -/_ differences are ignored).",
        min_length=1,
        max_length=100,
    ),
]
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)


# ---------------------------------------------------------------- output models


class Place(BaseModel):
    file: str
    line: int | None = None


class Declaration(BaseModel):
    """One place a manifest or lock file names the package."""

    file: str
    line: int | None = None
    format: str
    group: str
    direct: bool
    specifier: str = Field(description="Version specifier as written, '' when none.")
    locked_version: str | None = Field(
        None, description="Exact version from a lock file or an exact '==' pin."
    )


class Change(BaseModel):
    kind: str = Field(
        description="removed | parameter-removed | parameter-required | parameter-moved | default-changed | deprecated"
    )
    symbol: str
    parameter: str | None = None
    detail: str
    replacement: str | None = Field(
        None, description="What to use instead, when the library names it."
    )
    replacement_source: str | None = Field(
        None,
        description="message = taken from the library's deprecation text and verified to exist; "
        "message-unverified = named in the text but not verified; signature = inferred from the new signature.",
    )
    library_message: str | None = Field(
        None, description="The library's own deprecation/warning text, verbatim."
    )
    before: Place | None = Field(None, description="Definition in the old release.")
    after: Place | None = Field(None, description="Definition in the new release.")


class BriefFinding(BaseModel):
    severity: Literal["breaks", "needs-change"]
    guarded: bool = Field(
        description="True when every affected use sits behind an import fallback (try/except ImportError etc.)."
    )
    change: Change
    locations: list[str] = Field(
        description="Places in the consumer repository, as 'path:line'."
    )


class UncheckedItem(BaseModel):
    location: str
    reason: str
    detail: str
    symbol: str | None = None


class AdvisoryItem(BaseModel):
    id: str
    aliases: list[str] = []
    summary: str | None = None
    severity: str | None = None
    fixed: str | None = Field(None, description="First fixed version, when known.")
    url: str


class VersionAdvisories(BaseModel):
    package: str
    version: str
    status: Literal["advisories", "none-known", "not-checked"]
    advisories: list[AdvisoryItem] = []
    detail: str | None = None


class ReleaseInfo(BaseModel):
    repository: str | None = None
    start_published: str | None = None
    end_published: str | None = None
    end_yanked: bool = False
    start_tag: str | None = None
    end_tag: str | None = None
    note: str | None = None


class Coverage(BaseModel):
    files: int
    usages: int
    checked: int
    unchecked: int
    unchanged_unchecked: int
    upstream_changes: int


class UpgradeBrief(BaseModel):
    repo: str
    ref: str
    package: str
    from_version: str
    from_version_source: Literal["argument", "lock", "exact-pin"]
    to_version: str
    verdict: Literal["breaks", "needs-change", "not-checked", "no-known-impact"]
    label: str
    reason: str
    steps: list[str] = Field(
        description="Ordered, deterministic actions derived from the findings below; no model wrote them."
    )
    findings: list[BriefFinding]
    unchecked: list[UncheckedItem] = Field(
        description="Uses the analysis could not follow that touch parts of the library that changed: review by hand."
    )
    limits_count: int = Field(
        description="Uses not followed that touch nothing the upgrade changed (not listed)."
    )
    declarations: list[Declaration] = Field(
        description="Where the repo declares the package."
    )
    advisories: list[VersionAdvisories] = Field(
        description="OSV advisories for from_version and to_version."
    )
    release: ReleaseInfo | None = None
    coverage: Coverage | None = None
    truncated: bool = Field(
        False, description="True when steps or lists were cut to stay compact."
    )


class Pinning(BaseModel):
    file: str
    line: int | None = None
    format: str
    group: str
    direct: bool
    constraint_only: bool
    specifier: str
    marker: str | None = None
    locked_version: str | None = None
    pins: list[dict[str, str]] = Field(
        description="Restrictive clauses with their kind: exact, upper_bound, exclusion, compatible, caret, tilde, wildcard."
    )
    introduced_by: PinOrigin | None = Field(
        None,
        description=(
            "The commit (and pull request, when found) that added the first restricting clause, from git "
            "blame walked back past edits that kept it. Its message and PR text are the author's reason."
        ),
    )
    origin_detail: str | None = Field(
        None, description="Why introduced_by is null for a deliberate pin."
    )


class WhyPinned(BaseModel):
    repo: str
    ref: str
    package: str
    declared: bool
    pinned: bool = Field(
        description="True when at least one declaration restricts versions (pins non-empty)."
    )
    declarations: list[Pinning]
    note: str
    manifest_issues: list[str] = []


class DependencyStatus(BaseModel):
    name: str
    current: str | None = Field(
        None, description="Locked version, else an exact '==' pin, else null."
    )
    current_source: Literal["lock", "exact-pin"] | None = None
    declared: list[str] = Field(
        description="'file:line specifier [group]' for each declaration."
    )
    latest: str | None = Field(
        None, description="Latest non-yanked final release on PyPI."
    )
    blocked_by: list[str] = Field(
        [],
        description="Declarations ('file:line specifier') whose specifier excludes `latest`.",
    )
    newer_available: bool | None = Field(
        None, description="latest > current; null when either is unknown."
    )
    note: str | None = None


class DependencyList(BaseModel):
    repo: str
    ref: str
    total: int
    returned: int
    truncated: bool
    dependencies: list[DependencyStatus]
    manifest_issues: list[str] = []


class AdvisoryReport(BaseModel):
    repo: str
    ref: str
    checked: int = Field(description="Distinct (package, version) pairs looked up.")
    truncated: bool
    affected: list[VersionAdvisories] = Field(
        description="Pairs with at least one active advisory."
    )
    not_checked: list[VersionAdvisories] = Field(
        description="Pairs that could not be checked, with the reason."
    )
    none_known: list[str] = Field(description="'name==version' with no known advisory.")
    unpinned: list[str] = Field(
        description="Dependencies with no locked or exact version, so not looked up."
    )
    manifest_issues: list[str] = []


# ---------------------------------------------------------------- helpers


def _parse_repo(value: str) -> tuple[str, str]:
    match = REPO.match(value.strip())
    if not match:
        raise ToolError(
            f"repo must look like 'owner/name' or 'owner/name@ref', got {value!r}"
        )
    ref = match["ref"] or "HEAD"
    if not REF.match(ref) or ".." in ref:
        raise ToolError(f"ref {ref!r} contains characters a git ref cannot have")
    return f"{match['owner']}/{match['name']}", ref


def _package(value: str) -> str:
    if not PROJECT.match(value.strip()):
        raise ToolError(f"{value!r} is not a valid PyPI project name")
    return canonicalize_name(value.strip())


def _version(value: str, what: str) -> str:
    try:
        Version(value.strip())
    except InvalidVersion as error:
        raise ToolError(
            f"{what} {value!r} is not a PEP 440 version (e.g. '0.28.0')"
        ) from error
    return value.strip()


def _place(location) -> str:
    return (
        f"{location.file}:{location.line}"
        if location.line is not None
        else location.file
    )


def _issues(scan: ManifestScan) -> list[str]:
    return [
        f"{_place(i.location)}: {i.reason} ({i.detail})"
        for i in scan.issues[:MAX_LISTED]
    ]


@contextmanager
def _slot() -> Iterator[None]:
    if not SLOTS.acquire(timeout=BUSY_WAIT_SECONDS):
        raise ToolError("the server is busy with other analyses; retry in a minute")
    try:
        yield
    finally:
        SLOTS.release()


@contextmanager
def _source(repo: str, ref: str) -> Iterator[Path]:
    """The repository unpacked in a temporary folder; tool errors for the failures an agent can act on."""
    installation = _installation.get()
    scoped = nullcontext()
    if installation is not None:
        from codeintent import github_app, mcp_tokens

        # The installation token reads this workspace's private repositories; any other repository
        # is fetched as the public would see it, so a token never reaches another workspace's code.
        if mcp_tokens.watches(installation, repo):
            scoped = repository.using(
                lambda: github_app.installation_token(installation)
            )
    with _slot(), repository.temporary() as folder, scoped:
        try:
            with _timed("download the repository", f"{repo}@{ref}"):
                root = repository.download(repo, ref, Path(folder), repository.token())
            yield root
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status == 404:
                raise ToolError(
                    f"{repo}@{ref} was not found on GitHub; check the owner/name and ref "
                    "(private repositories need the CodeIntent GitHub App installed on them)"
                ) from None
            if status in (403, 429):
                raise ToolError(
                    "GitHub refused the download (rate limit or access); retry later"
                ) from None
            raise ToolError(f"GitHub returned HTTP {status} for {repo}@{ref}") from None
        except httpx.HTTPError as error:
            raise ToolError(
                f"downloading {repo}@{ref} failed ({type(error).__name__}); retry later"
            ) from None
        except ValueError as error:  # size cap
            raise ToolError(str(error)) from None


@contextmanager
def _timed(name: str, detail: str | None = None) -> Iterator[dict]:
    """A timed step of the recorded tool call; a no-op when the call is not recorded."""
    run = _run.get()
    if run is None:
        yield {"detail": detail}
        return
    with run.step(name, detail) as note:
        yield note


def _summary(result: BaseModel) -> dict:
    """The headline of a tool's result, for listing calls without loading the full result."""
    data = result.model_dump(mode="json")
    keys = (
        "verdict",
        "reason",
        "package",
        "from_version",
        "to_version",
        "declared",
        "pinned",
    )
    summary = {k: data[k] for k in keys if k in data}
    for name in (
        "findings",
        "steps",
        "declarations",
        "dependencies",
        "affected",
        "unchecked",
    ):
        if isinstance(data.get(name), list):
            summary[name] = len(data[name])
    return summary


def _recorded(tool: str):
    """Record each call of a tool as an ``mcp`` run with its arguments, steps and full result.

    Recording is best effort: without a database, or if it fails, the tool still answers.
    """

    def wrap(fn):
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def call(*args, **kwargs):
            arguments = signature.bind(*args, **kwargs)
            arguments.apply_defaults()
            values = dict(arguments.arguments)
            if not os.getenv("DATABASE_URL"):
                return fn(*args, **kwargs)
            from codeintent import runs

            try:
                repo, ref = _parse_repo(str(values.get("repo") or ""))
            except ToolError:
                repo, ref = str(values.get("repo") or "")[:200] or None, None
            with ExitStack() as stack:
                run = None
                try:
                    run = stack.enter_context(
                        runs.recorded(
                            "mcp",
                            installation_id=_installation.get(),
                            repository=repo,
                            subject=tool,
                            ref=ref,
                            token_id=_token_id.get(),
                            input=values,
                        )
                    )
                except Exception as error:
                    logger.warning(
                        "Could not record %s (%s)", tool, type(error).__name__
                    )
                reset = _run.set(run)
                try:
                    result = fn(*args, **kwargs)
                except ToolError as error:
                    if run is not None:
                        run.finish("failed", error=f"ToolError: {error}"[:300])
                    raise
                finally:
                    _run.reset(reset)
                if run is not None:
                    run.finish(
                        summary=_summary(result), result=result.model_dump(mode="json")
                    )
                return result

        return call

    return wrap


@contextmanager
def _guard(tool: str) -> Iterator[None]:
    """Turn unexpected failures into a short tool error; the traceback stays in the server log."""
    try:
        yield
    except ToolError:
        raise
    except httpx.HTTPError as error:
        logger.warning("%s: upstream HTTP failure (%s)", tool, type(error).__name__)
        raise ToolError(
            f"an upstream service (PyPI, OSV or GitHub) failed ({type(error).__name__}); retry later"
        ) from None
    except Exception:
        logger.exception("%s failed", tool)
        raise ToolError(f"{tool} failed with an internal error; retry later") from None


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "CodeIntent-MCP/1.0"},
    )


def _matching(scan: ManifestScan, package: str) -> list[Dependency]:
    return [d for d in scan.dependencies if canonicalize_name(d.name) == package]


def _current(found: list[Dependency]) -> tuple[str | None, str | None]:
    """The single version the repo is on, and whether it came from a lock or an exact pin."""
    locked = {d.locked_version for d in found if d.format in LOCKS and d.locked_version}
    if len(locked) == 1:
        return next(iter(locked)), "lock"
    if len(locked) > 1:
        raise ToolError(
            f"the lock files name several versions ({', '.join(sorted(locked))}); pass from_version"
        )
    pinned = {d.locked_version for d in found if d.locked_version}
    if len(pinned) == 1:
        return next(iter(pinned)), "exact-pin"
    if len(pinned) > 1:
        raise ToolError(
            f"the manifests pin several versions ({', '.join(sorted(pinned))}); pass from_version"
        )
    return None, None


def _declaration(d: Dependency) -> Declaration:
    return Declaration(
        file=d.location.file,
        line=d.location.line,
        format=d.format,
        group=d.group,
        direct=d.direct,
        specifier=d.specifier,
        locked_version=d.locked_version,
    )


def _advisories(check: AdvisoryCheck) -> VersionAdvisories:
    return VersionAdvisories(
        package=check.package,
        version=check.version,
        status=check.status,
        detail=check.detail,
        advisories=[
            AdvisoryItem(
                id=a.id,
                aliases=list(a.aliases),
                summary=a.summary,
                severity=a.severity,
                fixed=a.fixed,
                url=a.url,
            )
            for a in check.active
        ],
    )


def _code(text: str | None) -> str:
    return f"`{text}`" if text else ""


def _step(finding: Finding, where: str, package: str, end: str) -> str:
    change = finding.change
    param, symbol = change.parameter, change.symbol
    if change.kind == "parameter-removed":
        action = f"stop passing {param}= to {_code(symbol)}"
        if change.replacement:
            action = f"replace {param}= with {change.replacement} in the call to {_code(symbol)}"
    elif change.kind == "removed":
        action = f"{_code(symbol)} no longer exists in {package} {end}"
        action += (
            f"; use {change.replacement} instead"
            if change.replacement
            else "; find its replacement"
        )
    elif change.kind == "parameter-required":
        action = f"pass {param}= explicitly to {_code(symbol)}; it is required in {end}"
    elif change.kind == "parameter-moved":
        action = f"adjust how {param} is passed to {_code(symbol)}: {change.detail}"
    elif change.kind == "default-changed":
        action = f"the default of {param}= in {_code(symbol)} changed ({change.detail}); pass the old value explicitly if you rely on it"
    else:  # deprecated
        action = f"move off deprecated {_code(symbol)}" + (
            f" (parameter {param}=)" if param else ""
        )
        if change.replacement:
            action += f"; use {change.replacement}"
    if change.kind in {"parameter-required", "deprecated"}:
        action += f" ({change.detail})"
    if change.message:
        action += f'; library says: "{change.message.strip()}"'
    prefix = "Optional (behind an import fallback): " if finding.guarded else ""
    return f"{prefix}In {where}, {action}"


def _excludes(specifier: str, version: str) -> bool:
    if not specifier:
        return False
    try:
        return not SpecifierSet(specifier).contains(version, prereleases=True)
    except (InvalidSpecifier, InvalidVersion):
        return False


def _steps(
    result: UpgradeVerdict, declarations: list[Dependency]
) -> tuple[list[str], bool]:
    steps: list[str] = []
    for finding in result.findings:
        for location in finding.locations:
            steps.append(_step(finding, _place(location), result.package, result.end))
    for item in result.unchecked:
        steps.append(
            f"Review {_place(item.location)} by hand: the analysis could not follow it "
            f"({item.reason}: {item.detail}) and it touches code that changed in {result.end}"
        )
    for d in declarations:
        if d.format in LOCKS:
            continue
        if not _excludes(d.specifier, result.end):
            continue
        written = _code(d.name + d.specifier)
        if d.pins and all(p.kind == "exact" for p in d.pins):
            steps.append(
                f"Change {written} at {_place(d.location)} to {_code(f'{d.name}=={result.end}')}"
            )
        else:
            steps.append(
                f"Relax {written} at {_place(d.location)}: it excludes {result.end}"
            )
    if any(d.format in LOCKS for d in declarations):
        locks = sorted({d.location.file for d in declarations if d.format in LOCKS})
        steps.append(
            f"Re-lock so {', '.join(locks)} resolve {result.package}=={result.end}"
        )
    steps = list(dict.fromkeys(steps))  # two uses on one line give one step
    truncated = len(steps) > MAX_STEPS
    return steps[:MAX_STEPS], truncated


def _release(result: UpgradeVerdict) -> ReleaseInfo | None:
    found = result.release
    if found is None:
        return None
    return ReleaseInfo(
        repository=found.repository,
        start_published=found.start.published,
        end_published=found.end.published,
        end_yanked=found.end.yanked,
        start_tag=found.start.tag,
        end_tag=found.end.tag,
        note=found.not_located,
    )


def brief(
    repo: str,
    ref: str,
    result: UpgradeVerdict,
    source: Literal["argument", "lock", "exact-pin"],
    declarations: list[Dependency],
) -> UpgradeBrief:
    """The compact, agent-facing form of an ``UpgradeVerdict``."""
    steps, cut = _steps(result, declarations)
    findings = [
        BriefFinding(
            severity=f.severity,
            guarded=f.guarded,
            locations=list(dict.fromkeys(_place(loc) for loc in f.locations)),
            change=Change(
                kind=f.change.kind,
                symbol=f.change.symbol,
                parameter=f.change.parameter,
                detail=f.change.detail,
                replacement=f.change.replacement,
                replacement_source=f.change.replacement_source,
                library_message=f.change.message,
                before=Place(**f.change.before.model_dump(include={"file", "line"}))
                if f.change.before
                else None,
                after=Place(**f.change.after.model_dump(include={"file", "line"}))
                if f.change.after
                else None,
            ),
        )
        for f in result.findings
    ]
    unchecked = [
        UncheckedItem(
            location=_place(u.location),
            reason=u.reason,
            detail=u.detail,
            symbol=u.symbol,
        )
        for u in result.unchecked
    ]
    return UpgradeBrief(
        repo=repo,
        ref=ref,
        package=result.package,
        from_version=result.start,
        from_version_source=source,
        to_version=result.end,
        verdict=result.verdict,
        label=result.label,
        reason=result.reason,
        steps=steps,
        findings=findings,
        unchecked=unchecked[:MAX_LISTED],
        limits_count=len(result.limits),
        declarations=[_declaration(d) for d in declarations][:MAX_LISTED],
        advisories=[_advisories(a) for a in result.advisories],
        release=_release(result),
        coverage=Coverage(**result.coverage.model_dump()) if result.coverage else None,
        truncated=cut or len(unchecked) > MAX_LISTED or len(declarations) > MAX_LISTED,
    )


_latest_cache: dict[str, tuple[float, str | None, str | None]] = {}
_latest_lock = threading.Lock()


def latest(name: str, client: httpx.Client) -> tuple[str | None, str | None]:
    """(latest non-yanked final release on PyPI, error) for ``name``; cached in memory for an hour."""
    key = canonicalize_name(name)
    with _latest_lock:
        hit = _latest_cache.get(key)
    if hit and time.monotonic() - hit[0] < LATEST_TTL:
        return hit[1], hit[2]
    version: str | None = None
    error: str | None = None
    try:
        response = client.get(f"{PYPI}/{key}/json")
        if response.status_code == 404:
            error = "not on PyPI"
        elif response.status_code != 200:
            error = f"PyPI returned HTTP {response.status_code}"
        else:
            version = _newest(response.json())
            error = None if version else "no non-yanked final release on PyPI"
    except (httpx.HTTPError, ValueError) as failure:
        error = f"PyPI lookup failed ({type(failure).__name__})"
    if error is None or error == "not on PyPI":
        with _latest_lock:
            _latest_cache[key] = (time.monotonic(), version, error)
    return version, error


def _newest(data: dict) -> str | None:
    releases: dict[str, list[dict]] = data.get("releases") or {}

    def usable(v: str) -> bool:
        files = releases.get(v) or []
        return bool(files) and not all(f.get("yanked") for f in files)

    info = (data.get("info") or {}).get("version")
    if info and usable(info) and not (data.get("info") or {}).get("yanked"):
        return info
    candidates = []
    for v in releases:
        try:
            parsed = Version(v)
        except InvalidVersion:
            continue
        if not parsed.is_prerelease and usable(v):
            candidates.append(parsed)
    return str(max(candidates)) if candidates else None


def _newer(current: str | None, newest: str | None) -> bool | None:
    if not current or not newest:
        return None
    try:
        return Version(newest) > Version(current)
    except InvalidVersion:
        return None


# ---------------------------------------------------------------- server

INSTRUCTIONS = """\
CodeIntent answers "what happens to this Python repository if dependency X moves to version Y?"
by statically comparing both releases of X against the repository's own code (nothing is executed
and no model is involved). Start with upgrade_brief for a specific upgrade and follow its `steps`;
use list_dependencies to find upgrade candidates, advisories for known vulnerabilities, and
why_pinned to see where a version restriction is declared. Repositories must be public on GitHub.
A verdict of "no-known-impact" never means "safe": it means every use was compared and nothing
relevant changed."""

server = MCPServer(
    "codeintent",
    title="CodeIntent dependency upgrade checks",
    instructions=INSTRUCTIONS,
    version="1.0.0",
)


@server.tool(title="Upgrade brief for one dependency", annotations=READ_ONLY)
@_recorded("upgrade_brief")
def upgrade_brief(
    repo: RepoArg,
    package: PackageArg,
    to_version: Annotated[
        str,
        Field(
            description="Target version, exact PEP 440 (e.g. '0.28.0'), or 'latest' for the newest "
            "non-yanked final release on PyPI.",
            min_length=1,
            max_length=64,
        ),
    ],
    from_version: Annotated[
        str | None,
        Field(
            description="Current version. Omit to read it from the repo's lock file or exact '==' pin."
        ),
    ] = None,
) -> UpgradeBrief:
    """Check what upgrading one Python dependency would break in a GitHub repository, and how to fix it.

    Downloads the repo at the ref, finds the current version (lock file, else exact pin, unless
    from_version is given), compares both releases' public API against every use in the repo, and
    returns: verdict (breaks | needs-change | not-checked | no-known-impact) with a reason; findings
    with consumer file:line locations, what changed, the replacement and the library's own
    deprecation message; uses that could not be checked; OSV advisories for both versions; and an
    ordered `steps` list to apply. Deterministic: same inputs give the same brief. Typically
    10-120 seconds on first run for a package (release files are cached afterwards).
    """
    name, ref = _parse_repo(repo)
    package = _package(package)
    start = _version(from_version, "from_version") if from_version else None
    with _guard("upgrade_brief"), _client() as client:
        end = _target(package, to_version, client)
        if start:
            _published(package, start, client)
        with _source(name, ref) as root, _timed(f"compare {package} → {end}") as note:
            brief = _upgrade_brief(name, ref, package, start, end, root, client)
            note["detail"] = f"{brief.verdict}: {brief.reason}"
            return brief


def _target(package: str, to_version: str, client: httpx.Client) -> str:
    if to_version.strip().lower() == "latest":
        newest, error = latest(package, client)
        if newest is None:
            raise ToolError(f"could not resolve the latest {package} release: {error}")
        return newest
    end = _version(to_version, "to_version")
    _published(package, end, client)
    return end


def _published(package: str, version: str, client: httpx.Client) -> None:
    try:
        artifacts.release(package, version, client)
    except artifacts.ArtifactError as error:
        if error.reason == "release-not-found":
            raise ToolError(
                f"{package} {version} is not on PyPI; check the version or use 'latest'"
            ) from None
        raise


def _upgrade_brief(
    name: str,
    ref: str,
    package: str,
    start: str | None,
    end: str,
    root: Path,
    client: httpx.Client,
) -> UpgradeBrief:
    scan = manifests.scan(root)
    found = _matching(scan, package)
    source: Literal["argument", "lock", "exact-pin"] = "argument"
    if start is None:
        current, kind = _current(found)
        if current is None:
            declared = ", ".join(
                f"{_place(d.location)} {d.specifier or '(any version)'}" for d in found
            )
            raise ToolError(
                f"could not tell which {package} version {name}@{ref} is on: "
                + (
                    f"it is declared without a lock or exact pin ({declared})"
                    if found
                    else "it is not declared in any supported manifest or lock file"
                )
                + "; pass from_version"
            )
        start, source = current, kind  # type: ignore[assignment]
    if Version(start) == Version(end):
        raise ToolError(f"{package} is already at {end} in {name}@{ref}")
    result = evaluate(package, start, end, root, client)
    return brief(name, ref, result, source, found)


@server.tool(title="Where a dependency is pinned", annotations=READ_ONLY)
@_recorded("why_pinned")
def why_pinned(repo: RepoArg, package: PackageArg) -> WhyPinned:
    """Show every place a GitHub repository declares or restricts one Python dependency.

    Returns each declaration in requirements files, pyproject.toml, setup.py/setup.cfg, uv.lock and
    poetry.lock with file:line, the specifier, the restrictive clauses (pins) and their kind (exact,
    upper_bound, exclusion, compatible, ...), dependency group and locked version, and for each deliberate
    pin the commit and pull request that added it, so its reason can be read before relaxing it.
    ``==`` lines in requirements files are version locks and are not traced.
    """
    name, ref = _parse_repo(repo)
    package = _package(package)
    with _guard("why_pinned"), _source(name, ref) as root:
        scan = manifests.scan(root)
        found = _matching(scan, package)
        declarations = [
            Pinning(
                **_introduced(name, ref, d),
                file=d.location.file,
                line=d.location.line,
                format=d.format,
                group=d.group,
                direct=d.direct,
                constraint_only=d.constraint_only,
                specifier=d.specifier,
                marker=d.marker,
                locked_version=d.locked_version,
                pins=[{"kind": p.kind, "clause": p.clause} for p in d.pins],
            )
            for d in found
        ]
        note = (
            "Pins come from the manifests and lock files. introduced_by quotes the commit and pull request "
            "that added each deliberate pin; whether it can be lifted depends on the upgrade it blocks, "
            "so run upgrade_brief to that version."
        )
        if not found:
            note = (
                f"{package} is not declared in any supported manifest or lock file of {name}@{ref}. "
                + note
            )
        return WhyPinned(
            repo=name,
            ref=ref,
            package=package,
            declared=bool(found),
            pinned=any(d.pins for d in declarations),
            declarations=declarations,
            note=note,
            manifest_issues=_issues(scan),
        )


def _introduced(name: str, ref: str, d: Dependency) -> dict:
    """``introduced_by`` / ``origin_detail`` for one declaration's first deliberate pin."""
    from codeintent.upgrades.upstream import GitHubCache, RateLimited, Repo

    chosen = pin_history.deliberate(d.pins, d.format)
    if not chosen or not d.location.line:
        return {}
    with _client() as http:
        try:
            found, detail = pin_history.origin(
                Repo(GitHubCache(http, repository.token()), name),
                ref,
                d.location.file,
                d.location.line,
                d.name,
                chosen[0].clause,
            )
        except (httpx.HTTPError, RateLimited, KeyError, LookupError) as error:
            found, detail = (
                None,
                f"git history could not be read: {type(error).__name__}",
            )
    return {"introduced_by": found, "origin_detail": detail}


def _direct(scan: ManifestScan) -> dict[str, list[Dependency]]:
    grouped: dict[str, list[Dependency]] = {}
    for d in scan.dependencies:
        grouped.setdefault(canonicalize_name(d.name), []).append(d)
    return {
        name: entries
        for name, entries in grouped.items()
        if any(d.direct for d in entries)
    }


@server.tool(title="Direct dependencies and newer releases", annotations=READ_ONLY)
@_recorded("list_dependencies")
def list_dependencies(repo: RepoArg) -> DependencyList:
    """List a GitHub repository's direct Python dependencies with current and latest PyPI versions.

    For each direct dependency: the locked (or exact '==') version, every declaration as
    'file:line specifier [group]', the latest non-yanked final release on PyPI, and whether a newer
    release exists. Use it to pick upgrade candidates, then call upgrade_brief on one. At most 300
    dependencies are looked up (truncated=true beyond that).
    """
    name, ref = _parse_repo(repo)
    with _guard("list_dependencies"), _source(name, ref) as root, _client() as client:
        scan = manifests.scan(root)
        direct = _direct(scan)
        names = sorted(direct)[:MAX_DEPENDENCIES]
        rows: list[DependencyStatus] = []
        lookups: dict[str, Any] = {}
        registry = [n for n in names if any(d.source == "registry" for d in direct[n])]
        with ThreadPoolExecutor(max_workers=LATEST_WORKERS) as pool:
            for package, answer in zip(
                registry, pool.map(lambda n: latest(n, client), registry)
            ):
                lookups[package] = answer
        for package in names:
            entries = direct[package]
            try:
                current, kind = _current(entries)
                note = None
            except ToolError as conflict:
                current, kind, note = None, None, str(conflict)
            newest, error = lookups.get(package, (None, "not installed from PyPI"))
            rows.append(
                DependencyStatus(
                    name=package,
                    current=current,
                    current_source=kind,  # type: ignore[arg-type]
                    declared=[
                        f"{_place(d.location)} {d.specifier or '(any)'} [{d.group}]"
                        for d in entries
                        if d.format not in LOCKS
                    ][:10],
                    latest=newest,
                    newer_available=_newer(current, newest),
                    blocked_by=[
                        f"{_place(d.location)} {d.specifier}"
                        for d in entries
                        if d.format not in LOCKS
                        and newest
                        and _excludes(d.specifier, newest)
                    ],
                    note=note or error,
                )
            )
        return DependencyList(
            repo=name,
            ref=ref,
            total=len(direct),
            returned=len(rows),
            truncated=len(direct) > len(rows),
            dependencies=rows,
            manifest_issues=_issues(scan),
        )


@server.tool(
    title="Known vulnerabilities in locked dependencies", annotations=READ_ONLY
)
@_recorded("advisories")
def advisories(repo: RepoArg) -> AdvisoryReport:
    """List known OSV.dev vulnerability advisories for every locked or exactly pinned dependency of a GitHub repo.

    Covers direct and transitive packages from lock files and '==' pins (up to 300 distinct
    package versions). Returns `affected` (with advisory id, summary, severity, first fixed version
    and URL), `not_checked` with the reason, `none_known`, and `unpinned` dependencies that have no
    exact version and so cannot be looked up. A lookup failure is reported as not_checked, never as
    none_known.
    """
    name, ref = _parse_repo(repo)
    with _guard("advisories"), _source(name, ref) as root, _client() as client:
        scan = manifests.scan(root)
        seen: dict[tuple[str, str], Dependency] = {}
        unpinned: set[str] = set()
        for d in scan.dependencies:
            key = canonicalize_name(d.name)
            if d.locked_version:
                seen.setdefault((key, d.locked_version), d)
            elif d.source == "registry":
                unpinned.add(key)
        pinned_names = {k for k, _ in seen}
        pairs = list(seen.values())
        lookups = pairs[:MAX_DEPENDENCIES]
        checks = osv.check_dependencies(lookups, client)
        affected, failed, clean = [], [], []
        for check in checks:
            if check.status == "advisories" and check.active:
                affected.append(_advisories(check))
            elif check.status == "not-checked":
                failed.append(_advisories(check))
            else:
                clean.append(f"{check.package}=={check.version}")
        return AdvisoryReport(
            repo=name,
            ref=ref,
            checked=len(lookups),
            truncated=len(pairs) > len(lookups),
            affected=affected,
            not_checked=failed,
            none_known=sorted(clean),
            unpinned=sorted(unpinned - pinned_names),
            manifest_issues=_issues(scan),
        )


# ---------------------------------------------------------------- HTTP app


class ImpactLine(BaseModel):
    repository: str
    file: str
    line: int | None = None
    code: str | None = Field(
        None, description="The code at that place, as last scanned."
    )
    symbol: str
    change: str = Field(description="What changed, e.g. 'httpx.Client(proxies=)'.")
    kind: str
    version: str = Field(description="The release that made the change.")
    replacement: str | None = None
    locked: str | None = Field(
        None, description="The version this repository locks now."
    )
    confirmed: bool = Field(
        description="True when a run compared this upgrade for this repository; false when the line was "
        "found through the workspace graph alone (same symbol and argument, never compared there)."
    )


class Impact(BaseModel):
    package: str
    version: str | None
    repositories: list[str]
    lines: list[ImpactLine]
    note: str


class SymbolUse(BaseModel):
    repository: str
    file: str
    line: int | None = None
    code: str | None = None
    symbol: str
    kind: str | None = None
    keywords: list[str] = []


class Usages(BaseModel):
    package: str
    symbol: str | None
    uses: list[SymbolUse]
    note: str


def _workspace() -> int:
    installation = _installation.get()
    if installation is None:
        raise ToolError(
            "this tool reads your workspace graph: connect with a workspace token from the CodeIntent "
            "dashboard (AI agents tile)"
        )
    return installation


@server.tool(
    title="What a library change breaks across all your repositories",
    annotations=READ_ONLY,
)
@_recorded("impact")
def impact(
    package: PackageArg,
    version: Annotated[
        str | None,
        Field(
            description="The release whose changes to check, e.g. '0.28.1'. Omit for every known change.",
            max_length=64,
        ),
    ] = None,
) -> Impact:
    """List every line in your workspace's repositories that a known change in one Python library touches.

    Answered from the workspace graph that CodeIntent builds from every PR check and daily scan: the
    changes found anywhere in your repositories, joined to every place your default branches use the same
    symbol (and pass the same argument, for argument changes). Lines with confirmed=false were found
    through the graph alone: the same use in a repository whose upgrade has not been compared yet.
    Instant: nothing is downloaded. Needs a workspace token.
    """
    from codeintent import graph, workspace_graph

    ws = _workspace()
    name = _package(package)
    with (
        _guard("impact"),
        _timed("query the workspace graph") as note,
        graph.driver() as db,
    ):
        rows = workspace_graph.impact(db, ws, name, version)
        note["detail"] = f"{len(rows)} line(s)"
    return Impact(
        package=name,
        version=version,
        repositories=sorted({r["repository"] for r in rows}),
        lines=[ImpactLine(**r) for r in rows],
        note=(
            "From the workspace graph: changes found by earlier runs, joined to every current use. "
            "Run upgrade_brief on a repository to confirm and get exact steps."
            if rows
            else f"No known change in {name} touches code in your repositories. Changes are known once a "
            "PR check or scan has compared a release; run upgrade_brief to compare one now."
        ),
    )


@server.tool(title="Where your repositories use a library", annotations=READ_ONLY)
@_recorded("who_uses")
def who_uses(
    package: PackageArg,
    symbol: Annotated[
        str | None,
        Field(
            description="A public name such as 'httpx.Client'; omit for every use.",
            max_length=300,
        ),
    ] = None,
) -> Usages:
    """List where your workspace's default branches use one Python library, or one name in it.

    From the workspace graph (the latest scan of each repository), with file:line, the code there, how it
    is used (call, import, subclass, ...) and the keyword arguments passed. Needs a workspace token.
    """
    from codeintent import graph, workspace_graph

    ws = _workspace()
    name = _package(package)
    with (
        _guard("who_uses"),
        _timed("query the workspace graph") as note,
        graph.driver() as db,
    ):
        rows = workspace_graph.usages(db, ws, name, symbol)
        note["detail"] = f"{len(rows)} use(s)"
    return Usages(
        package=name,
        symbol=symbol,
        uses=[SymbolUse(**r) for r in rows],
        note=(
            "From each repository's latest default-branch scan; at most 500 uses."
            if rows
            else f"No scanned repository uses {name}"
            + (f" ({symbol})" if symbol else "")
            + ". Uses are recorded for dependencies with a newer release."
        ),
    )


class DependencyPath(BaseModel):
    repo: str
    package: str
    chains: list[list[str]] = Field(
        description="Shortest chains 'package@version' from a direct dependency to the package, shortest first."
    )
    note: str


class Dependent(BaseModel):
    kind: str = Field(
        description="Repository (yours) or SourceRepo (a public open-source project)."
    )
    name: str
    stars: int | None = None
    hops: int = Field(
        description="0 = depends on it directly; 1+ = through that many other packages."
    )
    via: list[str] = []


class Dependents(BaseModel):
    package: str
    known: bool
    source: dict | None = None
    needs: list[str] = []
    needed_by: list[str] = []
    advisories: list[dict] = []
    dependents: list[Dependent] = []
    note: str


@server.tool(
    title="Why a package is in a repository's dependency tree", annotations=READ_ONLY
)
@_recorded("dependency_path")
def dependency_path(repo: RepoArg, package: PackageArg) -> DependencyPath:
    """Explain why a Python package is installed in one of your repositories: the shortest chains of
    dependencies from what the repository declares to that package, from the ecosystem graph (resolved
    dependency trees of every release your repositories lock). Needs a workspace token.
    """
    from codeintent import ecosystem, graph, mcp_tokens

    ws = _workspace()
    name, _ = _parse_repo(repo)
    target = _package(package)
    if not mcp_tokens.watches(ws, name):
        raise ToolError(f"{name} is not a repository of this workspace")
    with (
        _guard("dependency_path"),
        _timed("query the ecosystem graph") as note,
        graph.driver() as db,
    ):
        chains = ecosystem.why(db, ws, name, target)
        note["detail"] = f"{len(chains)} chain(s)"
    return DependencyPath(
        repo=name,
        package=target,
        chains=chains,
        note=(
            "Each chain starts at a dependency the repository declares; a one-element chain means it is declared directly."
            if chains
            else f"{target} is not in the known dependency tree of {name}. Trees are known after the repository's first scan."
        ),
    )


@server.tool(
    title="Who depends on a package, across the ecosystem graph", annotations=READ_ONLY
)
@_recorded("dependents")
def dependents(package: PackageArg) -> Dependents:
    """Describe one Python package from the ecosystem graph: its source repository (stars, licence, OpenSSF
    Scorecard), what it depends on, which packages depend on it, known advisories, and every one of your
    repositories and indexed open-source projects that depend on it, directly or transitively.
    """
    from codeintent import ecosystem, graph

    ws = _installation.get() or 0
    name = _package(package)
    with (
        _guard("dependents"),
        _timed("query the ecosystem graph") as note,
        graph.driver() as db,
    ):
        found = ecosystem.package(db, ws, name)
        note["detail"] = f"{len(found.get('dependents') or [])} dependent(s)"
    if not found.get("known"):
        return Dependents(
            package=name,
            known=False,
            note=f"{name} is not in the ecosystem graph yet; it is added when a watched or indexed project uses it.",
        )
    return Dependents(
        package=name,
        known=True,
        source=found.get("source"),
        needs=sorted(found.get("needs") or []),
        needed_by=sorted(found.get("needed_by") or []),
        advisories=found.get("advisories") or [],
        dependents=[Dependent(**d) for d in found.get("dependents") or []],
        note="From the public ecosystem graph (deps.dev, OSV.dev and indexed GitHub projects) and your workspace.",
    )


class Affected(BaseModel):
    function: str | None = None
    file: str
    line: int | None = None
    depth: int = Field(
        description="Calls or imports away from the broken line (1 = direct)."
    )
    entry: str | None = Field(
        None,
        description="Route, command or task this function serves, e.g. 'GET /users'.",
    )


class Edit(BaseModel):
    file: str
    line: int | None = None
    code: str | None = Field(None, description="The statement there, as checked.")
    function: str | None = Field(None, description="The function the line is in.")
    severity: str
    change: Change
    step: str = Field(description="What to change, in one sentence.")
    upstream_pr: str | None = Field(
        None, description="The library PR that made the change."
    )
    upstream_quote: str | None = None
    callers: list[Affected] = Field(
        [],
        description="Code that calls the function, from the workspace graph: check it still works.",
    )
    importers: list[str] = Field([], description="Files that import this file.")
    entry_points: list[str] = Field(
        [], description="Routes, commands, tasks and scripts that reach this line."
    )
    tests: list[str] = Field(
        [], description="Test files that reach this line: run them."
    )


class UpgradeFix(BaseModel):
    package: str
    from_version: str
    to_version: str
    verdict: str
    reason: str
    edits: list[Edit]
    unchecked: list[UncheckedItem] = Field(
        [],
        description="Uses touching changed code that static analysis could not follow: review by hand.",
    )
    reach: dict | None = Field(
        None,
        description="Where the package reaches the code: its own uses, and chains through other dependencies.",
    )


class FixBrief(BaseModel):
    repo: str
    pull: int
    head_sha: str | None
    checked_at: str
    verdict: str | None
    upgrades: list[UpgradeFix]
    tests_to_run: list[str]
    steps: list[str] = Field(description="Every edit as one ordered checklist.")
    then: str


@server.tool(title="Everything needed to fix one dependency PR", annotations=READ_ONLY)
@_recorded("fix_brief")
def fix_brief(
    repo: RepoArg,
    pull: Annotated[int, Field(description="The pull request number.", ge=1)],
) -> FixBrief:
    """Get the fix list for a dependency pull request that CodeIntent has checked.

    Use this when asked to fix CodeIntent's findings on a PR. For each upgraded package it returns every
    edit with the file, line, the code there, the function it is in, what changed in the library and the
    upstream PR behind it, the replacement, and, from the workspace graph, the callers, importing files,
    routes/commands and tests that reach the line. Then a single ordered checklist and the tests to run.
    Instant: it reads the latest check of the PR, nothing is downloaded. Needs a workspace token.
    """
    from codeintent import breaks, store

    ws = _workspace()
    name, _ = _parse_repo(repo)
    with _guard("fix_brief"), _timed("read the latest check") as note:
        with store.connection() as conn:
            run = conn.execute(
                """SELECT id,ref,result,summary,finished_at FROM ci_runs
                WHERE installation_id=%s AND kind='pull' AND lower(repository)=lower(%s) AND subject=%s
                  AND status IN ('succeeded','partial') ORDER BY started_at DESC LIMIT 1""",
                (ws, name, f"#{pull}"),
            ).fetchone()
            code = {
                (p.get("file"), p.get("line")): p.get("code")
                for r in conn.execute(
                    """SELECT places FROM ci_breaks WHERE installation_id=%s AND lower(repository)=lower(%s)
                    AND source='pull' AND pull_number=%s""",
                    (ws, name, pull),
                ).fetchall()
                for p in r["places"] or []
            }
        if not run:
            raise ToolError(
                f"CodeIntent has not checked {name}#{pull} yet (or it is not in your workspace); "
                "it checks dependency PRs when they open or change"
            )
        note["detail"] = f"run {run['id']}"
    result = run["result"] or {}
    graph = result.get("graph") or {}
    upgrades, steps, tests = [], [], set()
    for raw in result.get("verdicts") or []:
        verdict = UpgradeVerdict.model_validate(raw)
        traced = graph.get(verdict.package) or {}
        blast = {(b["file"], b["line"]): b for b in traced.get("blast") or []}
        edits = []
        for index, finding in enumerate(verdict.findings):
            decision = (
                breaks._decision(raw, raw["findings"][index]["change"], index) or {}
            )
            quote = next(
                (
                    q.get("text")
                    for q in decision.get("quotes") or []
                    if q.get("source_kind") != "pr-title"
                ),
                None,
            )
            for loc in dict.fromkeys(finding.locations):
                where = blast.get((loc.file, loc.line)) or {}
                step = _step(finding, _place(loc), verdict.package, verdict.end)
                steps.append(step)
                tests.update(where.get("tests") or [])
                edits.append(
                    Edit(
                        file=loc.file,
                        line=loc.line,
                        code=code.get((loc.file, loc.line)),
                        function=where.get("function"),
                        severity=finding.severity,
                        change=Change(
                            kind=finding.change.kind,
                            symbol=finding.change.symbol,
                            parameter=finding.change.parameter,
                            detail=finding.change.detail,
                            replacement=finding.change.replacement,
                            replacement_source=finding.change.replacement_source,
                            library_message=finding.change.message,
                        ),
                        step=step,
                        upstream_pr=decision.get("pr_url"),
                        upstream_quote=quote,
                        callers=[
                            Affected(
                                function=c.get("function"),
                                file=c["file"],
                                line=c.get("line"),
                                depth=c.get("depth") or 1,
                                entry=c.get("entry"),
                            )
                            for c in where.get("callers") or []
                        ],
                        importers=[i["file"] for i in where.get("importers") or []],
                        entry_points=sorted(
                            {e["name"] for e in where.get("entry_points") or []}
                        ),
                        tests=where.get("tests") or [],
                    )
                )
        for item in verdict.unchecked:
            steps.append(
                f"Review {_place(item.location)} by hand: the analysis could not follow it "
                f"({item.reason}: {item.detail})"
            )
        upgrades.append(
            UpgradeFix(
                package=verdict.package,
                from_version=verdict.start,
                to_version=verdict.end,
                verdict=verdict.verdict,
                reason=verdict.reason,
                edits=edits,
                unchecked=[
                    UncheckedItem(
                        location=_place(u.location),
                        reason=u.reason,
                        detail=u.detail,
                        symbol=u.symbol,
                    )
                    for u in verdict.unchecked[:MAX_LISTED]
                ],
                reach=traced.get("reach"),
            )
        )
    tested = sorted(tests)
    if tested:
        steps.append("Run " + ", ".join(tested))
    return FixBrief(
        repo=name,
        pull=pull,
        head_sha=run["ref"],
        checked_at=run["finished_at"].isoformat(),
        verdict=(run["summary"] or {}).get("verdict"),
        upgrades=upgrades,
        tests_to_run=tested,
        steps=list(dict.fromkeys(steps))[:MAX_STEPS],
        then="Commit the edits to the PR's branch and push; CodeIntent checks the PR again and marks "
        "each fixed break as fixed.",
    )


class BearerAuth:
    """Reject HTTP requests without a valid ``Authorization: Bearer`` token (constant-time compares).

    ``token`` is the deployment's own token (public repositories only). With ``workspaces``, a CodeIntent
    workspace token (``ci_mcp_…``) also works and scopes the request to its installation.
    """

    def __init__(self, app: ASGIApp, token: str | None, workspaces: bool = False):
        self.app = app
        self.expected = token.encode() if token else None
        self.workspaces = workspaces

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = b""
        for key, value in scope.get("headers", ()):
            if key == b"authorization":
                header = value
                break
        scheme, _, supplied = header.partition(b" ")
        supplied = supplied.strip()
        if scheme.lower() == b"bearer" and supplied:
            if self.expected and hmac.compare_digest(supplied, self.expected):
                await self.app(scope, receive, send)
                return
            if self.workspaces:
                from starlette.concurrency import run_in_threadpool

                from codeintent import mcp_tokens

                resolved = await run_in_threadpool(
                    mcp_tokens.resolve_token, supplied.decode("utf-8", "replace")
                )
                if resolved is not None:
                    reset = _installation.set(resolved[0])
                    reset_token = _token_id.set(resolved[1])
                    try:
                        await self.app(scope, receive, send)
                    finally:
                        _token_id.reset(reset_token)
                        _installation.reset(reset)
                    return
        response = JSONResponse(
            {
                "error": "invalid_token",
                "error_description": "send Authorization: Bearer <your CodeIntent MCP token>",
            },
            status_code=401,
            headers={"WWW-Authenticate": 'Bearer realm="codeintent-mcp"'},
        )
        await response(scope, receive, send)


def configured_token() -> str | None:
    """CODEINTENT_MCP_TOKEN; refuses to run without it in production, warns otherwise."""
    token = os.getenv("CODEINTENT_MCP_TOKEN", "").strip()
    if token:
        if len(token) < 32:
            logger.warning(
                "CODEINTENT_MCP_TOKEN is shorter than 32 characters; use a random secret"
            )
        return token
    if os.getenv("CODEINTENT_ENV", "").lower() == "production":
        raise RuntimeError(
            "CODEINTENT_MCP_TOKEN must be set when CODEINTENT_ENV=production"
        )
    logger.warning(
        "CODEINTENT_MCP_TOKEN is not set: the MCP endpoint accepts unauthenticated requests "
        "(development only)"
    )
    return None


def _transport_security(token: str | None) -> TransportSecuritySettings | None:
    hosts = [
        h.strip()
        for h in os.getenv("CODEINTENT_MCP_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    ]
    if hosts:
        return TransportSecuritySettings(
            allowed_hosts=[*hosts, *(f"{h}:*" for h in hosts if ":" not in h)],
            allowed_origins=[f"https://{h}" for h in hosts],
        )
    if token:
        # Every request must carry the bearer token, which a DNS-rebinding page cannot supply.
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return None  # SDK default: localhost-only Host/Origin allowlist


def mcp_app(token: str | None, path: str = "/mcp", workspaces: bool = False) -> ASGIApp:
    """The streamable HTTP endpoint at ``path`` behind bearer auth.

    A host app that mounts this must run ``server.session_manager.run()`` in its own lifespan.
    ``workspaces`` accepts per-installation tokens (see ``codeintent.mcp_tokens``).
    """
    app = server.streamable_http_app(
        streamable_http_path=path,
        stateless_http=True,
        transport_security=_transport_security(
            token or ("workspaces" if workspaces else None)
        ),
    )
    return BearerAuth(app, token, workspaces) if token or workspaces else app


def create_app() -> Starlette:
    """Standalone ASGI app: ``/mcp`` (authenticated) and ``/healthz`` (open, no data)."""
    token = configured_token()
    endpoint = mcp_app(token)

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with server.session_manager.run():
            yield

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return Starlette(
        routes=[Route("/healthz", health), Mount("/", app=endpoint)],
        lifespan=lifespan,
    )
