"""Mechanically sample "harmless" upgrade cases from merged Dependabot PRs.

A case is a merged Dependabot PR that bumps exactly one PyPI package (patch or
minor) in a mature public Python repo, whose head commit had green checks and
which contained nothing but Dependabot's own manifest/lockfile edits. The
consumer ref is the PR's base commit (the code before the bump).

Sampling is deterministic for a fixed set of past single-day merge windows:
for each (day, ecosystem) GitHub search query we walk results in `created`
ascending order, page by page, apply the filters below in order, and stop as
soon as `--target` cases are accepted. Every rejection is counted per filter.
GitHub prunes check runs after roughly a year, so windows must be recent and
the check summary is frozen into each case's evidence at sampling time.

Usage:
    uv run python scripts/sample_harmless.py                 # dry run, prints report + JSON
    uv run python scripts/sample_harmless.py --write evals/upgrades.json

`--write` replaces every `"label": "harmless"` case in the file and keeps the
hand-verified cases untouched. Needs a GitHub token (GITHUB_TOKEN or `gh auth token`).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from packaging.version import InvalidVersion, Version

GRAPHQL = "https://api.github.com/graphql"

# --- sampling frame -------------------------------------------------------
# GitHub search cannot filter PRs by repo stars, and a month of Dependabot PRs is
# ~30k results (search caps at 1000), so we walk single-day merge windows. For
# each (day, head) query we take results in created-ascending order, 100 per
# page, up to the 1000-result cap, and filter mechanically.
QUERY_TEMPLATE = "is:pr is:merged author:app/dependabot language:Python {head} merged:{day} sort:created-asc"
HEADS = ("head:dependabot/pip", "head:dependabot/uv")
FIRST_DAY = "2026-08-03"  # past, closed windows; GitHub prunes check runs after ~1 year
MAX_DAYS = 28
MAX_PAGES_PER_QUERY = 10  # GitHub search caps at 1000 results.
PAGE_SIZE = 100

# --- filters --------------------------------------------------------------
MIN_STARS = 500
MAX_PER_REPO = 2
HEAD_PREFIXES = ("dependabot/pip/", "dependabot/uv/")
TITLE_RE = re.compile(
    r"^(?:[^:]*:\s*)?[Bb]ump\s+(?P<pkg>[A-Za-z0-9][A-Za-z0-9._\-\[\]]*)\s+"
    r"from\s+(?P<from>\S+)\s+to\s+(?P<to>\S+?)(?:\s+in\s+(?P<dir>\S+))?\s*$"
)
MANIFEST_RE = re.compile(
    r"(^|/)("
    r"pyproject\.toml|uv\.lock|poetry\.lock|Pipfile|Pipfile\.lock|setup\.cfg|setup\.py|"
    r"[^/]*requirements[^/]*\.(txt|in)|[^/]*constraints[^/]*\.txt|requirements/[^/]+\.(txt|in)"
    r")$"
)
DOCS_CI_RE = re.compile(r"(^|/)(docs?|\.github)/|(^|/)[^/]*docs?[^/]*\.(txt|in)$", re.I)
FILTERS = [
    "repo_not_mature",  # stars < MIN_STARS, fork, or archived
    "not_pip_or_uv_branch",  # head ref not dependabot/pip/* or dependabot/uv/*
    "not_single_package_title",  # grouped / multi-package / unparseable title
    "not_patch_or_minor",  # major bump, 0.x minor bump, prerelease, or unparseable
    "docs_or_ci_only",  # bump only in docs/ or .github/ requirements (not the consumer's code deps)
    "repo_cap_reached",  # already MAX_PER_REPO cases from this repo
    "not_on_pypi",  # package or either version missing on PyPI
    "extra_commits",  # PR contains commits not authored by dependabot
    "non_manifest_files",  # PR touches files other than Python dependency manifests
    "checks_not_green",  # head statusCheckRollup missing / not SUCCESS / no check actually succeeded
]

SEARCH_GQL = (
    """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: %d, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        id number url title headRefName createdAt mergedAt
        repository { nameWithOwner stargazerCount isFork isArchived }
      }
    }
  }
}
"""
    % PAGE_SIZE
)

DETAIL_GQL = """
query($id: ID!) {
  node(id: $id) {
    ... on PullRequest {
      baseRefName baseRefOid headRefOid
      mergeCommit { oid }
      files(first: 30) { totalCount nodes { path } }
      commits(first: 20) {
        totalCount
        nodes { commit { oid author { name email user { login } } } }
      }
      last: commits(last: 1) {
        nodes { commit { oid statusCheckRollup {
          state
          contexts(first: 100) {
            totalCount
            nodes {
              __typename
              ... on CheckRun { name conclusion status }
              ... on StatusContext { context state }
            }
          }
        } } }
      }
    }
  }
}
"""


def token() -> str:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    return subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, check=True
    ).stdout.strip()


class GitHub:
    def __init__(self) -> None:
        self.http = httpx.Client(
            headers={"Authorization": f"bearer {token()}"}, timeout=60
        )

    def gql(self, query: str, variables: dict) -> dict:
        for attempt in range(6):
            r = self.http.post(GRAPHQL, json={"query": query, "variables": variables})
            if r.status_code in (502, 503, 504) or (
                r.status_code == 403 and "rate limit" in r.text.lower()
            ):
                time.sleep(10 * (attempt + 1))
                continue
            r.raise_for_status()
            body = r.json()
            if body.get("errors"):
                msg = json.dumps(body["errors"])[:300]
                if "RATE_LIMITED" in msg or "secondary" in msg.lower():
                    time.sleep(30 * (attempt + 1))
                    continue
                raise RuntimeError(msg)
            return body["data"]
        raise RuntimeError("GitHub GraphQL retries exhausted")


class PyPI:
    def __init__(self) -> None:
        self.http = httpx.Client(timeout=30, follow_redirects=True)
        self.cache: dict[str, set[str] | None] = {}

    def releases(self, pkg: str) -> set[str] | None:
        name = re.sub(r"\[.*\]$", "", pkg).lower()
        if name not in self.cache:
            r = self.http.get(f"https://pypi.org/pypi/{name}/json")
            self.cache[name] = (
                set(r.json()["releases"]) if r.status_code == 200 else None
            )
        return self.cache[name]


def bump_kind(old: str, new: str) -> str | None:
    """Return 'patch'/'minor' for acceptable bumps, None otherwise."""
    try:
        a, b = Version(old), Version(new)
    except InvalidVersion:
        return None
    if b <= a or a.is_prerelease or b.is_prerelease or b.is_devrelease:
        return None
    ra = ((*a.release, 0, 0, 0))[:3]
    rb = ((*b.release, 0, 0, 0))[:3]
    if ra[0] != rb[0]:
        return None
    if ra[1] != rb[1]:
        return None if ra[0] == 0 else "minor"  # 0.x minor bumps are semver-major
    return "patch"


def check_summary(rollup: dict | None) -> tuple[str | None, str]:
    if not rollup:
        return None, "no checks or statuses reported on head commit"
    counts: Counter[str] = Counter()
    for node in rollup["contexts"]["nodes"]:
        if node["__typename"] == "CheckRun":
            counts[(node["conclusion"] or node["status"] or "unknown").lower()] += 1
        else:
            counts[(node["state"] or "unknown").lower()] += 1
    parts = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
    total = rollup["contexts"]["totalCount"]
    return rollup[
        "state"
    ], f"statusCheckRollup={rollup['state']} ({total} checks/statuses: {parts})"


def is_dependabot(commit: dict) -> bool:
    author = commit["author"] or {}
    login = ((author.get("user") or {}).get("login") or "").lower()
    name = (author.get("name") or "").lower()
    email = (author.get("email") or "").lower()
    return "dependabot" in login or "dependabot" in name or "dependabot" in email


def days() -> list[str]:
    start = datetime.date.fromisoformat(FIRST_DAY)
    return [(start + datetime.timedelta(days=n)).isoformat() for n in range(MAX_DAYS)]


def sample(target: int, log) -> tuple[list[dict], Counter, int, list[str]]:
    gh, pypi = GitHub(), PyPI()
    rejected: Counter[str] = Counter()
    per_repo: defaultdict[str, int] = defaultdict(int)
    accepted: list[dict] = []
    queries: list[str] = []
    seen = 0
    for day in days():
        for head in HEADS:
            q = QUERY_TEMPLATE.format(head=head, day=day)
            queries.append(q)
            after = None
            for page in range(1, MAX_PAGES_PER_QUERY + 1):
                data = gh.gql(SEARCH_GQL, {"q": q, "after": after})["search"]
                log(f"query={q!r} page={page} issueCount={data['issueCount']}")
                for pr in data["nodes"]:
                    if not pr:
                        continue
                    seen += 1
                    reason, case = evaluate(gh, pypi, pr, per_repo, q)
                    if reason:
                        rejected[reason] += 1
                        continue
                    per_repo[pr["repository"]["nameWithOwner"]] += 1
                    accepted.append(case)
                    log(f"  accept #{len(accepted)}: {case['id']}")
                    if len(accepted) >= target:
                        return accepted, rejected, seen, queries
                if not data["pageInfo"]["hasNextPage"]:
                    break
                after = data["pageInfo"]["endCursor"]
    return accepted, rejected, seen, queries


def evaluate(
    gh: GitHub, pypi: PyPI, pr: dict, per_repo, query: str
) -> tuple[str | None, dict | None]:
    repo = pr["repository"]
    name = repo["nameWithOwner"]
    if repo["stargazerCount"] < MIN_STARS or repo["isFork"] or repo["isArchived"]:
        return "repo_not_mature", None
    if not pr["headRefName"].startswith(HEAD_PREFIXES):
        return "not_pip_or_uv_branch", None
    m = TITLE_RE.match(pr["title"].strip())
    if not m:
        return "not_single_package_title", None
    pkg, old, new = m["pkg"], m["from"], m["to"]
    kind = bump_kind(old, new)
    if not kind:
        return "not_patch_or_minor", None
    if m["dir"] and DOCS_CI_RE.search(m["dir"].strip("/") + "/"):
        return "docs_or_ci_only", None
    if per_repo[name] >= MAX_PER_REPO:
        return "repo_cap_reached", None
    releases = pypi.releases(pkg)
    if releases is None or old not in releases or new not in releases:
        return "not_on_pypi", None
    detail = gh.gql(DETAIL_GQL, {"id": pr["id"]})["node"]
    commits = [n["commit"] for n in detail["commits"]["nodes"]]
    if detail["commits"]["totalCount"] > len(commits) or not all(
        map(is_dependabot, commits)
    ):
        return "extra_commits", None
    files = [n["path"] for n in detail["files"]["nodes"]]
    if (
        not files
        or detail["files"]["totalCount"] > len(files)
        or not all(MANIFEST_RE.search(f) for f in files)
    ):
        return "non_manifest_files", None
    if all(DOCS_CI_RE.search(f) for f in files):
        return "docs_or_ci_only", None
    head = detail["last"]["nodes"][0]["commit"]
    state, summary = check_summary(head["statusCheckRollup"])
    if state != "SUCCESS" or " success" not in summary.split("(", 1)[-1]:
        return "checks_not_green", None
    owner_repo = name.lower().replace("/", "-")
    case = {
        "id": f"harmless-{owner_repo}-{pr['number']}",
        "label": "harmless",
        "consumer": {
            "repo": name,
            "ref": detail["baseRefOid"],
            "commit": detail["baseRefOid"],
        },
        "package": re.sub(r"\[.*\]$", "", pkg).lower(),
        "from": old,
        "to": new,
        "expected": [],
        "evidence": [
            pr["url"],
            f"https://github.com/{name}/commit/{head['oid']}/checks",
            f"{summary} at head {head['oid']}",
        ],
        "notes": (
            f"Mechanically sampled ({kind} bump). Merged {pr['mergedAt']} into {detail['baseRefName']}; "
            f"merge commit {(detail['mergeCommit'] or {}).get('oid')}. "
            f"Files: {', '.join(files)}. Stars at sampling: {repo['stargazerCount']}. "
            f"Query: {query}"
        ),
    }
    return None, case


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--target", type=int, default=80)
    parser.add_argument(
        "--write", type=Path, help="merge harmless cases into this upgrades.json"
    )
    args = parser.parse_args()

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    log("Query template: " + QUERY_TEMPLATE)
    log(
        f"Heads: {', '.join(HEADS)}; days: {FIRST_DAY} + up to {MAX_DAYS} days; sort created-asc; <= {MAX_PAGES_PER_QUERY} pages x {PAGE_SIZE}"
    )
    log(
        f"Filters (in order): stars>={MIN_STARS}, not fork/archived; head ref in {HEAD_PREFIXES}; "
        f"title matches single 'Bump X from A to B'; same major and not 0.x-minor, no prerelease; "
        f"not a docs/.github-only bump; <= {MAX_PER_REPO} per repo; package+versions on PyPI; "
        f"only dependabot commits; only dependency manifests changed; "
        f"head statusCheckRollup == SUCCESS with >= 1 successful check"
    )
    accepted, rejected, seen, queries = sample(args.target, log)
    log(
        f"\nRan {len(queries)} queries (last: {queries[-1]!r}); {seen} PR search results; accepted {len(accepted)}."
    )
    for f in FILTERS:
        log(f"  rejected by {f}: {rejected.get(f, 0)}")

    if args.write:
        existing = json.loads(args.write.read_text()) if args.write.exists() else []
        kept = [c for c in existing if c.get("label") != "harmless"]
        args.write.write_text(json.dumps(kept + accepted, indent=2) + "\n")
        log(
            f"Wrote {len(kept)} curated + {len(accepted)} harmless cases to {args.write}"
        )
    else:
        print(json.dumps(accepted, indent=2))


if __name__ == "__main__":
    main()
