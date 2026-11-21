"""The MCP server through the SDK's own client and the real ASGI app; network cases are opt-in.

CODEINTENT_RUN_NETWORK=1 uv run pytest tests/test_mcp_server.py  # also downloads real repositories
"""

import os

import pytest
from mcp import Client
from starlette.testclient import TestClient

from codeintent import mcp_server

network = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_NETWORK") != "1",
    reason="downloads GitHub repositories and PyPI releases",
)
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.mark.asyncio
async def test_tools_are_read_only_with_structured_output():
    async with Client(mcp_server.server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {
        "upgrade_brief",
        "why_pinned",
        "list_dependencies",
        "advisories",
    }
    for tool in tools.values():
        assert tool.annotations.read_only_hint is True
        assert tool.output_schema and tool.description
    assert tools["upgrade_brief"].input_schema["required"] == [
        "repo",
        "package",
        "to_version",
    ]


@pytest.mark.asyncio
async def test_bad_arguments_are_tool_errors_not_crashes():
    async with Client(mcp_server.server) as client:
        bad_repo = await client.call_tool(
            "why_pinned", {"repo": "not a repo", "package": "httpx"}
        )
        bad_package = await client.call_tool(
            "why_pinned", {"repo": "pallets/flask", "package": "-bad-"}
        )
    assert bad_repo.is_error and "owner/name" in bad_repo.content[0].text
    assert bad_package.is_error and "PyPI project name" in bad_package.content[0].text


def test_bearer_token_is_required(monkeypatch):
    monkeypatch.setenv("CODEINTENT_MCP_TOKEN", "t" * 40)
    with TestClient(mcp_server.create_app()) as http:
        assert http.get("/healthz").status_code == 200
        assert http.post("/mcp", json=INITIALIZE, headers=HEADERS).status_code == 401
        wrong = {**HEADERS, "Authorization": "Bearer " + "x" * 40}
        assert http.post("/mcp", json=INITIALIZE, headers=wrong).status_code == 401
        right = {**HEADERS, "Authorization": "Bearer " + "t" * 40}
        response = http.post("/mcp", json=INITIALIZE, headers=right)
        assert response.status_code == 200
        assert "codeintent" in response.text


def test_production_refuses_to_start_without_token(monkeypatch):
    monkeypatch.delenv("CODEINTENT_MCP_TOKEN", raising=False)
    monkeypatch.setenv("CODEINTENT_ENV", "production")
    with pytest.raises(RuntimeError, match="CODEINTENT_MCP_TOKEN"):
        mcp_server.create_app()


@network
@pytest.mark.asyncio
async def test_upgrade_brief_on_openai_python():
    async with Client(mcp_server.server) as client:
        result = await client.call_tool(
            "upgrade_brief",
            {
                "repo": "openai/openai-python@v1.54.4",
                "package": "httpx",
                "from_version": "0.27.2",
                "to_version": "0.28.0",
            },
        )
    brief = result.structured_content
    assert brief["verdict"] == "breaks"
    places = {p for f in brief["findings"] for p in f["locations"]}
    assert places == {
        "src/openai/_base_client.py:857",
        "src/openai/_base_client.py:1438",
        "src/openai/cli/_cli.py:179",
    }
    assert {f["change"]["replacement"] for f in brief["findings"]} == {
        "proxy= or mounts="
    }
    assert brief["steps"][0].startswith("In src/openai/_base_client.py:1438, replace")


@network
@pytest.mark.asyncio
async def test_why_pinned_on_flask():
    async with Client(mcp_server.server) as client:
        result = await client.call_tool(
            "why_pinned", {"repo": "pallets/flask@1.1.4", "package": "itsdangerous"}
        )
    (declaration,) = result.structured_content["declarations"]
    assert (declaration["file"], declaration["line"]) == ("setup.py", 58)
    assert declaration["pins"] == [{"kind": "upper_bound", "clause": "<2.0"}]
    origin = declaration["introduced_by"]
    assert origin["commit"] == "6d8b4ce9d037937ef8694067ab5754666240d097"
    assert (origin["pr_number"], origin["pr_title"]) == (
        4047,
        "set maximum versions for 1.1.x to avoid new major versions",
    )
