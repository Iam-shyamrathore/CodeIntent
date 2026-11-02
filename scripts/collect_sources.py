"""Collect a bounded public corpus with immutable source identities and hashes.

This deliberately collects selected historical cases, not all HTTPX history.
No target repository code is executed.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydriller import Repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".data"
REPO = ROOT / ".external/httpx"
PR_NUMBERS = [2241, 2481, 3050, 2074]
ISSUE_NUMBERS = [2462, 1850]


def collect() -> dict:
    DATA.mkdir(exist_ok=True)
    headers = {
        "User-Agent": "CodeIntent-feasibility",
        "Accept": "application/vnd.github+json",
    }
    token = subprocess.run(
        ["gh", "auth", "token"], check=False, capture_output=True, text=True
    )
    if token.returncode == 0:
        headers["Authorization"] = f"Bearer {token.stdout.strip()}"
    documents, links, pulls = [], [], []
    fetched = datetime.now(UTC).isoformat()
    client = httpx.Client(headers=headers, timeout=30, follow_redirects=False)

    def request(path: str):
        response = client.get(
            "https://api.github.com/repos/encode/httpx" + ("/" + path if path else "")
        )
        response.raise_for_status()
        return response

    def pages(path: str) -> list:
        result, page = [], 1
        while True:
            sep = "&" if "?" in path else "?"
            response = request(f"{path}{sep}per_page=100&page={page}")
            batch = response.json()
            result.extend(batch)
            if 'rel="next"' not in response.headers.get("link", ""):
                return result
            page += 1
            if page > 10:
                raise RuntimeError(
                    "Source pagination exceeded the spike's explicit limit"
                )

    def add(
        doc_id: str,
        kind: str,
        title: str,
        body: str,
        url: str,
        date: str,
        author: str,
        **extra,
    ):
        item = {
            "id": doc_id,
            "kind": kind,
            "title": title,
            "body": body,
            "url": url,
            "date": date,
            "author": author,
            "retrieved_at": fetched,
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            **extra,
        }
        documents.append(item)
        return doc_id

    try:
        metadata = request("").json()
        revision = subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
        ).strip()
        for number in PR_NUMBERS:
            pr = request(f"pulls/{number}").json()
            pulls.append(pr)
            pid = add(
                f"pr-{number}",
                "pull_request",
                pr["title"],
                pr.get("body") or "",
                pr["html_url"],
                pr["merged_at"] or pr["created_at"],
                pr["user"]["login"],
                number=number,
                merged_at=pr["merged_at"],
                commit=pr["merge_commit_sha"],
            )
            for path, kind in [
                (f"issues/{number}/comments", "comment"),
                (f"pulls/{number}/reviews", "review"),
                (f"pulls/{number}/comments", "review_comment"),
            ]:
                for c in pages(path):
                    if not c.get("body"):
                        continue
                    cid = add(
                        f"{kind}-{c['id']}",
                        kind,
                        f"{kind.replace('_', ' ').title()} on PR #{number}",
                        c["body"],
                        c["html_url"],
                        c.get("created_at") or c.get("submitted_at") or fetched,
                        c["user"]["login"],
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
            for f in pages(f"pulls/{number}/files"):
                if f.get("patch"):
                    fid = add(
                        f"diff-{number}-{f['filename']}",
                        "diff",
                        f"{f['filename']} · PR #{number}",
                        f["patch"],
                        f["blob_url"],
                        pr["merged_at"],
                        pr["user"]["login"],
                        parent=pid,
                        path=f["filename"],
                        number=number,
                        commit=pr["merge_commit_sha"],
                    )
                    links.append(
                        {
                            "source": pid,
                            "target": fid,
                            "relation": "CHANGES",
                            "evidence": fid,
                        }
                    )
            for issue in ISSUE_NUMBERS:
                if f"#{issue}" in (pr.get("body") or ""):
                    links.append(
                        {
                            "source": pid,
                            "target": f"issue-{issue}",
                            "relation": "REFERENCES",
                            "evidence": pid,
                        }
                    )
        for number in ISSUE_NUMBERS:
            issue = request(f"issues/{number}").json()
            iid = add(
                f"issue-{number}",
                "issue",
                issue["title"],
                issue.get("body") or "",
                issue["html_url"],
                issue["created_at"],
                issue["user"]["login"],
                number=number,
            )
            for c in pages(f"issues/{number}/comments"):
                cid = add(
                    f"comment-{c['id']}",
                    "comment",
                    f"Comment on issue #{number}",
                    c["body"],
                    c["html_url"],
                    c["created_at"],
                    c["user"]["login"],
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
        comment = request("issues/comments/1727389402").json()
        add(
            f"comment-{comment['id']}",
            "comment",
            "Earlier transport API rationale",
            comment["body"],
            comment["html_url"],
            comment["created_at"],
            comment["user"]["login"],
            parent="pr-3050",
        )
        links.append(
            {
                "source": "pr-3050",
                "target": f"comment-{comment['id']}",
                "relation": "CITES_RATIONALE",
                "evidence": "pr-3050",
            }
        )
        git_records = []
        for pr in pulls:
            for c in Repository(
                str(REPO), single=pr["merge_commit_sha"]
            ).traverse_commits():
                git_records.append(
                    {
                        "sha": c.hash,
                        "date": c.committer_date.isoformat(),
                        "message": c.msg,
                        "paths": [m.new_path or m.old_path for m in c.modified_files],
                    }
                )
        for rel in ["httpx/_urls.py", "httpx/_client.py"]:
            body = (REPO / rel).read_text()
            add(
                "code-" + rel.replace("/", "-"),
                "code",
                rel,
                body,
                f"https://github.com/encode/httpx/blob/{revision}/{rel}",
                fetched,
                "Repository source",
                path=rel,
                commit=revision,
            )
        result = {
            "repository": "encode/httpx",
            "repository_id": metadata["id"],
            "revision": revision,
            "collected_at": fetched,
            "documents": documents,
            "links": links,
            "git_records": git_records,
            "coverage": {
                "scope": "Four selected historical PRs, two linked issues, their comments/reviews, one rationale comment and two current source files",
                "full_repository_history": False,
                "pull_requests": PR_NUMBERS,
                "issues": ISSUE_NUMBERS,
                "complete_for_selected_endpoints": True,
            },
        }
        (DATA / "corpus.json").write_text(json.dumps(result, indent=2))
        print(
            json.dumps(
                {
                    "documents": len(documents),
                    "links": len(links),
                    "git_commits": len(git_records),
                    "revision": revision,
                }
            )
        )
        return result
    finally:
        client.close()


if __name__ == "__main__":
    collect()
