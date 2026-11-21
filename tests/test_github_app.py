"""GitHub App webhook signatures and PR dependency diffs, checked against real recorded data.

Fixtures under tests/fixtures/github_app/<case>/ were fetched from real merged Dependabot PRs:
pull.json holds the PR's real file listing and SHAs; base/ and head/ hold the real file
contents at the merge base and head commit.
"""

import hashlib
import hmac
import json
from pathlib import Path

import pytest

from codeintent.github_app import dependency_changes, manifest_root, verify_signature

FIXTURES = Path(__file__).parent / "fixtures" / "github_app"

# From docs.github.com "Validating webhook deliveries" > "Testing the webhook payload validation".
DOCS_SECRET = "It's a Secret to Everybody"
DOCS_PAYLOAD = b"Hello, World!"
DOCS_SIGNATURE = (
    "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"
)


def test_signature_matches_github_documented_vector():
    assert verify_signature(DOCS_PAYLOAD, DOCS_SECRET, DOCS_SIGNATURE)


@pytest.mark.parametrize(
    "body,secret,header",
    [
        (b"Hello, World?", DOCS_SECRET, DOCS_SIGNATURE),
        (DOCS_PAYLOAD, "another secret", DOCS_SIGNATURE),
        (DOCS_PAYLOAD, DOCS_SECRET, DOCS_SIGNATURE.removeprefix("sha256=")),
        (DOCS_PAYLOAD, DOCS_SECRET, ""),
        (DOCS_PAYLOAD, DOCS_SECRET, None),
        (DOCS_PAYLOAD, "", DOCS_SIGNATURE),
    ],
)
def test_signature_rejects_tampering_and_missing_values(body, secret, header):
    assert not verify_signature(body, secret, header)


def test_signature_covers_raw_bytes_not_reserialised_json():
    raw = b'{"zen":  "Keep it logically awesome.", "hook_id": 1}'
    header = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
    assert verify_signature(raw, "s3cret", header)
    assert not verify_signature(json.dumps(json.loads(raw)).encode(), "s3cret", header)


class Recorded:
    """Serves one real PR's recorded API data through the client interface."""

    def __init__(self, case: str):
        self.root = FIXTURES / case
        self.pull = json.loads((self.root / "pull.json").read_text())

    def pull_files(self, repository, number):
        assert (repository, number) == (self.pull["repository"], self.pull["number"])
        return self.pull["files"], False

    def merge_base(self, repository, base, head):
        return self.pull["merge_base"]

    def file_text(self, repository, path, ref):
        side = "head" if ref == self.pull["head_sha"] else "base"
        assert ref in (self.pull["head_sha"], self.pull["merge_base"])
        file = self.root / side / path
        return file.read_text() if file.exists() else None


def changes(case: str) -> dict:
    client = Recorded(case)
    pull = client.pull
    diff = dependency_changes(
        client, pull["repository"], pull["number"], pull["base_sha"], pull["head_sha"]
    )
    assert diff["added"] == diff["removed"] == []
    return diff


def summary(diff: dict) -> set[tuple]:
    return {
        (c["file"], c["name"], c["old"]["specifier"], c["new"]["specifier"],
         c["old"]["locked_version"], c["new"]["locked_version"])
        for c in diff["changed"]
    }  # fmt: skip


def test_pyproject_bump_matches_pr_title():
    # "build(deps-dev): bump virtualenv from 21.15.0 to 21.15.1"
    diff = changes("pyproject-virtualenv")
    assert summary(diff) == {
        ("pyproject.toml", "virtualenv", "==21.15.0", "==21.15.1", "21.15.0", "21.15.1")
    }
    assert diff["changed"][0]["group"] == "group:development"


def test_requirement_range_change_in_root_and_nested_project():
    # "update daytona requirement from <1.0.0,>=0.231.0 to >=0.231.1,<1.0.0"
    diff = changes("requirements-daytona")
    old, new = "<1.0.0,>=0.231.0", "<1.0.0,>=0.231.1"
    assert summary(diff) == {
        ("requirements.txt", "daytona", old, new, None, None),
        ("backend/requirements.txt", "daytona", old, new, None, None),
    }


def test_uv_lock_group_update_reports_each_locked_bump():
    # "bump the uv-dependencies group with 3 updates": slack-sdk 3.46.0 -> 3.47.0, ruff, ty
    diff = changes("uv-lock-group")
    assert {(c["name"], c["old"]["locked_version"], c["new"]["locked_version"])
            for c in diff["changed"]} == {
        ("slack-sdk", "3.46.0", "3.47.0"),
        ("ruff", "0.17.4", "0.17.5"),
        ("ty", "0.0.101", "0.0.103"),
    }  # fmt: skip
    assert all(c["file"] == "uv.lock" and c["direct"] for c in diff["changed"])


def test_files_outside_the_manifest_parser_are_not_downloaded():
    # The PR bumps pytest in development-requirements.txt, a name scan() does not read.
    diff = changes("unsupported-requirements-name")
    assert diff["files"] == [] and diff["changed"] == [] and diff["merge_base"] is None


@pytest.mark.parametrize(
    "path,root",
    [
        ("pyproject.toml", "."),
        ("backend/requirements.txt", "backend"),
        ("requirements/dev.in", "."),
        ("svc/requirements/requirements-dev.txt", "svc"),
        ("requirements-test.lock", "."),
        ("pkg/poetry.lock", "pkg"),
        ("development-requirements.txt", None),
        ("docs/conf.py", None),
        ("requirements/notes.md", None),
    ],
)
def test_manifest_root_mirrors_scan(path, root):
    assert manifest_root(path) == root
