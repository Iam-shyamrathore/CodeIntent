"""Read-only toolsets for the agents, built per session.

``code`` reads the downloaded repository (a 100-line viewer and a short text search, after SWE-agent's
agent-computer interface); ``graph`` asks the workspace graph in Neo4j who calls a line, where a package is
used and how it is pulled in (after CodexGraph and LocAgent); ``upstream`` reads a library's GitHub release
notes; ``web`` searches with Serper and reads pages, but only pages that a search in the same session
returned, so nothing an agent read can point it at an address of an attacker's choosing.

Every tool is confined to one repository and one workspace, and none can write anything.
"""

from __future__ import annotations

import html
import ipaddress
import os
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx
from packaging.version import InvalidVersion, Version

from codeintent.agent.harness import Tool
from codeintent.upgrades.manifests import files

VIEW_LINES = 100
MAX_MATCHES = 40
MAX_PAGE_BYTES = 1_500_000
SERPER = "https://google.serper.dev"


@dataclass
class Session:
    """What one agent's tools may reach, and what they have shown it."""

    root: Path | None = None
    ws: int | None = None
    repo: str | None = None
    http: httpx.Client | None = None
    allowed_urls: set[str] = field(default_factory=set)
    read_urls: set[str] = field(default_factory=set)
    seen: list[str] = field(default_factory=list)
    """Text the tools returned (release notes, pages), for checking an agent's quotes against."""


def _schema(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


# --- code ------------------------------------------------------------------------------------------


def _path(session: Session, path: str) -> Path:
    if session.root is None:
        raise ValueError("no repository is available in this session")
    target = files.confined(session.root, session.root / path.lstrip("/"))
    if not target.is_file():
        raise ValueError(f"{path} is not a file in the repository")
    return target


def code(session: Session) -> list[Tool]:
    def read_file(path: str, start: int = 1, lines: int = VIEW_LINES) -> str:
        target = _path(session, path)
        text = files.read(session.root, target).splitlines()
        start = max(1, int(start))
        end = min(len(text), start - 1 + max(1, min(int(lines), 200)))
        body = "\n".join(f"{n:>5}  {text[n - 1]}" for n in range(start, end + 1))
        return f"{path} lines {start}-{end} of {len(text)}\n{body}"

    def search_code(text: str, path_prefix: str = "") -> str:
        from codeintent.upgrades.usage.extractor import _python_files

        if not session.root or len(text) < 2:
            raise ValueError("give at least two characters to search for")
        hits = []
        for path in _python_files(session.root):
            rel = path.relative_to(session.root).as_posix()
            if path_prefix and not rel.startswith(path_prefix):
                continue
            try:
                body = files.read(session.root, path)
            except files.Unreadable:
                continue
            for n, line in enumerate(body.splitlines(), 1):
                if text in line:
                    hits.append(f"{rel}:{n}: {line.strip()[:160]}")
                    if len(hits) == MAX_MATCHES:
                        return "\n".join(hits) + f"\n(first {MAX_MATCHES} matches only)"
        return "\n".join(hits)

    return [
        Tool(
            "read_file",
            "Read up to 100 numbered lines of a repository file, from `start`.",
            _schema(
                {
                    "path": {
                        "type": "string",
                        "description": "Path from the repository root.",
                    },
                    "start": {"type": "integer", "description": "First line, from 1."},
                    "lines": {
                        "type": "integer",
                        "description": "How many lines (at most 200).",
                    },
                },
                ["path"],
            ),
            read_file,
            "code",
        ),
        Tool(
            "search_code",
            "Find Python lines containing exact text. Returns file:line: line, at most 40.",
            _schema(
                {
                    "text": {"type": "string"},
                    "path_prefix": {
                        "type": "string",
                        "description": "Only under this folder.",
                    },
                },
                ["text"],
            ),
            search_code,
            "code",
        ),
    ]


# --- graph -----------------------------------------------------------------------------------------


def graph(session: Session) -> list[Tool]:
    from codeintent import workspace_graph as wg
    from codeintent.graph import shared

    def needs():
        if session.ws is None or not session.repo:
            raise ValueError("no workspace repository in this session")

    def callers(file: str, line: int) -> dict:
        needs()
        with shared() as db:
            [found] = wg.blast(
                db,
                session.ws,
                session.repo,
                [{"file": file, "line": int(line)}],
                depth=3,
            )
        return found

    def uses_of(package: str) -> dict:
        needs()
        with shared() as db:
            found = wg.reach(db, session.ws, session.repo, package)
        found["lines"] = found["lines"][:60]
        return found

    return [
        Tool(
            "callers",
            "From the code graph: the function a line is in, functions calling it (up to 3 calls "
            "away), files importing its file, and the tests and entry points among them.",
            _schema(
                {"file": {"type": "string"}, "line": {"type": "integer"}},
                ["file", "line"],
            ),
            callers,
            "graph",
        ),
        Tool(
            "uses_of",
            "From the code graph: every line in this repository using a package (symbol, call kind, "
            "keyword arguments, enclosing function), and the chains of other packages pulling it in.",
            _schema({"package": {"type": "string"}}, ["package"]),
            uses_of,
            "graph",
        ),
    ]


# --- upstream --------------------------------------------------------------------------------------


def _version(tag: str) -> Version | None:
    match = re.search(r"\d+(?:\.\d+)+(?:[a-z]+\d*)?", tag or "")
    try:
        return Version(match.group(0)) if match else None
    except InvalidVersion:
        return None


def release_notes(repository: str, start: str, end: str, http: httpx.Client) -> str:
    """GitHub release notes of ``repository`` for versions after ``start`` up to and including ``end``."""
    from codeintent.upgrades.repository import token
    from codeintent.upgrades.upstream import API, GitHubCache

    gh = GitHubCache(http, token())
    low, high = Version(start), Version(end)
    notes = []
    for page in (1, 2, 3):
        data, _ = gh.get(
            f"{API}/repos/{repository}/releases",
            {"per_page": 100, "page": page},
            ttl=6 * 3600,
        )
        rows = data if isinstance(data, list) else []
        for release in rows:
            version = _version(release.get("tag_name") or release.get("name") or "")
            if (
                version
                and low < version <= high
                and (release.get("body") or "").strip()
            ):
                notes.append(
                    (
                        version,
                        (
                            f"## {release.get('tag_name')} ({(release.get('published_at') or '')[:10]})\n"
                            f"{release['body'].strip()}"
                        ),
                    )
                )
        if len(rows) < 100:
            break
    notes.sort(key=lambda n: n[0], reverse=True)
    return "\n\n".join(text for _, text in notes)


def upstream(session: Session) -> list[Tool]:
    def notes(repository: str, start: str, end: str) -> str:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("repository must be owner/name")
        text = release_notes(
            repository, start, end, session.http or httpx.Client(timeout=30)
        )
        session.seen.append(text)
        return text or "No GitHub release notes in that range."

    return [
        Tool(
            "release_notes",
            "The library's GitHub release notes for versions after `start` up to `end`, newest first.",
            _schema(
                {
                    "repository": {
                        "type": "string",
                        "description": "owner/name on GitHub",
                    },
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
                ["repository", "start", "end"],
            ),
            notes,
            "upstream",
        )
    ]


# --- web -------------------------------------------------------------------------------------------


def search_configured() -> bool:
    return bool(os.getenv("SERPER_API_KEY"))


def serper(
    kind: str,
    query: str,
    http: httpx.Client,
    *,
    recent: str | None = None,
    num: int = 10,
) -> list[dict]:
    """Organic (``search``) or ``news`` results from Serper: title, link, snippet, date."""
    body = {"q": query[:300], "num": num}
    if recent:
        body["tbs"] = f"qdr:{recent}"
    response = http.post(
        f"{SERPER}/{kind}",
        headers={
            "X-API-KEY": os.environ["SERPER_API_KEY"],
            "Content-Type": "application/json",
        },
        json=body,
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    rows = data.get("news" if kind == "news" else "organic") or []
    return [
        {
            "title": r.get("title"),
            "link": r.get("link"),
            "snippet": r.get("snippet"),
            "date": r.get("date"),
            "source": r.get("source"),
        }
        for r in rows
        if r.get("link", "").startswith(("https://", "http://"))
    ]


def _public(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname
    if host in ("localhost",) or host.endswith((".local", ".internal")):
        return False
    try:
        resolved = {info[4][0] for info in socket.getaddrinfo(host, parsed.port or 443)}
    except (socket.gaierror, UnicodeError):
        return False
    return bool(resolved) and all(
        ipaddress.ip_address(a.split("%")[0]).is_global for a in resolved
    )


class _Text(HTMLParser):
    SKIP = frozenset({"script", "style", "noscript", "svg", "nav", "footer", "header"})

    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "tr", "pre", "div"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1

    def handle_data(self, data):
        if not self.skipping:
            self.out.append(data)


def page_text(raw: str) -> str:
    parser = _Text()
    parser.feed(raw)
    text = html.unescape("".join(parser.out))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def web(session: Session) -> list[Tool]:
    http = session.http or httpx.Client(timeout=20, follow_redirects=True)

    def search(query: str, kind: str = "search", recent: str = "m") -> list[dict]:
        if not search_configured():
            raise ValueError("web search is not configured (SERPER_API_KEY)")
        rows = serper(
            "news" if kind == "news" else "search",
            query,
            http,
            recent=recent if recent in ("d", "w", "m", "y") else None,
        )
        session.allowed_urls.update(r["link"] for r in rows)
        return rows

    def read_page(url: str) -> str:
        if url not in session.allowed_urls:
            raise ValueError(
                "read_page only opens links returned by web_search in this session"
            )
        if not _public(url):
            raise ValueError("that address is not a public web page")
        with http.stream("GET", url, follow_redirects=True, timeout=20) as response:
            if not _public(str(response.url)):
                raise ValueError("the page redirected to a non-public address")
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                chunks.append(chunk)
                if size > MAX_PAGE_BYTES:
                    break
        raw = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        text = (
            page_text(raw)
            if "html" in response.headers.get("content-type", "html")
            else raw
        )
        session.seen.append(text)
        session.read_urls.add(url)
        return text

    return [
        Tool(
            "web_search",
            "Search the web (Google, through Serper). kind: 'search' or 'news'; recent: 'd', 'w', 'm' or "
            "'y' for the last day, week, month or year. Returns title, link, snippet and date.",
            _schema(
                {
                    "query": {"type": "string"},
                    "kind": {"type": "string", "enum": ["search", "news"]},
                    "recent": {"type": "string", "enum": ["d", "w", "m", "y"]},
                },
                ["query"],
            ),
            search,
            "web",
        ),
        Tool(
            "read_page",
            "Read the text of a page that web_search returned in this session.",
            _schema({"url": {"type": "string"}}, ["url"]),
            read_page,
            "web",
        ),
    ]


TOOLSETS = {"code": code, "graph": graph, "upstream": upstream, "web": web}


def toolbox(session: Session, *names: str) -> list[Tool]:
    """The tools of the named toolsets, for one session."""
    return [tool for name in names for tool in TOOLSETS[name](session)]
