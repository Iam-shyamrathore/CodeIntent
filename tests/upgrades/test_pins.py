"""Pins: which clauses count, whether they block the latest release, and where they came from.

The origin test reads real git history at a fixed commit (CODEINTENT_RUN_NETWORK=1): the MCP fetch
server pinned ``httpx<0.28`` after httpx 0.28 removed ``proxies=``.
"""

import os

import httpx
import pytest

from codeintent.upgrades import pins
from codeintent.upgrades.models import Pin

FETCH = """[project]
name = "mcp-server-fetch"
dependencies = [
    "httpx<0.28",
    "markdownify>=0.13.1",
    "mcp>=1.1.3",
]
"""


def test_lock_style_exact_pins_are_not_deliberate_outside_project_files():
    exact, upper = (
        Pin(kind="exact", clause="==2.31.0"),
        Pin(kind="upper_bound", clause="<0.28"),
    )
    assert pins.deliberate((exact,), "requirements") == ()
    assert pins.deliberate((exact, upper), "requirements") == (upper,)
    assert pins.deliberate((exact,), "pyproject") == (exact,)


@pytest.mark.parametrize(
    "specifier,version,expected",
    [
        ("<0.28", "0.28.1", False),
        ("<0.29", "0.28.1", True),
        ("!=2.0.0", "2.0.0", False),
        ("^1.2", "1.3", None),
    ],
)
def test_allows_reads_pep_440_and_admits_what_it_cannot(specifier, version, expected):
    assert pins.allows(specifier, version) is expected


def test_lift_follows_the_verdict_on_the_blocked_upgrade():
    assert pins.lift(True, "no-known-impact")[0] == "can-be-lifted"
    assert pins.lift(True, "breaks")[0] == "keep"
    assert pins.lift(True, "needs-change")[0] == "keep"
    assert pins.lift(True, "not-checked")[0] == "unknown"
    assert pins.lift(True, None)[0] == "unknown"
    assert pins.lift(False, "breaks")[0] is None
    assert pins.lift(None, "no-known-impact")[0] == "unknown"


def test_line_with_matches_name_and_clause_but_not_lookalikes():
    assert pins.line_with(FETCH, "httpx", "<0.28") == 4
    assert pins.line_with(FETCH, "httpx", "< 0.28") == 4
    assert pins.line_with(FETCH, "httpx", "<0.27") is None
    assert pins.line_with('"httpx-sse<0.5",\n', "httpx", "<0.5") is None
    assert pins.line_with('"Flask_Login<1",\n', "flask-login", "<1") == 1


@pytest.mark.skipif(os.getenv("CODEINTENT_RUN_NETWORK") != "1", reason="reads GitHub")
def test_origin_walks_back_to_the_commit_that_added_the_clause():
    from codeintent.upgrades.repository import token
    from codeintent.upgrades.upstream import GitHubCache, Repo

    sha = "71e6293bae0b7a1208b11822183828715efe3e91"
    with httpx.Client(timeout=60, follow_redirects=True) as http:
        repo = Repo(GitHubCache(http, token()), "kevin-biot/MCP-LMstudio")
        found, detail = pins.origin(
            repo, sha, "src/fetch/pyproject.toml", 19, "httpx", "<0.28"
        )
    assert detail is None
    assert found.commit == "9a4d513724b4fbe638ca24f6f86e6fc3ca373e89"
    assert found.message.startswith(
        "fix(fetch): specify httpx<0.28 to resolve proxy problem"
    )
    assert "unexpected keyword argument 'proxies'" in found.message
