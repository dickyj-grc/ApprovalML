"""ApprovalML MCP Server.

Exposes human approval gates as MCP tools so AI agents can request approval
and check results without requiring the agent to know about the underlying
REST API.

Native tools:
  request_approval        — create a single-step approval gate
  check_approval_status   — poll the result of a pending approval
  list_pending_approvals  — list approvals not yet decided

Wrapped server tools (optional, configured via YAML):
  guarded__<server>__<tool> — any tool from a wrapped MCP server that requires
                               human approval before forwarding to upstream

Environment variables:
  APPROVALML_API_URL         base URL of ApprovalML backend (default: http://localhost:8000)
  APPROVALML_API_TOKEN       bearer token
  APPROVALML_CONFIG          path to wrapped-servers config YAML (default: approvalml-config.yaml)

Usage (stdio, for Claude Desktop):
  approvalml mcp-server

Usage (HTTP, for remote access):
  approvalml mcp-server --http --port 3100
"""

from __future__ import annotations

import json
import os
from typing import Any

from .mcp_client import ApprovalMLClient
from .mcp_proxy import WrappedServerRegistry

try:
    import mcp.server.stdio
    import mcp.types as types
    from mcp.server import Server
    from mcp.server.models import InitializationOptions
    import mcp.server.stdio as stdio_server
except ImportError as e:
    raise ImportError(
        "MCP server dependencies not installed. "
        "Run: pip install 'approvalml[mcp]'"
    ) from e


def _build_server(
    client: ApprovalMLClient,
    proxy: WrappedServerRegistry,
) -> Server:
    server = Server("approvalml")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        native = [
            types.Tool(
                name="request_approval",
                description=(
                    "Request human approval for an action. The approver receives an email "
                    "with an approve/reject link — no login required. Returns an instance_id "
                    "you can poll with check_approval_status."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "What action needs approval. Be specific.",
                        },
                        "approver_email": {
                            "type": "string",
                            "format": "email",
                            "description": "Email address of the person who should approve.",
                        },
                        "context": {
                            "type": "object",
                            "description": "Optional key/value pairs shown to the approver for context.",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["description", "approver_email"],
                },
            ),
            types.Tool(
                name="check_approval_status",
                description=(
                    "Check the current status of an approval request. "
                    "Returns status (pending/approved/rejected), who decided, their comment, and when."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "instance_id": {
                            "type": "string",
                            "description": "The instance_id returned by request_approval.",
                        },
                    },
                    "required": ["instance_id"],
                },
            ),
            types.Tool(
                name="list_pending_approvals",
                description="List all approval requests that have not yet been decided.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

        proxied_raw = proxy.list_all_tools()
        proxied = [
            types.Tool(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {"type": "object", "properties": {}}),
            )
            for t in proxied_raw
        ]

        return native + proxied

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        try:
            result = _dispatch(name, arguments, client, proxy)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as exc:
            return [types.TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    return server


def _dispatch(
    name: str,
    arguments: dict[str, Any],
    client: ApprovalMLClient,
    proxy: WrappedServerRegistry,
) -> Any:
    if name == "request_approval":
        return client.request_approval(
            description=arguments["description"],
            approver_email=arguments["approver_email"],
            context=arguments.get("context"),
        )

    if name == "check_approval_status":
        return client.check_approval_status(arguments["instance_id"])

    if name == "list_pending_approvals":
        return client.list_pending_approvals()

    # Proxied tool — requires approval gate before forwarding
    resolved = proxy.resolve(name)
    if resolved is not None:
        server_obj, tool_name = resolved
        # Request approval, then return pending status.
        # The agent must call check_approval_status and, once approved,
        # call the tool again to get the forwarded result.
        gate = client.request_approval(
            description=f"AI agent wants to call `{tool_name}` on `{server_obj.name}`",
            approver_email=os.environ.get("APPROVALML_DEFAULT_APPROVER", ""),
            context={"tool": tool_name, "server": server_obj.name, "arguments": arguments},
        )
        # If already approved (e.g. re-call after approval), forward immediately
        if gate.get("status") == "approved":
            return proxy.call_tool(name, arguments)
        return {
            "pending": True,
            "instance_id": gate.get("instance_id"),
            "message": (
                f"Approval requested. Poll check_approval_status(instance_id='{gate.get('instance_id')}') "
                "until status is 'approved', then call this tool again."
            ),
        }

    raise ValueError(f"Unknown tool: {name}")


async def run_stdio(client: ApprovalMLClient, proxy: WrappedServerRegistry) -> None:
    server = _build_server(client, proxy)
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="approvalml",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities={},
                ),
            ),
        )


def start(
    api_url: str | None = None,
    api_token: str | None = None,
    config_path: str | None = None,
    http: bool = False,
    port: int = 3100,
) -> None:
    """Entry point called by the CLI."""
    import asyncio

    client = ApprovalMLClient(api_url=api_url, api_token=api_token)
    resolved_config = config_path or os.environ.get("APPROVALML_CONFIG", "approvalml-config.yaml")
    proxy = WrappedServerRegistry.from_yaml(resolved_config)

    if http:
        raise NotImplementedError(
            "HTTP transport not yet implemented. Use stdio mode (default) for Claude Desktop."
        )

    asyncio.run(run_stdio(client, proxy))
