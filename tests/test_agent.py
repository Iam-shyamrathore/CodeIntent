"""The agent harness, its tools and the checks on agents' answers.

A scripted fake replaces Gemini, so the loop is tested without a model. Re-checking a patch with the real
engine downloads two httpx releases (CODEINTENT_RUN_NETWORK=1, as in CI).
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest
from google.genai import types
from pydantic import BaseModel

from codeintent.agent import harness, news, review
from codeintent.agent.tools import Session, _public, toolbox

network = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_NETWORK") != "1", reason="downloads PyPI releases"
)

CLIENT = """import httpx


def make_client(proxy):
    return httpx.Client(
        timeout=10,
        proxies=proxy,
    )
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "weather").mkdir()
    (tmp_path / "weather" / "client.py").write_text(CLIENT)
    return tmp_path


# --- The loop --------------------------------------------------------------------------------------


def said(*calls: tuple[str, dict]) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(function_call=types.FunctionCall(name=n, args=a))
                        for n, a in calls
                    ],
                )
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            total_token_count=100
        ),
    )


class Fake:
    """Replays scripted model turns and keeps what each call was sent."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.sent = []
        self.models = self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def generate_content(self, model, contents, config):
        self.sent.append((list(contents), config))
        return self.turns.pop(0)


class Answer(BaseModel):
    line: int
    quote: str


@pytest.fixture
def model(monkeypatch):
    def install(*turns):
        fake = Fake(turns)
        monkeypatch.setattr("codeintent.vertex.client", lambda: fake)
        return fake

    return install


def results(contents) -> list[str]:
    return [
        p.function_response.response["result"]
        for c in contents
        for p in c.parts or []
        if p.function_response
    ]


def test_tools_run_then_a_checked_answer_ends_the_turn(model, repo):
    fake = model(
        said(("read_file", {"path": "weather/client.py", "start": 1, "lines": 8})),
        said(("submit", {"line": 7, "quote": "proxies=nobody"})),
        said(("submit", {"line": 7, "quote": "proxies=proxy,"})),
    )
    text = CLIENT

    def check(a: Answer) -> list[str]:
        return [] if a.quote in text else ["quote not in the file"]

    answer, trace = harness.run(
        "test",
        "Find the proxies line.",
        tools=toolbox(Session(root=repo), "code"),
        answer=Answer,
        role="investigator",
        check=check,
    )
    assert answer == Answer(line=7, quote="proxies=proxy,")
    assert (trace.outcome, trace.turns, trace.tokens) == ("answered", 3, 300)
    assert trace.rejected == ["quote not in the file"]
    assert [c["tool"] for c in trace.calls] == ["read_file", "submit"]
    assert trace.calls[1]["args"]["quote"] == "proxies=nobody"
    seen = results(fake.sent[1][0])
    assert "    7          proxies=proxy," in seen[0]
    assert "Not accepted" in results(fake.sent[2][0])[-1]
    system = fake.sent[0][1].system_instruction
    assert system.startswith("# CodeIntent agent")
    assert "Safety rules" in system


def test_the_last_turn_may_only_submit(model, repo):
    fake = model(
        said(("search_code", {"text": "httpx"})),
        said(("submit", {"line": 1, "quote": "import httpx"})),
    )
    answer, _trace = harness.run(
        "test",
        "x",
        tools=toolbox(Session(root=repo), "code"),
        answer=Answer,
        role="investigator",
        budget=2,
    )
    assert answer is not None
    first, last = (c.tool_config.function_calling_config for _, c in fake.sent)
    assert first.allowed_function_names is None
    assert last.allowed_function_names == ["submit"]


def test_tool_errors_and_unknown_tools_go_back_to_the_model(model, repo):
    fake = model(
        said(("read_file", {"path": "../../etc/passwd"}), ("rm_rf", {})),
        said(("submit", {"line": 1, "quote": "x"})),
    )
    harness.run(
        "test",
        "x",
        tools=toolbox(Session(root=repo), "code"),
        answer=Answer,
        role="investigator",
    )
    errors = results(fake.sent[1][0])
    assert errors[0].startswith("error: read_file failed")
    assert errors[1] == "error: there is no tool named rm_rf"


def test_answer_schemas_keep_fields_named_like_schema_keywords():
    schema = harness._inline(news.Reports.model_json_schema())
    report = schema["properties"]["items"]["items"]
    assert "title" in report["properties"]
    assert "title" in report["required"]
    assert "$ref" not in str(schema)
    assert "title" not in schema


def test_long_results_keep_head_and_tail():
    cut = harness.clip("a" * 5000 + "b" * 5000, 1000)
    assert cut.startswith("a" * 500)
    assert cut.endswith("b" * 500)
    assert "[9000 characters cut]" in cut


# --- Tools -----------------------------------------------------------------------------------------


def test_web_pages_only_open_from_this_sessions_search():
    session = Session()
    read_page = {t.name: t for t in toolbox(session, "web")}["read_page"]
    with pytest.raises(ValueError, match="only opens links returned by web_search"):
        read_page.run(url="https://evil.example/collect?d=secret")


def _resolves_to(monkeypatch, addresses: dict[str, str]):
    def getaddrinfo(host, *args, **kwargs):
        if host not in addresses:
            raise socket.gaierror(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addresses[host], 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def test_private_addresses_are_not_web_pages(monkeypatch):
    _resolves_to(monkeypatch, {"github.com": "140.82.112.3"})
    assert _public("https://github.com/encode/httpx/releases")
    for url in (
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://localhost:8000",
        "file:///etc/passwd",
        "http://10.0.0.5/",
    ):
        assert not _public(url), url


def test_names_that_resolve_to_private_addresses_are_not_web_pages(monkeypatch):
    _resolves_to(
        monkeypatch,
        {
            "metadata.attacker.example": "169.254.169.254",
            "intranet.example": "10.1.2.3",
        },
    )
    assert not _public("http://metadata.attacker.example/latest")
    assert not _public("https://intranet.example/")
    assert not _public("https://does-not-resolve.example/")


# --- Checks on answers -----------------------------------------------------------------------------

PATCH = review.Patch(
    file="weather/client.py",
    line=7,
    before="        proxies=proxy,",
    after="        proxy=proxy,",
    explanation="proxies= was removed in 0.28; proxy= takes one URL.",
)


def test_a_patch_applies_only_where_its_before_text_is(repo):
    assert "        proxy=proxy,\n" in review.apply(CLIENT, PATCH)
    far = PATCH.model_copy(update={"line": 60})
    assert review.apply(CLIENT, far) is None
    check = review.check_patches(repo, {("weather/client.py", 7)})
    assert check(review.Patches(patches=[PATCH])) == []
    invented = PATCH.model_copy(update={"before": "    proxies = proxy"})
    broken = PATCH.model_copy(update={"after": "        proxy=(proxy,"})
    elsewhere = PATCH.model_copy(update={"file": "weather/other.py"})
    problems = check(review.Patches(patches=[invented, broken, elsewhere]))
    assert "is not in the file near that line" in problems[0]
    assert "does not parse" in problems[1]
    assert "not one of the places" in problems[2]


def test_a_patch_copied_with_other_indentation_or_line_numbers_still_applies():
    shifted = PATCH.model_copy(
        update={"before": "proxies=proxy,", "after": "proxy=proxy,"}
    )
    assert "        proxy=proxy,\n" in review.apply(CLIENT, shifted)
    numbered = PATCH.model_copy(update={"before": "    7          proxies=proxy,"})
    assert "        proxy=proxy,\n" in review.apply(CLIENT, numbered)
    block = PATCH.model_copy(
        update={
            "line": 5,
            "before": "return httpx.Client(\n    timeout=10,\n    proxies=proxy,\n)",
            "after": "return httpx.Client(\n    timeout=10,\n    proxy=proxy,\n)",
        }
    )
    assert (
        "    return httpx.Client(\n        timeout=10,\n        proxy=proxy,\n    )\n"
        in review.apply(CLIENT, block)
    )


def test_a_rejected_patch_is_shown_the_real_lines(repo):
    check = review.check_patches(repo, {("weather/client.py", 7)})
    invented = PATCH.model_copy(update={"before": "        proxies = proxy"})
    [problem] = check(review.Patches(patches=[invented]))
    assert "    7          proxies=proxy," in problem


def test_assessments_need_quotes_from_the_file(repo):
    check = review.check_assessments(repo, {("weather/client.py", 5)})
    good = review.Assessment(
        file="weather/client.py",
        line=5,
        assessment="likely-breaks",
        reason="passes proxies=",
        evidence=[
            review.Evidence(file="weather/client.py", line=7, quote="proxies=proxy")
        ],
    )
    bare = good.model_copy(update={"evidence": []})
    made_up = good.model_copy(
        update={
            "evidence": [
                review.Evidence(file="weather/client.py", line=7, quote="verify=False")
            ]
        }
    )
    assert check(review.Assessments(items=[good])) == []
    assert "needs quoted evidence" in check(review.Assessments(items=[bare]))[0]
    assert "not in that file" in check(review.Assessments(items=[made_up]))[0]


def test_behaviour_changes_need_a_quote_from_notes_read_and_a_used_name():
    session = Session(
        seen=["## 0.28.0\nThe deprecated `proxies` argument has now been removed."]
    )
    check = review.check_behaviour(session, {"httpx.Client", "httpx.get"})
    item = review.Change(
        symbol="httpx.Client",
        version="0.28.0",
        what_changed="proxies removed",
        why_it_matters="you pass it",
        quote="The deprecated `proxies` argument has now been removed.",
        severity="likely-breaks",
    )
    assert check(review.Behaviour(items=[item])) == []
    unused = item.model_copy(update={"symbol": "httpx.AsyncClient"})
    invented = item.model_copy(update={"quote": "Client now retries by default."})
    problems = check(review.Behaviour(items=[unused, invented]))
    assert "not a name this repository uses" in problems[0]
    assert "not in the release notes you read" in problems[1]


def test_agent_prose_cannot_carry_links_or_html():
    text = review.plain(
        "See [here](https://evil.example) ![x](https://t.example/p.png) <img src=x> https://a.b/c"
    )
    assert "evil" not in text
    assert "<" not in text
    assert "https://" not in text


BODY = """<!-- codeintent:dependency-report -->
### CodeIntent: Breaks you

table

**Fix it with your AI agent:** ask it.

<sub>footer</sub>"""


def test_the_agent_section_sits_before_the_hint_and_is_replaced_next_time():
    first = review.merged(BODY, f"{review.START}\nold\n{review.END}")
    assert first.index("old") < first.index("**Fix it with your AI agent:**")
    second = review.merged(first, f"{review.START}\nnew\n{review.END}")
    assert "old" not in second
    assert second.count(review.START) == 1
    assert review.merged(second, "").count(review.START) == 0


def test_the_section_says_whether_codeintent_confirmed_a_fix():
    block = review.section(
        {
            "upgrades": [
                {
                    "package": "httpx",
                    "patches": [{**PATCH.model_dump(), "verified": True}],
                }
            ]
        },
        "gemini-2.5-flash",
    )
    assert "#### Agent review (gemini-2.5-flash; not part of the verdict)" in block
    assert (
        "CodeIntent re-analysed the edited code and no longer finds this break" in block
    )
    assert "-         proxies=proxy," in block
    assert "+         proxy=proxy," in block


@network
def test_the_patcher_is_told_the_new_signature_with_its_types(tmp_path, monkeypatch):
    import httpx

    monkeypatch.setenv("CODEINTENT_ARTIFACT_CACHE", str(tmp_path / "cache"))
    with httpx.Client(timeout=60, follow_redirects=True) as http:
        text = review.describe("httpx", "0.28.1", ["httpx._client.Client"], http)
    assert "proxy: ProxyTypes | None = None" in text
    assert "mounts:" in text
    assert "proxies" not in text
    assert "httpx._types.ProxyTypes = " in text


def test_the_stored_edit_has_the_files_own_indentation(repo):
    sloppy = PATCH.model_copy(
        update={"before": "proxies=proxy,", "after": "proxy=proxy,"}
    )
    assert review._as_applied(repo, sloppy) == {
        "before": "        proxies=proxy,",
        "after": "        proxy=proxy,",
    }


@network
def test_codeintent_confirms_a_patch_by_analysing_the_patched_copy(
    repo, tmp_path, monkeypatch
):
    monkeypatch.setenv("CODEINTENT_ARTIFACT_CACHE", str(tmp_path / "cache"))
    wrong = PATCH.model_copy(update={"after": "        proxies=proxy,  # unchanged"})
    assert review.recheck("httpx", "0.27.2", "0.28.1", repo, [PATCH]) == [True]
    assert review.recheck("httpx", "0.27.2", "0.28.1", repo, [wrong]) == [False]
    # An edit that could not be applied (its line was already changed) is never counted as confirmed.
    assert review.recheck("httpx", "0.27.2", "0.28.1", repo, [PATCH, PATCH]) == [
        True,
        False,
    ]


# --- Security news ---------------------------------------------------------------------------------


def test_news_reports_need_a_page_that_was_read_and_a_real_id():
    session = Session(read_urls={"https://github.com/advisories/GHSA-abcd"})
    check = news.check(session, {"urllib3"})
    good = news.Report(
        package="urllib3",
        title="Decompression bomb",
        summary="Unbounded decompression in urllib3.",
        ids=["CVE-2025-66418"],
        affected=">=1.24,<2.6.0",
        url="https://github.com/advisories/GHSA-abcd",
    )
    assert check(news.Reports(items=[good])) == []
    bad = good.model_copy(
        update={
            "package": "requests",
            "url": "https://x.example",
            "ids": ["CVE-1"],
            "affected": "old ones",
        }
    )
    problems = " | ".join(check(news.Reports(items=[bad])))
    for expected in (
        "not one of the packages",
        "was not read",
        "is not a CVE",
        "not a PEP 440",
    ):
        assert expected in problems


def test_codeintent_decides_whether_the_locked_version_is_affected():
    assert news.affects(">=1.24,<2.6.0", {"2.5.0"}) == "yes"
    assert news.affects(">=1.24,<2.6.0", {"2.6.3"}) == "no"
    assert news.affects("", {"2.5.0"}) == "maybe"
    assert news.key({"ids": ["ghsa-x", "CVE-2025-1"], "url": "u"}) == "CVE-2025-1"
