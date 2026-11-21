"""GitHub App boundary: app JWTs, installation tokens, webhook intake and PR dependency diffs.

Secrets (private key, webhook secret, tokens) and webhook bodies are never logged.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import logging
import os
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Callable

import httpx

from codeintent.upgrades.manifests import REQUIREMENT_PATTERNS

logger = logging.getLogger(__name__)

API = "https://api.github.com"
API_VERSION = "2026-03-10"
PULL_ACTIONS = {"opened", "synchronize", "reopened"}
MAX_PULL_FILES = 3000  # GitHub's documented cap for GET /pulls/{n}/files
MAX_FILE_BYTES = 5_000_000
_TOKEN_MARGIN = 300  # refresh installation tokens five minutes before expiry
_tokens: dict[int, tuple[str, float]] = {}
_tokens_lock = threading.Lock()


class GitHubAppError(Exception):
    pass


# --- Authentication -------------------------------------------------------------------------


def app_id() -> str:
    value = os.getenv("GITHUB_APP_ID", "").strip()
    if not value:
        raise GitHubAppError("GITHUB_APP_ID is required")
    return value


def private_key() -> str:
    value = os.getenv("GITHUB_APP_PRIVATE_KEY", "")
    if not value.strip():
        raise GitHubAppError("GITHUB_APP_PRIVATE_KEY is required")
    # Config vars often carry the PEM on one line with literal "\n" escapes.
    return value.replace("\\n", "\n").strip() + "\n"


def app_jwt(now: int | None = None) -> str:
    """RS256 JWT per GitHub docs: iat 60 s in the past, exp under 10 minutes, iss = app id."""
    import jwt

    now = int(time.time()) if now is None else now
    claims = {"iat": now - 60, "exp": now + 540, "iss": app_id()}
    return jwt.encode(claims, private_key(), algorithm="RS256")


def _headers(token: str | None = None, accept: str = "application/vnd.github+json"):
    headers = {
        "Accept": accept,
        "User-Agent": "CodeIntent-App/1.0",
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def installation_token(
    installation_id: int, *, http: httpx.Client | None = None
) -> str:
    """Exchange the app JWT for an installation token, cached until five minutes before expiry."""
    installation_id = int(installation_id)
    with _tokens_lock:
        cached = _tokens.get(installation_id)
        if cached and cached[1] - _TOKEN_MARGIN > time.time():
            return cached[0]
        owned = http is None
        http = http or httpx.Client(base_url=API, timeout=20, follow_redirects=False)
        try:
            response = http.post(
                f"/app/installations/{installation_id}/access_tokens",
                headers=_headers(app_jwt()),
            )
        finally:
            if owned:
                http.close()
        if response.status_code != 201:
            raise GitHubAppError(
                f"Installation token request failed with HTTP {response.status_code}"
            )
        body = response.json()
        expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        _tokens[installation_id] = (body["token"], expires.timestamp())
        return body["token"]


def verify_signature(body: bytes, secret: str, header: str | None) -> bool:
    """X-Hub-Signature-256 check: HMAC-SHA256 hex digest of the raw body, constant-time compare."""
    if not secret or not header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), header.strip().encode())


class Client:
    """Minimal REST client. ``token`` is a callable so installation tokens refresh transparently."""

    def __init__(self, token: Callable[[], str]):
        self.token = token
        self.http = httpx.Client(base_url=API, timeout=30, follow_redirects=True)

    @classmethod
    def for_installation(cls, installation_id: int) -> Client:
        return cls(lambda: installation_token(installation_id))

    @classmethod
    def with_token(cls, token: str) -> Client:
        return cls(lambda: token)

    def close(self):
        self.http.close()

    def get(self, path: str, *, params=None, accept="application/vnd.github+json"):
        response = self.http.get(
            path, params=params, headers=_headers(self.token(), accept)
        )
        if response.status_code in (403, 429):
            raise GitHubAppError(
                f"GitHub rate limit or permission denied (HTTP {response.status_code})"
            )
        return response

    def request(self, method: str, path: str, *, json: dict) -> httpx.Response:
        """A write call. Errors are returned, not raised, so callers can fall back (edit -> create)."""
        response = self.http.request(
            method, path, json=json, headers=_headers(self.token())
        )
        if response.status_code in (403, 429) and "rate limit" in response.text.lower():
            raise GitHubAppError(f"GitHub rate limit on {method} {path}")
        return response

    def json(self, path: str, params=None):
        response = self.get(path, params=params)
        if response.status_code != 200:
            raise GitHubAppError(f"GET {path} failed with HTTP {response.status_code}")
        return response.json()

    def pull_files(self, repository: str, number: int) -> tuple[list[dict], bool]:
        files, page = [], 1
        while len(files) < MAX_PULL_FILES:
            response = self.get(
                f"/repos/{repository}/pulls/{number}/files",
                params={"per_page": 100, "page": page},
            )
            if response.status_code != 200:
                raise GitHubAppError(
                    f"Listing pull request files failed with HTTP {response.status_code}"
                )
            files.extend(response.json())
            if 'rel="next"' not in response.headers.get("link", ""):
                return files, False
            page += 1
        return files, True

    def merge_base(self, repository: str, base: str, head: str) -> str:
        data = self.json(
            f"/repos/{repository}/compare/{base}...{head}", params={"per_page": 1}
        )
        return data["merge_base_commit"]["sha"]

    def file_text(self, repository: str, path: str, ref: str) -> str | None:
        """File contents at ``ref`` via the contents API raw media type; None when absent."""
        response = self.get(
            f"/repos/{repository}/contents/{path}",
            params={"ref": ref},
            accept="application/vnd.github.raw+json",
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise GitHubAppError(
                f"Reading a file at {ref[:12]} failed with HTTP {response.status_code}"
            )
        if len(response.content) > MAX_FILE_BYTES:
            raise GitHubAppError(f"{path} is larger than {MAX_FILE_BYTES} bytes")
        return response.content.decode("utf-8", errors="replace")


# --- Dependency diff ------------------------------------------------------------------------

_ROOT_FILES = {"pyproject.toml", "uv.lock", "poetry.lock", "setup.cfg", "setup.py"}
_REQUIREMENT_PATTERNS = REQUIREMENT_PATTERNS


def manifest_root(path: str) -> str | None:
    """The directory the manifest parser would scan to read ``path``, or None if unsupported.

    Mirrors ``codeintent.upgrades.manifests.scan``: root-level manifests and lock files,
    ``REQUIREMENT_PATTERNS`` (e.g. ``dev-requirements.txt``) and ``requirements/*.{txt,in}``. Nested projects are
    scanned from their own directory.
    """
    parts = PurePosixPath(path)
    name, parent = parts.name, parts.parent
    if parent.name == "requirements" and parts.suffix in (".txt", ".in"):
        return parent.parent.as_posix()
    if name in _ROOT_FILES or any(
        fnmatch.fnmatchcase(name, p) for p in _REQUIREMENT_PATTERNS
    ):
        return parent.as_posix()
    return None


def _entries(scan, prefix: str) -> dict[tuple, dict]:
    grouped: dict[tuple, dict] = {}
    for dependency in scan.dependencies:
        file = (PurePosixPath(prefix) / dependency.location.file).as_posix()
        key = (file, dependency.name, dependency.group, dependency.marker or "")
        entry = grouped.setdefault(
            key,
            {
                "name": dependency.name,
                "file": file,
                "format": dependency.format,
                "group": dependency.group,
                "marker": dependency.marker,
                "direct": dependency.direct,
                "specifiers": set(),
                "versions": set(),
            },
        )
        entry["specifiers"].add(dependency.specifier)
        if dependency.locked_version:
            entry["versions"].add(dependency.locked_version)
    return grouped


def _state(entry: dict) -> dict:
    # One entry almost always; uv.lock can resolve several versions of one package.
    return {
        "specifier": " | ".join(sorted(entry["specifiers"])),
        "locked_version": ", ".join(sorted(entry["versions"])) or None,
    }


def _public(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k not in {"specifiers", "versions"}}


def diff_trees(base: Path, head: Path, roots: list[str]) -> dict:
    """Scan the same project roots in two checkouts and report dependency changes."""
    from codeintent.upgrades.manifests import scan

    added, removed, changed, issues = [], [], [], []
    for root in sorted(set(roots)):
        prefix = "" if root in ("", ".") else root
        before = (
            _entries(scan(base / prefix), prefix) if (base / prefix).is_dir() else {}
        )
        after_scan = scan(head / prefix) if (head / prefix).is_dir() else None
        after = _entries(after_scan, prefix) if after_scan else {}
        for issue in after_scan.issues if after_scan else ():
            issues.append(
                {
                    "reason": issue.reason,
                    "detail": issue.detail,
                    "file": (PurePosixPath(prefix) / issue.location.file).as_posix(),
                    "line": issue.location.line,
                }
            )
        for key in sorted(after.keys() - before.keys()):
            added.append(_public(after[key]) | {"new": _state(after[key])})
        for key in sorted(before.keys() - after.keys()):
            removed.append(_public(before[key]) | {"old": _state(before[key])})
        for key in sorted(before.keys() & after.keys()):
            old, new = _state(before[key]), _state(after[key])
            if old != new:
                changed.append(_public(after[key]) | {"old": old, "new": new})
    return {"added": added, "removed": removed, "changed": changed, "issues": issues}


def dependency_changes(
    client: Client, repository: str, number: int, base_sha: str, head_sha: str
) -> dict:
    """Dependency diff for one pull request revision. Reads only changed manifest files.

    The "before" side is the merge base, matching what GitHub shows as the PR diff even when
    the base branch has moved on since ``base_sha`` was recorded.
    """
    listed, truncated = client.pull_files(repository, number)
    manifests = [f for f in listed if manifest_root(f["filename"]) is not None]
    result = {
        "repository": repository,
        "number": number,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "merge_base": None,
        "files_truncated": truncated,
        "files": [
            {
                "path": f["filename"],
                "status": f["status"],
                "previous": f.get("previous_filename"),
            }
            for f in manifests
        ],
        "added": [],
        "removed": [],
        "changed": [],
        "issues": [],
    }
    if not manifests:
        return result
    merge_base = client.merge_base(repository, base_sha, head_sha)
    result["merge_base"] = merge_base
    with tempfile.TemporaryDirectory(prefix="ci-pr-") as temp:
        base, head = Path(temp, "base"), Path(temp, "head")
        roots = []
        for f in manifests:
            sides = []
            if f["status"] != "added":
                sides.append(
                    (base, f.get("previous_filename") or f["filename"], merge_base)
                )
            if f["status"] != "removed":
                sides.append((head, f["filename"], head_sha))
            for side, path, ref in sides:
                root = manifest_root(path)
                if root is None:
                    continue
                roots.append(root)
                text = client.file_text(repository, path, ref)
                if text is None:
                    continue
                target = (side / path).resolve()
                if not target.is_relative_to(side.resolve()):
                    raise GitHubAppError("Changed file path escapes the checkout")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
        base.mkdir(exist_ok=True)
        head.mkdir(exist_ok=True)
        result |= diff_trees(base, head, roots)
    return result


# --- Webhook intake (runs inside the web request; must stay fast) ----------------------------


def _upsert_installation(conn, installation: dict, account: dict | None, **fields):
    account = account or installation.get("account") or {}
    conn.execute(
        """INSERT INTO ci_installations(id,account_login,account_type,suspended,deleted_at)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET account_login=EXCLUDED.account_login,
          account_type=EXCLUDED.account_type,suspended=EXCLUDED.suspended,
          deleted_at=EXCLUDED.deleted_at,updated_at=now()"""
        if fields
        else """INSERT INTO ci_installations(id,account_login,account_type,suspended,deleted_at)
        VALUES (%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
        (
            int(installation["id"]),
            account.get("login", ""),
            account.get("type", ""),
            fields.get("suspended", False),
            fields.get("deleted_at"),
        ),
    )


def _add_repositories(conn, installation_id: int, repositories: list[dict]):
    for repo in repositories or []:
        conn.execute(
            """INSERT INTO ci_installation_repositories(installation_id,repository_id,full_name,private)
            VALUES (%s,%s,%s,%s) ON CONFLICT(installation_id,repository_id)
            DO UPDATE SET full_name=EXCLUDED.full_name,private=EXCLUDED.private""",
            (
                installation_id,
                int(repo["id"]),
                repo["full_name"],
                bool(repo.get("private")),
            ),
        )


def _remove_repositories(conn, installation_id: int, repositories: list[dict]):
    ids = [int(r["id"]) for r in repositories or []]
    if ids:
        conn.execute(
            "DELETE FROM ci_installation_repositories WHERE installation_id=%s AND repository_id=ANY(%s)",
            (installation_id, ids),
        )


def _scan(conn, installation_id: int, repositories: list[dict] | None):
    from codeintent import scans

    for repo in repositories or []:
        if repo.get("full_name"):
            scans.defer(conn, installation_id, repo["full_name"])


def handle_webhook(event: str, delivery: str, payload: dict) -> tuple[int, dict]:
    """Record a verified delivery and enqueue work in one transaction. Returns (status, body)."""
    from codeintent import store

    action = payload.get("action") if isinstance(payload.get("action"), str) else None
    installation = payload.get("installation") or {}
    installation_id = int(installation["id"]) if installation.get("id") else None
    with store.connection() as conn:
        inserted = conn.execute(
            """INSERT INTO ci_webhook_deliveries(id,installation_id,event,action)
            VALUES (%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING RETURNING id""",
            (delivery, installation_id, event, action),
        ).fetchone()
        if not inserted:
            return 202, {"status": "duplicate", "delivery": delivery}

        def finish(status: str, code: int, body: dict):
            conn.execute(
                "UPDATE ci_webhook_deliveries SET status=%s WHERE id=%s",
                (status, delivery),
            )
            return code, body

        if event == "ping":
            return finish("processed", 200, {"status": "pong"})
        if event == "installation" and installation_id:
            deleted = action == "deleted"
            _upsert_installation(
                conn,
                installation,
                None,
                suspended=action == "suspend"
                or (action != "unsuspend" and bool(installation.get("suspended_at"))),
                deleted_at=datetime.now(UTC) if deleted else None,
            )
            if deleted:
                _remove_repositories(conn, installation_id, payload.get("repositories"))
            else:
                _add_repositories(conn, installation_id, payload.get("repositories"))
                if action == "created":
                    _scan(conn, installation_id, payload.get("repositories"))
            return finish("processed", 202, {"status": "recorded", "action": action})
        if event == "installation_repositories" and installation_id:
            _upsert_installation(conn, installation, None, suspended=False)
            _add_repositories(conn, installation_id, payload.get("repositories_added"))
            _remove_repositories(
                conn, installation_id, payload.get("repositories_removed")
            )
            _scan(conn, installation_id, payload.get("repositories_added"))
            return finish("processed", 202, {"status": "recorded", "action": action})
        if event == "pull_request":
            pull, repo = (
                payload.get("pull_request") or {},
                payload.get("repository") or {},
            )
            if (
                action == "closed"
                and pull.get("merged")
                and installation_id
                and repo.get("full_name")
                and (pull.get("base") or {}).get("ref") == repo.get("default_branch")
            ):
                # A merge into the default branch can change what is locked: rescan for upcoming breakage.
                _upsert_installation(conn, installation, repo.get("owner"))
                _scan(conn, installation_id, [repo])
                return finish("queued", 202, {"status": "rescan"})
            if action not in PULL_ACTIONS:
                return finish(
                    "ignored", 202, {"status": "ignored", "reason": f"action {action}"}
                )
            if not installation_id:
                return finish(
                    "ignored", 202, {"status": "ignored", "reason": "no installation"}
                )
            number = int(payload.get("number") or pull.get("number") or 0)
            head = (pull.get("head") or {}).get("sha")
            base = (pull.get("base") or {}).get("sha")
            if not (repo.get("full_name") and number > 0 and head and base):
                return finish(
                    "ignored",
                    202,
                    {"status": "ignored", "reason": "incomplete payload"},
                )
            _upsert_installation(conn, installation, repo.get("owner"))
            ident = str(uuid.uuid4())
            created = conn.execute(
                """INSERT INTO ci_pull_analyses(id,installation_id,repository,number,head_sha,base_sha,delivery_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(repository,number,head_sha) DO NOTHING RETURNING id""",
                (
                    ident,
                    installation_id,
                    repo["full_name"],
                    number,
                    head,
                    base,
                    delivery,
                ),
            ).fetchone()
            if not created:
                return finish(
                    "ignored",
                    202,
                    {"status": "ignored", "reason": "revision already analysed"},
                )
            from codeintent.tasks import analyze_pull_request

            task_id = analyze_pull_request.configure(
                connection=conn, lock=f"pr:{repo['full_name']}#{number}"
            ).defer(analysis_id=ident)
            conn.execute(
                "UPDATE ci_pull_analyses SET task_id=%s WHERE id=%s", (task_id, ident)
            )
            return finish("queued", 202, {"status": "queued", "analysis_id": ident})
        return finish("ignored", 202, {"status": "ignored", "reason": f"event {event}"})


# --- Verdicts, check run and comment ------------------------------------------------------------


def _version(state: dict | None) -> str | None:
    """The exact version a manifest entry resolves to: the locked version, else an ``==`` pin."""
    if not state:
        return None
    locked = state.get("locked_version")
    if locked and "," not in locked:
        return locked
    specifier = (state.get("specifier") or "").strip()
    if specifier.startswith("==") and "," not in specifier and "*" not in specifier:
        return specifier[2:].strip()
    return None


def upgrades(
    diff: dict,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str | None]]]:
    """(name, from, to) for each changed package with exact versions on both sides, and added packages."""
    changed = {
        (c["name"], _version(c.get("old")), _version(c.get("new")))
        for c in diff.get("changed", [])
    }
    pairs = sorted((n, a, b) for n, a, b in changed if a and b and a != b)
    added = sorted({(a["name"], _version(a.get("new"))) for a in diff.get("added", [])})
    return pairs, added


def unresolved(diff: dict) -> list[str]:
    """Changed packages whose versions are ranges on one side, so there is no exact pair to compare."""
    names = []
    for c in diff.get("changed", []):
        a, b = _version(c.get("old")), _version(c.get("new"))
        if not (a and b) and c["name"] not in names:
            names.append(c["name"])
    return names


def create_check(client: Client, repository: str, head_sha: str) -> int | None:
    from codeintent.upgrades.report import CHECK_NAME

    response = client.request(
        "POST",
        f"/repos/{repository}/check-runs",
        json={"name": CHECK_NAME, "head_sha": head_sha, "status": "in_progress"},
    )
    return response.json().get("id") if response.status_code == 201 else None


def complete_check(
    client: Client,
    repository: str,
    head_sha: str,
    check_id: int | None,
    conclusion: str,
    output: dict,
    details_url: str | None,
) -> int | None:
    from codeintent.upgrades.report import CHECK_NAME

    body = {"status": "completed", "conclusion": conclusion, "output": output}
    if details_url:
        body["details_url"] = details_url
    if check_id:
        response = client.request(
            "PATCH", f"/repos/{repository}/check-runs/{check_id}", json=body
        )
        if response.status_code == 200:
            return check_id
    response = client.request(
        "POST",
        f"/repos/{repository}/check-runs",
        json={"name": CHECK_NAME, "head_sha": head_sha, **body},
    )
    return response.json().get("id") if response.status_code == 201 else None


def upsert_comment(
    client: Client, repository: str, number: int, body: str, comment_id: int | None
) -> int | None:
    """Edit our earlier comment on the PR if it still exists, else post a new one."""
    if comment_id:
        response = client.request(
            "PATCH",
            f"/repos/{repository}/issues/comments/{comment_id}",
            json={"body": body},
        )
        if response.status_code == 200:
            return comment_id
    response = client.request(
        "POST", f"/repos/{repository}/issues/{number}/comments", json={"body": body}
    )
    return response.json().get("id") if response.status_code == 201 else None
