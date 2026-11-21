"""Locate a package's source repository and the git commits behind two of its PyPI releases.

Repository evidence, strongest first: PyPI attestations (PEP 740) naming the publishing repository,
``project_urls`` with PEP 753 label normalisation, then deps.dev. Tag matching follows the heuristics
of dependabot-core's metadata and commits finders (MIT): try likely tag names directly, then scan the
tag list for one whose embedded version equals the release, then fall back to the last commit before
the release was uploaded.
"""

from __future__ import annotations

import re
import string
from urllib.parse import quote, urlparse

import httpx
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from codeintent.github import GitHub
from codeintent.upgrades import artifacts
from codeintent.upgrades.models import ReleasePoint, ReleaseRange
from codeintent.upgrades.repository import token

DEPS_DEV = "https://api.deps.dev/v3/systems/pypi/packages"
INTEGRITY = "https://pypi.org/integrity"
SOURCE_LABELS = ("source", "sourcecode", "repository", "code", "github", "homepage")
TAG_VERSION = re.compile(
    r"(\d+(?:\.\d+)*(?:[._-]?(?:a|b|rc|alpha|beta|post|dev)\.?\d*)*)"
)
MAX_TAG_PAGES = 10


def _label(text: str) -> str:
    return "".join(
        c for c in text.lower() if c not in string.punctuation and not c.isspace()
    )


def github_repository(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if parsed.netloc.lower() not in ("github.com", "www.github.com"):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    return f"{parts[0]}/{parts[1].removesuffix('.git')}".lower()


class Locator:
    def __init__(self, pypi: httpx.Client):
        self.pypi = pypi

    def repository(
        self, name: str, version: str, info: dict, files: list[dict]
    ) -> tuple[str | None, str | None]:
        for file in files:
            response = self.pypi.get(
                f"{INTEGRITY}/{canonicalize_name(name)}/{version}/{file['filename']}/provenance"
            )
            if response.status_code == 200:
                for bundle in response.json().get("attestation_bundles", []):
                    publisher = bundle.get("publisher") or {}
                    if publisher.get("kind") == "GitHub" and publisher.get(
                        "repository"
                    ):
                        return publisher["repository"].lower(), "attestation"
            break
        urls = {_label(k): v for k, v in (info.get("project_urls") or {}).items()}
        urls.setdefault("homepage", info.get("home_page"))
        for label in SOURCE_LABELS:
            if found := github_repository(urls.get(label)):
                return found, "project-urls"
        response = self.pypi.get(
            f"{DEPS_DEV}/{quote(canonicalize_name(name))}/versions/{quote(version)}"
        )
        if response.status_code == 200:
            for link in response.json().get("links", []):
                if link.get("label") == "SOURCE_REPO" and (
                    found := github_repository(link.get("url"))
                ):
                    return found, "deps.dev"
        for value in urls.values():
            if found := github_repository(value):
                return found, "project-urls"
        return None, None


class Repository:
    def __init__(self, full_name: str):
        self.api = GitHub(full_name).client
        if "Authorization" not in self.api.headers:
            secret = token()
            if secret:
                self.api.headers["Authorization"] = f"Bearer {secret}"
        response = self.api.get(f"/repos/{full_name}")
        if response.status_code in (301, 307):
            response = self.api.get(response.headers["location"])
        if response.status_code != 200:
            raise LookupError(
                f"repository {full_name} returned HTTP {response.status_code}"
            )
        meta = response.json()
        self.full_name, self.default_branch = (
            meta["full_name"].lower(),
            meta["default_branch"],
        )
        self._tags: list[dict] | None = None

    def commit_of(self, ref: dict) -> str:
        target = ref["object"]
        while target["type"] == "tag":
            target = self.api.get(
                f"/repos/{self.full_name}/git/tags/{target['sha']}"
            ).json()["object"]
        return target["sha"]

    def exact(self, candidates: list[str]) -> tuple[str, str] | None:
        for tag in candidates:
            response = self.api.get(
                f"/repos/{self.full_name}/git/ref/tags/{quote(tag, safe='')}"
            )
            if response.status_code == 200 and isinstance(response.json(), dict):
                return tag, self.commit_of(response.json())
        return None

    def tags(self) -> list[dict]:
        if self._tags is None:
            self._tags = []
            for page in range(1, MAX_TAG_PAGES + 1):
                response = self.api.get(
                    f"/repos/{self.full_name}/tags",
                    params={"per_page": 100, "page": page},
                )
                if response.status_code != 200:
                    break
                self._tags += response.json()
                if 'rel="next"' not in response.headers.get("link", ""):
                    break
        return self._tags

    def scan(self, package: str, version: Version) -> tuple[str, str] | None:
        matches = []
        for tag in self.tags():
            for found in TAG_VERSION.findall(tag["name"]):
                try:
                    if Version(found) == version:
                        matches.append(tag)
                        break
                except InvalidVersion:
                    continue
        if not matches:
            return None
        named = [t for t in matches if package in canonicalize_name(t["name"])]
        best = min(named or matches, key=lambda t: len(t["name"]))
        return best["name"], best["commit"]["sha"]

    def before(self, published: str) -> str | None:
        response = self.api.get(
            f"/repos/{self.full_name}/commits",
            params={"sha": self.default_branch, "until": published, "per_page": 1},
        )
        rows = response.json() if response.status_code == 200 else []
        return rows[0]["sha"] if rows else None


def _candidates(name: str, version: str) -> list[str]:
    normalized = str(Version(version))
    names = dict.fromkeys([name, canonicalize_name(name), name.lower()])
    tags = [f"v{normalized}", normalized, f"v{version}", version]
    for n in names:
        tags += [
            f"{n}-{normalized}",
            f"{n}-v{normalized}",
            f"{n}@{normalized}",
            f"{n}/{normalized}",
        ]
    tags += [f"release-{normalized}", f"release/{normalized}"]
    return list(dict.fromkeys(tags))


def _point(
    name: str, version: str, data: dict, repo: Repository | None
) -> ReleasePoint:
    files = data["urls"]
    published = min((f["upload_time_iso_8601"] for f in files), default=None)
    point = ReleasePoint(
        version=version, published=published, yanked=bool(data["info"].get("yanked"))
    )
    if repo is None:
        return point
    if found := repo.exact(_candidates(name, version)):
        return point.model_copy(
            update={"tag": found[0], "commit": found[1], "match": "exact-ref"}
        )
    if found := repo.scan(canonicalize_name(name), Version(version)):
        return point.model_copy(
            update={"tag": found[0], "commit": found[1], "match": "tag-list"}
        )
    if published and (commit := repo.before(published)):
        return point.model_copy(update={"commit": commit, "match": "release-date"})
    return point


def locate(name: str, start: str, end: str, pypi: httpx.Client) -> ReleaseRange:
    """Repository and release commits for upgrading ``name`` from ``start`` to ``end``."""
    try:
        first, last = (
            artifacts.release(name, start, pypi),
            artifacts.release(name, end, pypi),
        )
    except artifacts.ArtifactError as error:
        point = ReleasePoint(version=start)
        return ReleaseRange(
            package=name,
            start=point,
            end=ReleasePoint(version=end),
            not_located=error.detail,
        )
    found, evidence = Locator(pypi).repository(name, end, last["info"], last["urls"])
    repo, reason = None, None
    if found is None:
        reason = "no GitHub repository is declared in PyPI metadata or deps.dev"
    else:
        try:
            repo = Repository(found)
        except LookupError as error:
            reason = str(error)
    return ReleaseRange(
        package=canonicalize_name(name),
        repository=repo.full_name if repo else found,
        evidence=evidence,
        start=_point(name, start, first, repo),
        end=_point(name, end, last, repo),
        not_located=reason,
    )
