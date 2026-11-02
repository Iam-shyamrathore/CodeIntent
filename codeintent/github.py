"""Bounded public GitHub collection; no repository code or hooks are executed."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx


class CollectionError(Exception):
    pass


def canonical_repository(value: str) -> str:
    value = value.strip().removesuffix(".git").rstrip("/")
    if value.startswith("https://"):
        parsed = urlparse(value)
        if parsed.netloc != "github.com" or parsed.query or parsed.fragment:
            raise ValueError("Use a public github.com repository")
        value = parsed.path.strip("/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value):
        raise ValueError("Use owner/repository or its GitHub URL")
    if value.split("/")[1] in {".", ".."}:
        raise ValueError("Invalid repository name")
    return value.lower()


class GitHub:
    def __init__(self, repository: str):
        self.repository = canonical_repository(repository)
        self.requests = 0
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "CodeIntent/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if os.getenv("GITHUB_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
        self.client = httpx.Client(
            base_url="https://api.github.com",
            headers=headers,
            timeout=30,
            follow_redirects=False,
        )

    def get(self, path: str, params=None):
        self.requests += 1
        if self.requests > 350:
            raise CollectionError(
                "Collection reached the 350-request limit. Import fewer pull requests."
            )
        response = self.client.get(
            f"/repos/{self.repository}" + ("/" + path if path else ""), params=params
        )
        if response.status_code in [403, 429]:
            raise CollectionError(
                "GitHub rate limit or access restriction. Check the server GitHub token, then retry."
            )
        if response.status_code == 404:
            raise CollectionError(
                "Repository or source was not found. Only public repositories are supported."
            )
        if response.status_code != 200:
            raise CollectionError("GitHub could not return a source. Retry the import.")
        return response

    def pages(self, path: str, *, max_pages=3):
        rows = []
        for page in range(1, max_pages + 1):
            response = self.get(path, {"per_page": 100, "page": page})
            rows.extend(response.json())
            if 'rel="next"' not in response.headers.get("link", ""):
                return rows, True
        return rows, False

    def collect(self, options: dict, update=lambda *args: None) -> dict:
        fetched = datetime.now(UTC).isoformat()
        metadata = self.get("").json()
        if metadata.get("private"):
            raise CollectionError(
                "Private repositories are not supported in the public workspace."
            )
        revision = self.get("commits/" + metadata["default_branch"]).json()["sha"]
        documents, links, records, excluded = [], [], [], []
        seen = set()

        def add(ident, kind, title, body, url, date, author, **extra):
            if ident in seen:
                return ident
            seen.add(ident)
            body = body or ""
            truncated = len(body) > 24000
            body = body[:24000]
            if truncated:
                excluded.append(f"{ident}: source text limited to 24,000 characters")
            documents.append(
                {
                    "id": ident,
                    "kind": kind,
                    "title": title,
                    "body": body,
                    "url": url,
                    "date": date or fetched,
                    "author": author or "Unknown",
                    "retrieved_at": fetched,
                    "sha256": hashlib.sha256(body.encode()).hexdigest(),
                    **extra,
                }
            )
            return ident

        def author(obj):
            return (obj.get("user") or {}).get("login", "Unknown")

        numbers = options.get("pull_requests") or []
        if not numbers:
            pulls = self.get(
                "pulls",
                {
                    "state": "closed",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": options.get("limit", 12),
                },
            ).json()
            numbers = [p["number"] for p in pulls]
        paths = set()
        issues = set(options.get("issues") or [])
        for i, number in enumerate(numbers):
            update(
                "collecting",
                10 + int(35 * i / max(len(numbers), 1)),
                f"Collecting pull request {i + 1} of {len(numbers)}",
            )
            pr = self.get(f"pulls/{number}").json()
            pid = add(
                f"pr-{number}",
                "pull_request",
                pr["title"],
                pr.get("body"),
                pr["html_url"],
                pr.get("merged_at") or pr["created_at"],
                author(pr),
                number=number,
                merged_at=pr.get("merged_at"),
                commit=pr.get("merge_commit_sha"),
                state=pr["state"],
            )
            for endpoint, kind in [
                (f"issues/{number}/comments", "comment"),
                (f"pulls/{number}/reviews", "review"),
                (f"pulls/{number}/comments", "review_comment"),
            ]:
                comments, complete = self.pages(endpoint, max_pages=2)
                if not complete:
                    excluded.append(f"{endpoint}: limited to 200 entries")
                for c in comments:
                    if not c.get("body"):
                        continue
                    cid = add(
                        f"{kind}-{c['id']}",
                        kind,
                        f"{kind.replace('_', ' ').title()} on PR #{number}",
                        c["body"],
                        c["html_url"],
                        c.get("created_at") or c.get("submitted_at"),
                        author(c),
                        parent=pid,
                        number=number,
                    )
                    links.append(
                        {
                            "source": cid,
                            "target": pid,
                            "relation": "DISCUSSES",
                            "evidence": cid,
                        }
                    )
            files, complete = self.pages(f"pulls/{number}/files", max_pages=1)
            if not complete:
                excluded.append(f"PR #{number}: changed files limited to 100")
            for file in files:
                path = file["filename"]
                paths.add(path)
                if file.get("patch") or file.get("previous_filename"):
                    captured_patch = file.get("patch") or json.dumps(
                        {
                            k: file[k]
                            for k in ["filename", "previous_filename", "status"]
                            if k in file
                        },
                        sort_keys=True,
                    )
                    did = add(
                        f"diff-{number}-{path}",
                        "diff",
                        f"{path} · PR #{number}",
                        captured_patch,
                        file.get("blob_url") or pr["html_url"],
                        pr.get("merged_at") or pr["created_at"],
                        author(pr),
                        parent=pid,
                        path=path,
                        previous_path=file.get("previous_filename"),
                        commit=pr.get("merge_commit_sha"),
                        merged_at=pr.get("merged_at"),
                    )
                    links.append(
                        {
                            "source": pid,
                            "target": did,
                            "relation": "CHANGES",
                            "evidence": did,
                        }
                    )
                else:
                    excluded.append(f"PR #{number}, {path}: GitHub omitted the patch")
            # Same-repository explicit references only; numbers in external URLs are not followed.
            issues.update(
                int(n)
                for n in re.findall(r"(?<![\w/])#(\d+)\b", pr.get("body") or "")
                if int(n) not in numbers
            )
            if pr.get("merged_at") and pr.get("merge_commit_sha"):
                sha = pr["merge_commit_sha"]
                commit = self.get(f"commits/{sha}").json()
                cid = add(
                    "commit-" + sha,
                    "commit",
                    commit["commit"]["message"].split("\n")[0],
                    commit["commit"]["message"],
                    commit["html_url"],
                    commit["commit"]["committer"]["date"],
                    (commit.get("author") or {}).get("login", "Repository contributor"),
                    commit=sha,
                )
                links.append(
                    {
                        "source": pid,
                        "target": cid,
                        "relation": "MERGED_AS",
                        "evidence": pid,
                    }
                )
                records.append(
                    {
                        "sha": sha,
                        "date": commit["commit"]["committer"]["date"],
                        "message": commit["commit"]["message"],
                        "paths": [f["filename"] for f in commit.get("files", [])],
                    }
                )
        for number in sorted(issues)[:10]:
            issue = self.get(f"issues/{number}").json()
            iid = add(
                f"issue-{number}",
                "issue",
                issue["title"],
                issue.get("body"),
                issue["html_url"],
                issue["created_at"],
                author(issue),
                number=number,
            )
            comments, complete = self.pages(f"issues/{number}/comments", max_pages=2)
            if not complete:
                excluded.append(f"Issue #{number}: comments limited to 200")
            for c in comments:
                cid = add(
                    f"comment-{c['id']}",
                    "comment",
                    f"Comment on issue #{number}",
                    c.get("body"),
                    c["html_url"],
                    c["created_at"],
                    author(c),
                    parent=iid,
                    number=number,
                )
                links.append(
                    {
                        "source": cid,
                        "target": iid,
                        "relation": "DISCUSSES",
                        "evidence": cid,
                    }
                )
        if len(issues) > 10:
            excluded.append("Linked issues limited to 10")
        update("collecting", 48, "Capturing source files at the indexed revision")
        tree = self.get(f"git/trees/{revision}", {"recursive": 1}).json()
        if tree.get("truncated"):
            excluded.append("GitHub returned a truncated repository tree")
        blobs = {
            f["path"]: f
            for f in tree.get("tree", [])
            if f["type"] == "blob" and f.get("size", 0) <= 100000
        }
        supported = (
            ".py",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".go",
            ".rs",
            ".java",
            ".md",
            ".mdx",
        )
        candidates = sorted(p for p in paths if p in blobs and p.endswith(supported))
        candidates += [
            p
            for p in sorted(blobs)
            if (
                p.lower().startswith(("readme", "docs/adr", "docs/decisions"))
                and p.endswith((".md", ".mdx"))
            )
            and p not in candidates
        ]
        if not candidates:
            candidates = [p for p in sorted(blobs) if p.endswith(supported)][:40]
        for path in candidates[:40]:
            blob = self.get("git/blobs/" + blobs[path]["sha"]).json()
            try:
                body = base64.b64decode(blob["content"]).decode("utf-8")
            except (ValueError, UnicodeError):
                excluded.append(f"{path}: not UTF-8 text")
                continue
            add(
                "code-" + path,
                "design_document" if path.endswith((".md", ".mdx")) else "code",
                path,
                body,
                f"https://github.com/{self.repository}/blob/{revision}/{path}",
                fetched,
                "Repository source",
                path=path,
                commit=revision,
            )
        if len(candidates) > 40:
            excluded.append("Source files limited to 40")
        return {
            "repository": self.repository,
            "repository_id": metadata["id"],
            "revision": revision,
            "collected_at": fetched,
            "documents": documents,
            "links": links,
            "git_records": records,
            "coverage": {
                "scope": f"{len(numbers)} selected pull requests, up to 10 linked issues, bounded comments/reviews and up to 40 source files",
                "full_repository_history": False,
                "pull_requests": numbers,
                "issues": sorted(issues)[:10],
                "complete_for_selected_endpoints": not excluded,
                "excluded": excluded,
                "request_count": self.requests,
                "languages": "Python, JavaScript, TypeScript, Go, Rust and Java symbol extraction; other captured files remain searchable text",
            },
        }

    def close(self):
        self.client.close()
