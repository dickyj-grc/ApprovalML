"""
Tiny stdio MCP server used as a real subprocess by test_mcp_wrap_stdio.py.

Exposes:
  get_status(name)    - a safe, read-only-looking tool, auto-classified
  delete_file(path)   - a sensitive-looking tool, gate-classified

Run directly: python _stub_mcp_server.py
"""

import asyncio

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions


def build_server() -> Server:
    server = Server("stub")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="get_status",
                description="Return a fixed status string.",
                inputSchema={"type": "object", "properties": {"name": {"type": "string"}}},
                annotations={"readOnlyHint": True},
            ),
            types.Tool(
                name="delete_file",
                description="Pretend to delete a file.",
                inputSchema={"type": "object", "properties": {"path": {"type": "string"}}},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name == "get_status":
            return [types.TextContent(type="text", text=f"status-ok:{arguments.get('name', '')}")]
        if name == "delete_file":
            return [types.TextContent(type="text", text=f"deleted:{arguments.get('path', '')}")]
        raise ValueError(f"Unknown tool: {name}")

    return server


async def main() -> None:
    server = build_server()
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(
            read,
            write,
            InitializationOptions(
                server_name="stub",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
