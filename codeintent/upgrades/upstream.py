"""Explain each API change with the upstream decision behind it: the pull request that made it.

For every change the verdict engine found, the commits between the two release tags that touched the file
holding the symbol are read, and the one whose diff removes (or adds) the exact definition, parameter or
deprecation message wins. That commit is mapped to its pull request, and the pull request's title, body,
linked issues, commit message and changelog lines are searched for short sentences that mention the
symbol. Nothing is guessed:

- every quote is a verbatim substring of the text GitHub returned (checked in code, after whitespace
  normalisation) and quotes that fail the check are dropped;
- when no commit in the range matches, the change gets ``not_found`` with the reason, never a guess;
- a removal that was announced by a deprecation earlier (the change carries the warning ``message``) also
  gets the pull request that introduced that message, found by blaming the line at the start tag and
  walking past edits that only reworded it (e.g. a version bump in "will be removed in X");
- a removal is checked for a reversal: a later commit on the default branch that put the definition back.

GitHub responses are cached on disk keyed by URL. Anything addressed by commit SHA (compare, commit
details, trees, file contents, blame) is immutable and kept forever; pull requests, issues and listings of
the default branch expire after 24 hours and are revalidated with ``If-None-Match``. When the core rate
limit runs low the remaining changes get ``not_found="rate limited"`` instead of an error.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlencode

import httpx

from codeintent.upgrades import cache
from codeintent.upgrades.models import APIChange, Record, ReleaseRange
from codeintent.upgrades.repository import token

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
CACHE = (
    Path(
        os.getenv(
            "CODEINTENT_ARTIFACT_CACHE",
            Path.home() / ".cache" / "codeintent" / "artifacts",
        )
    ).parent
    / "github"
)
MUTABLE_TTL = 24 * 3600
"""Pull requests, issues and default-branch listings can change; everything addressed by SHA cannot."""
RATE_RESERVE = int(os.getenv("CODEINTENT_GITHUB_RESERVE", 25))
"""Stop before the core or GraphQL budget drops to this, so other work keeps some requests."""
MAX_REQUESTS = int(os.getenv("CODEINTENT_UPSTREAM_MAX_REQUESTS", 500))
"""Uncached GitHub requests one ``explain`` call may make; later changes get ``not_found``."""
MAX_COMPARE_PAGES = 10
MAX_HISTORY_PAGES = 3
MAX_CANDIDATES = 40
"""Commit details read per file and range; the newest are read first."""
MAX_LINEAGE = 5
"""Blame hops past commits that only edited the deprecation message."""
MAX_REVERSAL_COMMITS = 20
MAX_ISSUES = 3
MAX_QUOTES = 8
MAX_QUOTE_CHARS = 300
CHANGELOG = re.compile(
    r"(^|/)(changes|changelog|history|news|release[-_ ]?notes)[^/]*$"
    r"|(^|/)(newsfragments|changelog\.d|changelog|changes|news)/",
    re.IGNORECASE,
)
SQUASH_PR = re.compile(r"\(#(\d+)\)\s*$", re.MULTILINE)
LINKED = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+(?:(?P<repo>[\w.-]+/[\w.-]+)#|https://github\.com/(?P<url>[\w.-]+/[\w.-]+)/issues/|#)(?P<number>\d+)",
    re.IGNORECASE,
)
LITERAL = re.compile(r"""[rRbBuUfF]{0,2}("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")
WORD = re.compile(r"[A-Za-z0-9_]+")
BLOCK_START = re.compile(r"^(?:[-*+>#|]|\d+[.)]\s|\[[ xX]\]|\.\.\s|:\w+:|<!--)")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z`'\"(\[*])")
FENCE = re.compile(r"^\s*(```|~~~)")
WEAK = frozenset(
    {
        "args",
        "content",
        "data",
        "default",
        "encoding",
        "file",
        "files",
        "json",
        "key",
        "method",
        "mode",
        "name",
        "path",
        "test",
        "text",
        "timeout",
        "type",
        "url",
        "value",
    }
)
"""Names too common to quote a sentence on their own; such sentences must name them qualified."""
CONTEXT_NOUNS = "module|command|argument|parameter|function|class|attribute|keyword|option|kwarg|method"
REMOVAL = {"removed", "parameter-removed"}

SourceKind = Literal["pr-body", "pr-title", "commit-message", "issue", "changelog"]
Confidence = Literal["exact", "related"]


class Quote(Record):
    text: str
    source_url: str
    source_kind: SourceKind
    mentions: str
    """The name the quote was selected for: the changed symbol or parameter, or its enclosing module."""


class ChangeKey(Record):
    symbol: str
    parameter: str | None = None
    kind: str


class Origin(Record):
    """The pull request (or bare commit) that introduced the deprecation a removal followed."""

    pr_number: int | None = None
    pr_title: str | None = None
    pr_url: str | None = None
    merged_at: str | None = None
    commit: str
    commit_url: str
    confidence: Confidence


class UpstreamDecision(Record):
    change_key: ChangeKey
    pr_number: int | None = None
    pr_title: str | None = None
    pr_url: str | None = None
    merged_at: str | None = None
    author: str | None = None
    commit: str | None = None
    commit_url: str | None = None
    linked_issues: tuple[int, ...] = ()
    quotes: tuple[Quote, ...] = ()
    deprecation: Origin | None = None
    reversal: str | None = None
    confidence: Confidence | None = None
    evidence: str | None = None
    """What the chosen commit's diff does, e.g. "removes 4 line(s) defining proxies in httpx/_client.py"."""
    not_found: str | None = None
    limits: tuple[str, ...] = ()
    """What was capped or skipped (truncated compare, unread commits), so a miss can be judged."""


class RateLimited(Exception):
    """GitHub's rate limit (or this module's request budget) is spent; ``str()`` is the reason to report."""


def normalise(text: str) -> str:
    return " ".join(text.split())


def verified(text: str, source: str) -> bool:
    """The honesty rule: a quote must be a substring of the fetched source, whitespace aside."""
    return bool(text.strip()) and normalise(text) in normalise(source)


# --------------------------------------------------------------------------------------------- GitHub


class GitHubCache:
    """GET (and GraphQL POST) against GitHub with an on-disk cache, ETags and a rate-limit floor."""

    def __init__(self, client: httpx.Client, secret: str | None):
        self.client = client
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "CodeIntent/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if secret:
            self.headers["Authorization"] = f"Bearer {secret}"
        self.authenticated = bool(secret)
        self.remaining: dict[str, int] = {}
        self.calls = 0
        self.hits = 0
        self.revalidated = 0

    @staticmethod
    def _path(key: str) -> Path:
        name = cache.digest(key)
        return CACHE / name[:2] / f"{name}.json"

    def _guard(self, resource: str) -> None:
        left = self.remaining.get(resource)
        if left is not None and left <= RATE_RESERVE:
            raise RateLimited("rate limited")
        if self.calls >= MAX_REQUESTS:
            raise RateLimited(f"request budget of {MAX_REQUESTS} GitHub calls reached")

    def _track(self, response: httpx.Response) -> None:
        left = response.headers.get("x-ratelimit-remaining")
        if left is not None and left.isdigit():
            resource = response.headers.get("x-ratelimit-resource", "core")
            self.remaining[resource] = int(left)
        if response.status_code in (403, 429) and (
            response.headers.get("x-ratelimit-remaining") == "0"
            or "rate limit" in response.text.lower()
            or response.headers.get("retry-after")
        ):
            raise RateLimited("rate limited")

    def get(
        self,
        url: str,
        params: dict | None = None,
        *,
        ttl: float | None = None,
        shape: Callable[[object], object] | None = None,
        resource: str = "core",
    ) -> tuple[object | None, dict]:
        """``(data, meta)``; data is ``None`` for 404/409/422 answers, which are cached like any other."""
        if params:
            url = f"{url}?{urlencode(sorted(params.items()))}"
        path = self._path(url)
        entry = cache.read_json(path)
        if entry is not None and (
            ttl is None or time.time() - entry.get("fetched", 0) < ttl
        ):
            self.hits += 1
            return entry.get("data"), entry.get("meta", {})
        if resource:
            self._guard(resource)
        headers = (
            dict(self.headers)
            if url.startswith(API)
            else {"User-Agent": "CodeIntent/1.0"}
        )
        if url.startswith(RAW) and "Authorization" in self.headers:
            headers["Authorization"] = self.headers["Authorization"]
        if entry is not None and entry.get("etag"):
            headers["If-None-Match"] = entry["etag"]
        response = self.client.get(url, headers=headers)
        self.calls += 1
        self._track(response)
        if response.status_code == 304 and entry is not None:
            self.revalidated += 1
            entry["fetched"] = time.time()
            cache.write_json(path, entry)
            return entry.get("data"), entry.get("meta", {})
        if response.status_code in (404, 409, 410, 422):
            data, meta = None, {"status": response.status_code}
        elif response.status_code == 200:
            body = response.text if url.startswith(RAW) else response.json()
            data = shape(body) if shape else body
            meta = {"next": 'rel="next"' in response.headers.get("link", "")}
        else:
            response.raise_for_status()
            raise httpx.HTTPStatusError(
                f"unexpected HTTP {response.status_code}",
                request=response.request,
                response=response,
            )
        cache.write_json(
            path,
            {
                "url": url,
                "fetched": time.time(),
                "etag": response.headers.get("etag"),
                "meta": meta,
                "data": data,
            },
        )
        return data, meta

    def graphql(self, query: str, variables: dict) -> dict | None:
        """GraphQL POST for immutable data (blame at a commit), cached forever; None without a token."""
        if not self.authenticated:
            return None
        key = "graphql:" + query + json.dumps(variables, sort_keys=True)
        path = self._path(key)
        entry = cache.read_json(path)
        if entry is not None:
            self.hits += 1
            return entry.get("data")
        self._guard("graphql")
        response = self.client.post(
            f"{API}/graphql",
            headers=self.headers,
            json={"query": query, "variables": variables},
        )
        self.calls += 1
        self._track(response)
        if response.status_code != 200:
            return None
        payload = response.json()
        if payload.get("errors") or not payload.get("data"):
            return None
        cache.write_json(path, {"fetched": time.time(), "data": payload["data"]})
        return payload["data"]


def _commit_shape(data) -> dict:
    return {
        "sha": data["sha"],
        "html_url": data.get("html_url"),
        "message": data["commit"]["message"],
        "date": data["commit"]["committer"]["date"],
        "author": (data.get("author") or {}).get("login")
        or data["commit"]["author"].get("name"),
        "parents": [p["sha"] for p in data.get("parents", [])],
        "files": [
            {
                "filename": f["filename"],
                "previous_filename": f.get("previous_filename"),
                "status": f["status"],
                "patch": f.get("patch"),
            }
            for f in data.get("files", [])
        ],
    }


def _listing_shape(rows) -> list[dict]:
    return [
        {
            "sha": r["sha"],
            "date": r["commit"]["committer"]["date"],
            "title": r["commit"]["message"].split("\n", 1)[0],
        }
        for r in rows
    ]


def _compare_shape(data) -> dict:
    return {
        "total_commits": data.get("total_commits"),
        "merge_base": (data.get("merge_base_commit") or {}).get("sha"),
        "merge_base_date": ((data.get("merge_base_commit") or {}).get("commit") or {})
        .get("committer", {})
        .get("date"),
        "commits": _listing_shape(data.get("commits", [])),
    }


def _pr_shape(pr) -> dict:
    return {
        "number": pr["number"],
        "title": pr.get("title") or "",
        "body": pr.get("body") or "",
        "html_url": pr.get("html_url"),
        "merged_at": pr.get("merged_at"),
        "merge_commit_sha": pr.get("merge_commit_sha"),
        "author": (pr.get("user") or {}).get("login"),
        "base": (pr.get("base") or {}).get("ref"),
    }


def _issue_shape(issue) -> dict:
    return {
        "number": issue["number"],
        "title": issue.get("title") or "",
        "body": issue.get("body") or "",
        "html_url": issue.get("html_url"),
    }


class Repo:
    """The GitHub calls this module makes for one repository."""

    def __init__(self, gh: GitHubCache, full_name: str):
        self.gh = gh
        self.name = full_name
        self.base = f"{API}/repos/{full_name}"

    def compare(self, start: str, end: str) -> tuple[dict, bool]:
        commits: list[dict] = []
        first: dict | None = None
        for page in range(1, MAX_COMPARE_PAGES + 1):
            data, meta = self.gh.get(
                f"{self.base}/compare/{start}...{end}",
                {"per_page": 100, "page": page},
                shape=_compare_shape,
            )
            if data is None:
                break
            first = first or data
            commits += data["commits"]
            if not meta.get("next") or not data["commits"]:
                return {**(first or {}), "commits": commits}, False
        if first is None:
            raise LookupError(f"GitHub could not compare {start[:12]}...{end[:12]}")
        return {**first, "commits": commits}, len(commits) < (
            first.get("total_commits") or 0
        )

    def history(
        self,
        ref: str | None,
        path: str,
        since: str | None,
        *,
        ttl: float | None = None,
        pages: int = MAX_HISTORY_PAGES,
    ) -> tuple[list[dict], bool]:
        rows: list[dict] = []
        params = {"path": path, "per_page": 100}
        if ref:
            params["sha"] = ref
        if since:
            params["since"] = since
        for page in range(1, pages + 1):
            data, meta = self.gh.get(
                f"{self.base}/commits",
                {**params, "page": page},
                ttl=ttl,
                shape=_listing_shape,
            )
            rows += data or []
            if not meta.get("next"):
                return rows, False
        return rows, True

    def commit(self, sha: str) -> dict | None:
        data, _ = self.gh.get(f"{self.base}/commits/{sha}", shape=_commit_shape)
        return data

    def tree(self, sha: str) -> list[str]:
        data, _ = self.gh.get(
            f"{self.base}/git/trees/{sha}",
            {"recursive": 1},
            shape=lambda d: [
                t["path"] for t in d.get("tree", []) if t.get("type") == "blob"
            ],
        )
        return data or []

    def content(self, sha: str, path: str) -> str | None:
        data, _ = self.gh.get(f"{RAW}/{self.name}/{sha}/{quote(path)}", resource="")
        return data if isinstance(data, str) else None

    def pulls_of(self, sha: str) -> list[dict]:
        data, _ = self.gh.get(
            f"{self.base}/commits/{sha}/pulls",
            ttl=MUTABLE_TTL,
            shape=lambda rows: [_pr_shape(p) for p in rows],
        )
        return data or []

    def pull(self, number: int) -> dict | None:
        data, _ = self.gh.get(
            f"{self.base}/pulls/{number}", ttl=MUTABLE_TTL, shape=_pr_shape
        )
        return data

    def issue(self, number: int) -> dict | None:
        data, _ = self.gh.get(
            f"{self.base}/issues/{number}", ttl=MUTABLE_TTL, shape=_issue_shape
        )
        return data

    def pr_for(self, commit: dict) -> dict | None:
        """The merged pull request that brought ``commit`` in, preferring the one it was merged as."""
        merged = [p for p in self.pulls_of(commit["sha"]) if p.get("merged_at")]
        if merged:
            return sorted(
                merged,
                key=lambda p: (
                    p.get("merge_commit_sha") != commit["sha"],
                    p["merged_at"],
                ),
            )[0]
        title = commit["message"].split("\n", 1)[0]
        if found := SQUASH_PR.search(title):
            pr = self.pull(int(found.group(1)))
            if (
                pr
                and pr.get("merged_at")
                and pr.get("merge_commit_sha") == commit["sha"]
            ):
                return pr
        return None

    def blame(self, sha: str, path: str) -> list[dict] | None:
        owner, name = self.name.split("/", 1)
        data = self.gh.graphql(
            """query($owner:String!,$name:String!,$expr:String!,$path:String!){
              repository(owner:$owner,name:$name){object(expression:$expr){
                ... on Commit{blame(path:$path){ranges{startingLine endingLine commit{oid}}}}}}}""",
            {"owner": owner, "name": name, "expr": sha, "path": path},
        )
        try:
            return data["repository"]["object"]["blame"]["ranges"]
        except (TypeError, KeyError):
            return None


# --------------------------------------------------------------------------------------------- matching


def _weak(name: str) -> bool:
    return len(name) <= 4 or name.lower() in WEAK


@dataclass
class Target:
    """What to look for in diffs and prose for one change."""

    change: APIChange
    name: str
    parent: str
    module: bool = False
    definitions: list[re.Pattern] = field(default_factory=list)
    mention: re.Pattern | None = None
    prose: list[re.Pattern] = field(default_factory=list)
    context: list[re.Pattern] = field(default_factory=list)
    context_label: str = ""
    new_default: str | None = None
    old_default: str | None = None

    @classmethod
    def of(cls, change: APIChange, module: bool) -> Target:
        parts = change.symbol.split(".")
        name = change.parameter or parts[-1]
        parent = (
            parts[-1] if change.parameter else (parts[-2] if len(parts) > 1 else "")
        )
        target = cls(change=change, name=name, parent=parent, module=module)
        n = re.escape(name)
        target.mention = re.compile(rf"(?<![\w.]){n}\b")
        if change.parameter:
            target.definitions = [
                re.compile(rf"^\s*\*{{0,2}}{n}\s*(?::[^=]+)?(?:=|,|\)|$)"),
                re.compile(
                    rf"[(,]\s*\*{{0,2}}{n}\s*(?::[^,=)]+)?\s*(?:=[^,)]*)?\s*[,)]"
                ),
            ]
        else:
            target.definitions = [
                re.compile(rf"^\s*(?:async\s+)?def\s+{n}\b"),
                re.compile(rf"^\s*class\s+{n}\b"),
                re.compile(rf"^\s*{n}\s*(?::[^=]+)?=(?!=)"),
                re.compile(rf"^\s*from\s+\S+\s+import\b.*\b{n}\b"),
                re.compile(rf"^\s*import\s+.*\b{n}\b"),
                re.compile(rf"^\s*{n}(?:\s+as\s+\w+)?\s*,?\s*$"),
                re.compile(rf"^\s*[\"']{n}[\"'],?\s*$"),
            ]
        if found := re.search(r"from (.+) to (.+)$", change.detail):
            target.old_default, target.new_default = (
                found.group(1).strip(),
                found.group(2).strip(),
            )
        p = re.escape(parent)
        qualified = [re.escape(change.symbol)]
        if parent:
            qualified.append(rf"\b{p}\.{n}\b")
        if _weak(name):
            target.prose = [
                *(re.compile(q) for q in qualified),
                re.compile(rf"`{n}`"),
                re.compile(rf"\b{n}=", re.IGNORECASE),
                re.compile(rf"\b{n}\s+(?:{p}|{CONTEXT_NOUNS})s?\b", re.IGNORECASE)
                if parent
                else re.compile(rf"\b{n}\s+(?:{CONTEXT_NOUNS})s?\b", re.IGNORECASE),
            ]
        else:
            target.prose = [re.compile(rf"(?<![\w]){n}\b")]
        module_name = ".".join(parts[:-1])
        if not change.parameter and len(parts) >= 3 and not parts[-2].startswith("_"):
            m = re.escape(parts[-2])
            target.context_label = module_name
            target.context = [
                re.compile(rf"(?<![\w.]){re.escape(module_name)}\b"),
                re.compile(rf"`{m}`\s+module\b|\b{m}\s+module\b"),
            ]
        literal = (target.new_default or "").strip("'\"")
        if literal and not _weak(literal) and re.fullmatch(r"[\w.-]+", literal):
            target.prose.append(re.compile(rf"\b{re.escape(literal)}\b"))
        return target

    def mentioned(self, text: str) -> bool:
        return any(p.search(text) for p in self.prose)

    def defines(self, line: str) -> bool:
        return any(p.search(line) for p in self.definitions)


def _diff_lines(patch: str | None) -> tuple[list[str], list[str]]:
    removed, added = [], []
    for line in (patch or "").splitlines():
        if line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    return removed, added


def _fragments(message: str, source: str) -> list[str]:
    """String literal pieces of ``source`` (f-string placeholders split out) that occur in ``message``."""
    found = []
    for literal in LITERAL.findall(source):
        body = literal[1:-1]
        for piece in re.split(r"\{[^{}]*\}", body):
            piece = piece.strip()
            if len(piece) >= 15 and piece in message:
                found.append(piece)
    return found


def _assigns(name: str, literal: str, line: str) -> bool:
    """``line`` gives ``name`` the default ``literal`` (``name=lit`` or ``name: Annotation = lit``)."""
    if literal[:1] in ("'", '"') and literal[-1:] == literal[:1]:
        value = rf"[\"']{re.escape(literal[1:-1])}[\"']"
    else:
        value = rf"{re.escape(literal)}(?![\w.])"
    annotation = r"(?::\s*(?:[^=,\[\]]|\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])*)?"
    return (
        re.search(rf"(?<![\w.]){re.escape(name)}\s*{annotation}=\s*{value}", line)
        is not None
    )


@dataclass
class Match:
    commit: dict
    confidence: Confidence
    score: int
    evidence: str


def _assess(target: Target, commit: dict, files: list[str]) -> Match | None:
    kind = target.change.kind
    touched = [
        f
        for f in commit["files"]
        if f["filename"] in files or f.get("previous_filename") in files
    ]
    if not touched:
        return None
    net, mentions, exact_extra = 0, 0, 0
    evidence = ""
    for f in touched:
        if (
            target.module
            and f["status"] in ("removed", "renamed")
            and (f.get("previous_filename") or f["filename"]) == files[0]
        ):
            exact_extra += 100
            evidence = f"{f['status']} {files[0]}"
        removed, added = _diff_lines(f["patch"])
        mentions += sum(1 for line in removed + added if target.mention.search(line))
        gone = sum(1 for line in removed if target.defines(line))
        back = sum(1 for line in added if target.defines(line))
        if kind in REMOVAL:
            net += gone - back
            if gone > back and not evidence:
                evidence = f"removes {gone - back} line(s) defining {target.name} in {f['filename']}"
        elif kind == "deprecated":
            message = target.change.message or ""
            hits = [
                line
                for line in added
                if _fragments(message, line)
                or (target.mention.search(line) and "deprecat" in line.lower())
            ]
            if hits:
                exact_extra += len(hits)
                evidence = (
                    evidence
                    or f"adds the deprecation of {target.name} in {f['filename']}"
                )
        elif kind == "default-changed" and target.old_default and target.new_default:
            before = [
                line
                for line in removed
                if _assigns(target.name, target.old_default, line)
            ]
            after = [
                line
                for line in added
                if _assigns(target.name, target.new_default, line)
            ]
            if before and after:
                exact_extra += len(after)
                evidence = evidence or (
                    f"changes the default of {target.name} from {target.old_default} "
                    f"to {target.new_default} in {f['filename']}"
                )
        else:
            before = [line for line in removed if target.defines(line)]
            after = [line for line in added if target.defines(line)]
            if before and after:
                exact_extra += len(after)
                evidence = (
                    evidence
                    or f"rewrites the {target.name} parameter in {f['filename']}"
                )
    score = max(net, 0) + exact_extra
    if score > 0:
        return Match(commit, "exact", score, evidence)
    if mentions or target.mention.search(commit["message"]):
        return Match(
            commit, "related", mentions, f"mentions {target.name} in a touched file"
        )
    return None


# --------------------------------------------------------------------------------------------- quotes


def _paragraph_lines(text: str) -> Iterable[str]:
    """Lines of prose with hard-wrapped continuations joined; fenced code is skipped."""
    fenced = False
    current = ""
    for raw in text.splitlines():
        if FENCE.match(raw):
            fenced = not fenced
            if current:
                yield current
            current = ""
            continue
        if fenced:
            continue
        line = raw.strip()
        if not line or BLOCK_START.match(line):
            if current:
                yield current
            current = line
            continue
        current = f"{current} {line}" if current else line
    if current and not fenced:
        yield current


def _sentences(text: str) -> Iterable[str]:
    for line in _paragraph_lines(text):
        while (
            line[:2] in ("- ", "* ", "+ ", "> ")
            or line[:1] == "#"
            or line[:4] in ("[x] ", "[ ] ", "[X] ")
        ):
            line = line[4:] if line[:1] == "[" else line.lstrip("-*+># ")
            line = line.strip()
        for sentence in SENTENCE.split(line):
            sentence = sentence.strip()
            if sentence.startswith("**") != sentence.endswith("**"):
                sentence = sentence.strip("*").strip()
            if len(sentence) >= 8:
                yield sentence


def _clip(sentence: str, target: Target) -> str:
    if len(sentence) <= MAX_QUOTE_CHARS:
        return sentence
    spot = next((m.start() for p in target.prose if (m := p.search(sentence))), 0)
    begin = max(0, spot - MAX_QUOTE_CHARS // 2)
    clipped = sentence[begin : begin + MAX_QUOTE_CHARS]
    if begin:
        clipped = clipped.split(" ", 1)[-1]
    return (
        clipped.rsplit(" ", 1)[0]
        if begin + MAX_QUOTE_CHARS < len(sentence)
        else clipped
    )


def _quotes(
    target: Target,
    source: str,
    url: str,
    kind: SourceKind,
    limit: int = 3,
    *,
    context: bool = False,
) -> list[Quote]:
    """Sentences of ``source`` naming the change; with ``context``, naming its enclosing module instead."""
    patterns, label = (
        (target.context, target.context_label)
        if context
        else (target.prose, target.name)
    )
    found: list[Quote] = []
    for sentence in _sentences(source):
        hit = next((m for p in patterns if (m := p.search(sentence))), None)
        if hit is None:
            continue
        text = _clip(sentence, target).strip()
        mentions = label if context else (hit.group(0).strip("`=") or label)
        if verified(text, source) and all(q.text != text for q in found):
            found.append(
                Quote(text=text, source_url=url, source_kind=kind, mentions=mentions)
            )
        if len(found) >= limit:
            break
    return found


def _changelog_quotes(target: Target, commit: dict) -> list[Quote]:
    found: list[Quote] = []
    for f in commit["files"]:
        if not CHANGELOG.search(f["filename"]) or not f.get("patch"):
            continue
        removed, added = _diff_lines(f["patch"])
        # Lines that only re-mark-up an old entry (same words as a removed line) say nothing new.
        old = [set(WORD.findall(line)) for line in removed]
        added = [
            line
            for line in added
            if not (words := set(WORD.findall(line)))
            or not any(words <= previous for previous in old)
        ]
        source = "\n".join(added)
        for quote_ in _quotes(target, source, commit["html_url"], "changelog"):
            # Checked against the file as the commit left it (diff markers stripped), not just added lines.
            after = "\n".join(
                line[1:]
                for line in f["patch"].splitlines()
                if line[:1] in (" ", "+") and not line.startswith("+++")
            )
            if verified(quote_.text, after):
                found.append(quote_)
    return found[:3]


# --------------------------------------------------------------------------------------------- explain


@dataclass
class Context:
    repo: Repo
    release: ReleaseRange
    start_tree: list[str]
    end_tree: list[str]
    in_range: set[str]
    complete: bool
    """False when the compare was truncated: then every commit since the merge base counts as in range."""
    since: str | None
    end_date: str | None
    base_limits: list[str]
    limits: list[str] = field(default_factory=list)
    read: list[tuple[str, dict]] = field(default_factory=list)
    """In-range commits read for the current change, with the path they were read for."""


def _resolve(file: str, trees: Iterable[list[str]]) -> str | None:
    """The repository path of a file given relative to the package root (``src/`` layouts and the like)."""
    for tree in trees:
        hits = [p for p in tree if p == file or p.endswith("/" + file)]
        if hits:
            return min(hits, key=lambda p: (p.count("/"), len(p)))
    return None


def _module_files(symbol: str, trees: list[list[str]]) -> list[tuple[str, bool]]:
    """Repository files for the longest importable prefixes of ``symbol``; True when it is the symbol itself."""
    parts = symbol.split(".")
    found: list[tuple[str, bool]] = []
    for end in range(len(parts), 0, -1):
        stem = "/".join(parts[:end])
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            if path := _resolve(candidate, trees):
                found.append((path, end == len(parts)))
                break
        if found:
            break
    return found


def _files(change: APIChange, ctx: Context) -> tuple[list[str], bool]:
    """Repository paths to search, in order, and whether the symbol is a whole module."""
    trees = [ctx.start_tree, ctx.end_tree]
    paths: list[str] = []
    module = False
    modules = _module_files(change.symbol, trees)
    if modules and modules[0][1] and not change.parameter:
        module = True
        paths.append(modules[0][0])
    for location in (change.before, change.after):
        if location and (path := _resolve(location.file, trees)):
            paths.append(path)
    paths += [p for p, _ in modules]
    return list(dict.fromkeys(paths))[:3], module


def _candidates(target: Target, files: list[str], ctx: Context) -> list[Match]:
    end = ctx.release.end.commit
    matches: list[Match] = []
    for path in files:
        rows, more = ctx.repo.history(end, path, ctx.since)
        rows = [r for r in rows if not ctx.complete or r["sha"] in ctx.in_range]
        if more:
            ctx.limits.append(
                f"history of {path} has more than {MAX_HISTORY_PAGES * 100} commits"
            )
        if len(rows) > MAX_CANDIDATES:
            ctx.limits.append(
                f"read the newest {MAX_CANDIDATES} of {len(rows)} commits touching {path}"
            )
        for row in rows[:MAX_CANDIDATES]:
            commit = ctx.repo.commit(row["sha"])
            if commit:
                ctx.read.append((path, commit))
            if commit and (found := _assess(target, commit, [path])):
                matches.append(found)
        if any(m.confidence == "exact" for m in matches):
            break
    order = {"exact": 0, "related": 1}
    return sorted(
        matches,
        key=lambda m: (order[m.confidence], -m.score, m.commit["date"]),
    )


def _best(matches: list[Match]) -> Match | None:
    if not matches:
        return None
    top = matches[0]
    tied = [
        m for m in matches if m.confidence == top.confidence and m.score == top.score
    ]
    return max(tied, key=lambda m: m.commit["date"])


def _origin_line(message: str, text: str, near: int | None) -> int | None:
    lines = text.splitlines()
    hits = [i + 1 for i, line in enumerate(lines) if _fragments(message, line)]
    if not hits:
        return None
    return min(hits, key=lambda n: abs(n - near)) if near else hits[0]


def _introduces(commit: dict, path: str, message: str) -> tuple[bool, bool]:
    """``(adds the message, only rewords a line that already carried it)`` for ``path`` in ``commit``."""

    def squash(s: str) -> str:
        return re.sub(r"[\d\s]+", "", s)

    for f in commit["files"]:
        if f["filename"] != path:
            continue
        removed, added = _diff_lines(f["patch"])
        pieces = [p for line in added for p in _fragments(message, line)]
        if not pieces:
            return False, False
        old = squash("\n".join(removed))
        reworded = any(squash(p) and squash(p) in old for p in pieces)
        return True, reworded
    return False, False


def _deprecation_before(
    target: Target, files: list[str], ctx: Context
) -> tuple[dict, Confidence] | None:
    """The commit that introduced the deprecation message a removal followed, at or before the start tag."""
    message = target.change.message
    start = ctx.release.start.commit
    if not message or not start:
        return None
    near = target.change.before.line if target.change.before else None
    for path in files:
        text = ctx.repo.content(start, path)
        if not text or (line := _origin_line(message, text, near)) is None:
            continue
        sha, current, hops = start, path, 0
        while hops < MAX_LINEAGE:
            hops += 1
            ranges = ctx.repo.blame(sha, current)
            if ranges is None:
                return _walk_deprecation(message, current, sha, ctx)
            owner = next(
                (
                    r["commit"]["oid"]
                    for r in ranges
                    if r["startingLine"] <= line <= r["endingLine"]
                ),
                None,
            )
            commit = ctx.repo.commit(owner) if owner else None
            if commit is None:
                return None
            adds, reworded = _introduces(commit, current, message)
            if adds and not reworded:
                return commit, "exact"
            if not commit["parents"]:
                return (commit, "related") if adds else None
            parent = commit["parents"][0]
            text = ctx.repo.content(parent, current)
            line = _origin_line(message, text or "", line)
            if line is None:
                return (commit, "related") if adds else None
            sha = parent
        return None
    return None


def _deprecation(
    target: Target, files: list[str], ctx: Context
) -> tuple[dict, Confidence] | None:
    """The commit that introduced the deprecation message: before the start tag, else inside the range."""
    if found := _deprecation_before(target, files, ctx):
        return found
    message = target.change.message or ""
    for path, commit in sorted(ctx.read, key=lambda item: item[1]["date"]):
        adds, reworded = _introduces(commit, path, message)
        if adds and not reworded:
            return commit, "exact"
    return None


def _walk_deprecation(
    message: str, path: str, ref: str, ctx: Context
) -> tuple[dict, Confidence] | None:
    """Without a token for blame: walk the file's history back from ``ref`` for the commit adding the message."""
    rows, _ = ctx.repo.history(ref, path, None, pages=1)
    for row in rows[:MAX_CANDIDATES]:
        commit = ctx.repo.commit(row["sha"])
        if commit is None:
            continue
        adds, reworded = _introduces(commit, path, message)
        if adds and not reworded:
            return commit, "exact"
    return None


def _reversal(target: Target, files: list[str], ctx: Context) -> str | None:
    """A later commit on the default branch that put a removed definition back."""
    if target.change.kind not in REMOVAL or not ctx.end_date:
        return None
    path = files[0]
    rows, more = ctx.repo.history(None, path, ctx.end_date, ttl=MUTABLE_TTL, pages=1)
    rows = [
        r
        for r in rows
        if r["sha"] not in ctx.in_range and r["sha"] != ctx.release.end.commit
    ]
    if more or len(rows) > MAX_REVERSAL_COMMITS:
        ctx.limits.append(
            f"reversal check read {min(len(rows), MAX_REVERSAL_COMMITS)} of the commits touching {path} "
            f"after {ctx.release.end.tag or ctx.release.end.version}, oldest first"
        )
    for row in reversed(
        rows[-MAX_REVERSAL_COMMITS:] if len(rows) > MAX_REVERSAL_COMMITS else rows
    ):
        commit = ctx.repo.commit(row["sha"])
        if commit is None:
            continue
        restored = False
        for f in commit["files"]:
            if f["filename"] != path:
                continue
            removed, added = _diff_lines(f["patch"])
            if target.module and f["status"] == "added":
                restored = True
            elif sum(map(target.defines, added)) > sum(map(target.defines, removed)):
                restored = True
        if not restored:
            continue
        pr = ctx.repo.pr_for(commit)
        title = commit["message"].split("\n", 1)[0]
        if pr:
            return f'{ctx.repo.name}#{pr["number"]} "{pr["title"]}" (merged {pr["merged_at"]}, commit {commit["sha"][:12]}) adds {target.name} back to {path}'
        return f'commit {commit["sha"][:12]} "{title}" ({commit["date"]}) adds {target.name} back to {path}'
    return None


def _decide(change: APIChange, ctx: Context) -> UpstreamDecision:
    key = ChangeKey(symbol=change.symbol, parameter=change.parameter, kind=change.kind)
    ctx.limits = list(ctx.base_limits)
    ctx.read = []
    files, module = _files(change, ctx)
    if not files:
        return UpstreamDecision(
            change_key=key,
            not_found=f"no file for {change.symbol} was found in {ctx.repo.name} at {ctx.release.start.tag or ctx.release.start.commit}",
        )
    target = Target.of(change, module)
    best = _best(_candidates(target, files, ctx))
    origin = None
    if change.message and change.kind != "deprecated":
        # The removal usually deletes the warning too, which names the file to blame at the start tag.
        warned = [
            f["filename"]
            for f in (best.commit["files"] if best else [])
            if any(
                _fragments(change.message, line) for line in _diff_lines(f["patch"])[0]
            )
        ]
        origin = _deprecation(target, list(dict.fromkeys(files + warned)), ctx)
    quotes: list[Quote] = []
    fields: dict = {}
    if best is not None:
        commit = best.commit
        pr = ctx.repo.pr_for(commit)
        quotes += _changelog_quotes(target, commit)
        if pr:
            direct = _quotes(target, pr["title"], pr["html_url"], "pr-title", 1)
            direct += _quotes(target, pr["body"], pr["html_url"], "pr-body")
            if not direct and target.context:
                direct = _quotes(
                    target, pr["body"], pr["html_url"], "pr-body", 2, context=True
                )
            quotes += direct
            issues = []
            for found in LINKED.finditer(pr["body"]):
                other = (found.group("repo") or found.group("url") or "").lower()
                if other and other != ctx.repo.name.lower():
                    continue
                number = int(found.group("number"))
                if number not in issues and number != pr["number"]:
                    issues.append(number)
            fields["linked_issues"] = tuple(issues[:MAX_ISSUES])
            for number in issues[:MAX_ISSUES]:
                issue = ctx.repo.issue(number)
                if issue:
                    text = issue["title"] + "\n\n" + issue["body"]
                    quotes += _quotes(target, text, issue["html_url"], "issue", 2)
            fields.update(
                pr_number=pr["number"],
                pr_title=pr["title"],
                pr_url=pr["html_url"],
                merged_at=pr["merged_at"],
                author=pr["author"],
            )
        else:
            fields.update(author=commit["author"])
        quotes += _quotes(
            target, commit["message"], commit["html_url"], "commit-message", 2
        )
        fields.update(
            commit=commit["sha"],
            commit_url=commit["html_url"],
            confidence=best.confidence,
            evidence=best.evidence,
        )
        fields["reversal"] = _reversal(target, files, ctx)
    else:
        start, end = ctx.release.start, ctx.release.end
        fields["not_found"] = (
            f"no commit between {start.tag or start.commit[:12]} and {end.tag or end.commit[:12]} "
            f"that touched {', '.join(files)} changes or mentions {target.name}"
        )
    if origin is not None:
        commit, confidence = origin
        pr = ctx.repo.pr_for(commit)
        fields["deprecation"] = Origin(
            pr_number=pr["number"] if pr else None,
            pr_title=pr["title"] if pr else None,
            pr_url=pr["html_url"] if pr else None,
            merged_at=pr["merged_at"] if pr else None,
            commit=commit["sha"],
            commit_url=commit["html_url"],
            confidence=confidence,
        )
        direct: list[Quote] = []
        if pr:
            direct += _quotes(target, pr["title"], pr["html_url"], "pr-title", 1)
            direct += _quotes(target, pr["body"], pr["html_url"], "pr-body", 2)
        direct += _changelog_quotes(target, commit)[:1]
        direct += _quotes(
            target, commit["message"], commit["html_url"], "commit-message", 1
        )
        if not direct and pr and target.context:
            direct += _quotes(
                target, pr["title"], pr["html_url"], "pr-title", 1, context=True
            )
            direct += _quotes(
                target, pr["body"], pr["html_url"], "pr-body", 2, context=True
            )
        quotes += direct
    unique: list[Quote] = []
    for q in quotes:
        if all((q.text, q.source_url) != (u.text, u.source_url) for u in unique):
            unique.append(q)
    return UpstreamDecision(
        change_key=key,
        quotes=tuple(unique[:MAX_QUOTES]),
        limits=tuple(dict.fromkeys(ctx.limits)),
        **fields,
    )


def _context(repo: Repo, release: ReleaseRange) -> Context:
    start, end = release.start.commit, release.end.commit
    data, truncated = repo.compare(start, end)
    limits = []
    if truncated:
        limits.append(
            f"compare {release.start.version}...{release.end.version} lists {data.get('total_commits')} commits; read {len(data['commits'])}"
        )
    end_commit = repo.commit(end)
    ctx = Context(
        repo=repo,
        release=release,
        start_tree=repo.tree(start),
        end_tree=repo.tree(end),
        in_range={c["sha"] for c in data["commits"]},
        complete=not truncated,
        since=(
            data.get("merge_base_date")
            if truncated
            else min((c["date"] for c in data["commits"]), default=None)
        ),
        end_date=end_commit["date"] if end_commit else None,
        base_limits=limits,
    )
    return ctx


def explain(
    release: ReleaseRange,
    changes: list[APIChange],
    client: httpx.Client | None = None,
    *,
    stats: dict | None = None,
) -> list[UpstreamDecision]:
    """One upstream decision per change, in the order given; ``stats`` receives request counts."""

    def missing(change: APIChange, reason: str) -> UpstreamDecision:
        return UpstreamDecision(
            change_key=ChangeKey(
                symbol=change.symbol, parameter=change.parameter, kind=change.kind
            ),
            not_found=reason,
        )

    if not changes:
        return []
    if not release.repository or not release.start.commit or not release.end.commit:
        reason = (
            release.not_located
            or "the release tags were not located in a GitHub repository"
        )
        return [missing(c, reason) for c in changes]
    own = client is None
    http = client or httpx.Client(timeout=60, follow_redirects=True)
    gh = GitHubCache(http, token())
    try:
        repo = Repo(gh, release.repository)
        try:
            ctx = _context(repo, release)
        except RateLimited as error:
            return [missing(c, str(error)) for c in changes]
        except (httpx.HTTPError, LookupError, KeyError) as error:
            reason = f"GitHub lookup failed: {type(error).__name__}: {error}"
            return [missing(c, reason) for c in changes]
        decisions = []
        limited: str | None = None
        for change in changes:
            if limited:
                decisions.append(missing(change, limited))
                continue
            try:
                decisions.append(_decide(change, ctx))
            except RateLimited as error:
                limited = str(error)
                decisions.append(missing(change, limited))
            except (httpx.HTTPError, KeyError, ValueError) as error:
                decisions.append(
                    missing(change, f"GitHub lookup failed: {type(error).__name__}")
                )
        return decisions
    finally:
        if stats is not None:
            stats.update(calls=gh.calls, cached=gh.hits, revalidated=gh.revalidated)
        if own:
            http.close()
