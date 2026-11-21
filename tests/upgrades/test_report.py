from __future__ import annotations

from codeintent.upgrades import report
from codeintent.upgrades.verdict import UpgradeVerdict

BREAKS = UpgradeVerdict.model_validate(
    {
        "package": "httpx",
        "start": "0.27.2",
        "end": "0.28.1",
        "verdict": "breaks",
        "label": "Breaks you",
        "reason": "1 change(s) in httpx 0.28.1 break code you use, at 1 place(s)",
        "findings": [
            {
                "severity": "breaks",
                "change": {
                    "kind": "parameter-removed",
                    "symbol": "httpx._client.Client",
                    "parameter": "proxies",
                    "detail": "gone",
                    "replacement": "proxy= or mounts=",
                },
                "locations": [{"file": "src/app/client.py", "line": 5}],
            }
        ],
    }
)
HARMLESS = UpgradeVerdict(
    package="h11",
    start="0.14.0",
    end="0.16.0",
    verdict="no-known-impact",
    label="No known impact",
    reason="your code does not use h11 directly",
)
TRACED = {
    "httpx": {
        "reach": {
            "uses": 3,
            "files": ["src/app/client.py", "src/app/api.py"],
            "through": [],
        },
        "blast": [
            {
                "file": "src/app/client.py",
                "line": 5,
                "function": "make",
                "callers": [
                    {"function": "users", "file": "src/app/api.py", "depth": 1},
                    {
                        "function": "Session.__init__",
                        "file": "src/app/client.py",
                        "depth": 1,
                    },
                ],
                "importers": [{"file": "src/app/api.py", "depth": 1}],
                "tests": ["tests/test_client.py"],
                "entry_points": [
                    {
                        "name": "GET /users",
                        "function": "users",
                        "file": "src/app/api.py",
                    }
                ],
            }
        ],
    },
    "h11": {
        "reach": {
            "uses": 0,
            "files": [],
            "through": [
                {
                    "via": "httpx",
                    "chain": ["httpx@0.27.2", "httpcore@1.0.7", "h11@0.14.0"],
                    "uses": 3,
                    "files": ["src/app/client.py"],
                }
            ],
        },
        "blast": [],
    },
}


def body() -> str:
    return report.comment(
        [BREAKS, HARMLESS], [], None, graph=TRACED, pull="acme/app#12"
    )


def test_says_where_the_package_reaches_the_code():
    assert (
        "**Where `httpx` reaches your code:** 3 use(s) in 2 file(s): "
        "`src/app/client.py`, `src/app/api.py`." in body()
    )


def test_follows_a_broken_line_to_its_callers_routes_and_tests():
    assert (
        "- `src/app/client.py:5` in `make()`, called by `users()`, `Session.__init__()`, "
        "reached from `GET /users`, 1 file(s) import it, tests: `tests/test_client.py`."
        in body()
    )


def test_names_the_chain_for_a_package_the_code_never_imports():
    assert (
        "**Reaches you through:** `httpx` → `httpcore` → `h11` (3 use(s) of `httpx` in your code)."
        in body()
    )


def test_points_the_team_at_their_agent_only_when_there_is_something_to_fix():
    assert "_fix the CodeIntent findings on acme/app#12_" in body()
    assert "fix_brief" not in report.comment([HARMLESS], [], None, pull="acme/app#12")


def test_without_the_graph_the_comment_is_unchanged():
    plain = report.comment([BREAKS], [], None)
    assert "reaches your code" not in plain and "What else this breaks" not in plain
