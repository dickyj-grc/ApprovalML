"""
Real end-to-end test of the stdio relay: spawns `approvalml -- python
_stub_mcp_server.py` as an actual subprocess chain and talks MCP to it from
this test via a real stdio client — not mocked. Confirms the transport
wiring (spawn, classify, list_tools, forward) genuinely works.
"""

import os
import sys

import pytest

CLI_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cli.py")
STUB_PATH = os.path.join(os.path.dirname(__file__), "_stub_mcp_server.py")

pytest.importorskip("mcp", reason="mcp SDK not installed — skipping real stdio subprocess test")


async def _connect():
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[CLI_PATH, "--", sys.executable, STUB_PATH],
        env=os.environ.copy(),
    )
    return stdio_client(params)


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Stdio relay]]
@pytest.mark.asyncio
async def test_list_tools_classifies_and_names_correctly():
    """A real subprocess chain: auto tools stay unprefixed, sensitive tools get guarded__ + the instance-id param."""
    from mcp import ClientSession

    async with await _connect() as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            names = {t.name: t for t in tools}

    assert "get_status" in names
    assert "guarded__delete_file" in names
    assert "delete_file" not in names  # sensitive tool must never appear unguarded

    guarded = names["guarded__delete_file"]
    assert "approval" in guarded.description.lower()
    assert "_approval_instance_id" in guarded.inputSchema["properties"]


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Stdio relay]]
@pytest.mark.asyncio
async def test_auto_tool_forwards_directly_through_real_subprocess_chain():
    """An auto-classified tool call is genuinely forwarded to the spawned upstream subprocess."""
    from mcp import ClientSession

    async with await _connect() as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("get_status", {"name": "world"})
            text = result.content[0].text

    assert text == "status-ok:world"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Stdio relay]]
@pytest.mark.asyncio
async def test_gated_tool_is_never_silently_forwarded():
    """Calling the guarded tool must never return the stub's real 'deleted:' result directly."""
    from mcp import ClientSession

    async with await _connect() as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("guarded__delete_file", {"path": "/etc/passwd"})
            text = result.content[0].text

    assert "deleted:/etc/passwd" not in text
