import pytest

from codeintent.github import CollectionError, GitHub, canonical_repository
from codeintent.parsing import parse_sources
from codeintent.temporal import (
    Candidate,
    implemented_symbol_history,
    validate_decisions,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://github.com/Encode/HTTPX", "encode/httpx"),
        ("encode/httpx.git", "encode/httpx"),
        ("owner/repo-name", "owner/repo-name"),
    ],
)
def test_canonical_github(value, expected):
    assert canonical_repository(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://localhost/a",
        "https://github.com.evil.test/a/b",
        "https://github.com/a/b?token=x",
        "a/../b",
        "/tmp/repo",
        "a/..",
        "git@github.com:a/b",
        "https://github.com/a/b#readme",
    ],
)
def test_repository_network_boundary(value):
    with pytest.raises(ValueError):
        canonical_repository(value)


def test_rate_limit_does_not_leak_upstream_payload():
    import httpx

    github = GitHub("encode/httpx")
    github.client.close()
    github.client = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={"message": "credential-secret"})
        ),
    )
    with pytest.raises(CollectionError, match="rate limit") as exc:
        github.get("")
    assert "credential-secret" not in str(exc.value)
    github.close()


def test_parser_detects_code_without_executing_it():
    rows = parse_sources(
        [
            {
                "id": "code-demo.py",
                "kind": "code",
                "path": "demo.py",
                "body": 'raise RuntimeError("must never execute")\ndef compute(x):\n    return x + 1\ndef main():\n    return compute(2)\n',
            }
        ]
    )
    assert [f["name"] for f in rows[0]["functions"]] == ["compute", "main"]
    assert any(c["name"] == "compute" for c in rows[0]["function_calls"])
    assert not rows[0]["parse_errors"]


def fixture_corpus():
    def source(ident, body, **extra):
        return {
            "id": ident,
            "body": body,
            "kind": "pull_request",
            "date": "2022-01-01T00:00:00Z",
            "merged_at": "2022-01-01T00:00:00Z",
            **extra,
        }

    return {
        "documents": [
            source("pr-1", "Remove the raw declaration."),
            source(
                "diff-1",
                "-    def raw(self):\n-        return tuple()",
                kind="diff",
                path="url.py",
                parent="pr-1",
            ),
            source(
                "pr-2",
                "Restore the raw declaration.",
                date="2022-02-01T00:00:00Z",
                merged_at="2022-02-01T00:00:00Z",
            ),
            source(
                "diff-2",
                "+    def raw(self):\n+        return namedtuple()",
                kind="diff",
                path="url.py",
                parent="pr-2",
            ),
        ]
    }


def test_implemented_history_is_aspect_scoped_and_not_full_rollback():
    events = implemented_symbol_history(fixture_corpus())
    assert len(events) == 2
    assert events[0]["status"] == "replaced_in_aspect"
    assert events[1]["action"] == "restore"
    assert events[1]["replacement"]["aspect"] == "declaration in this file"
    assert "not proof of a full rollback" in events[1]["replacement"]["note"]


def test_equal_symbol_names_in_different_files_do_not_merge():
    corpus = fixture_corpus()
    corpus["documents"][3]["path"] = "other.py"
    assert implemented_symbol_history(corpus) == []


def test_unmerged_restoration_does_not_replace_merged_change():
    corpus = fixture_corpus()
    corpus["documents"][2]["merged_at"] = None
    assert implemented_symbol_history(corpus) == []


def test_signature_edit_does_not_claim_remove_and_restore():
    corpus = fixture_corpus()
    corpus["documents"][1]["body"] += "\n+    def raw(self, option=True):"
    assert implemented_symbol_history(corpus) == []


def test_decision_rejects_fabricated_span():
    candidate = Candidate(
        subject="raw",
        aspect="declaration",
        summary="The raw declaration was removed",
        action="remove",
        source_id="pr-1",
        span_ids=["invented"],
    )
    assert validate_decisions([candidate], fixture_corpus()) == []


def test_decision_rejects_foreign_parent_evidence():
    candidate = Candidate(
        subject="raw",
        aspect="declaration",
        summary="The raw declaration was removed",
        action="remove",
        source_id="pr-1",
        span_ids=["pr-2:0"],
    )
    assert validate_decisions([candidate], fixture_corpus()) == []


def test_javascript_arrow_functions_have_named_symbols():
    rows = parse_sources(
        [
            {
                "id": "code-main.ts",
                "kind": "code",
                "path": "main.ts",
                "body": "export const compute = (x: number) => x + 1; const main = () => compute(2);",
            }
        ]
    )
    assert [f["name"] for f in rows[0]["functions"]] == ["compute", "main"]
    assert rows[0]["function_calls"][0]["name"] == "compute"


def test_github_rename_metadata_survives_without_a_patch():
    import base64

    import httpx

    github = GitHub("fixture/repository")
    github.client.close()

    def respond(request):
        path = request.url.path.removeprefix("/repos/fixture/repository").lstrip("/")
        routes = {
            "": {"id": 101, "default_branch": "main", "private": False},
            "commits/main": {"sha": "a" * 40},
            "pulls/1": {
                "title": "Rename module",
                "body": "Rename module only",
                "html_url": "https://github.com/fixture/repository/pull/1",
                "created_at": "2024-01-01T00:00:00Z",
                "merged_at": None,
                "merge_commit_sha": None,
                "state": "closed",
                "user": {"login": "fixture"},
            },
            "pulls/1/files": [
                {
                    "filename": "new.py",
                    "previous_filename": "old.py",
                    "status": "renamed",
                    "blob_url": "https://github.com/fixture/repository/blob/main/new.py",
                }
            ],
            "git/trees/" + "a" * 40: {
                "tree": [
                    {"path": "new.py", "type": "blob", "sha": "b" * 40, "size": 30}
                ]
            },
            "git/blobs/" + "b" * 40: {
                "content": base64.b64encode(b"def hello():\n    return 1\n").decode()
            },
        }
        return httpx.Response(200, json=routes.get(path, []))

    github.client = httpx.Client(
        base_url="https://api.github.com", transport=httpx.MockTransport(respond)
    )
    try:
        corpus = github.collect({"pull_requests": [1]})
        diff = next(s for s in corpus["documents"] if s["kind"] == "diff")
        assert diff["previous_path"] == "old.py"
        assert '"previous_filename": "old.py"' in diff["body"]
        assert diff["path"] == "new.py"
    finally:
        github.close()
