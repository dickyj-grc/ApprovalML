"""Wrapped-server proxy for ApprovalML gated MCP.

Loads a config file that describes upstream MCP servers whose tools should be
gated behind human approval before execution.

Config file format (YAML):
  wrapped_servers:
    - name: filesystem
      url: http://localhost:3001
      auth:                         # optional
        type: bearer
        token: "..."
      gate: [write_file, delete_file]   # omit to gate ALL tools from this server

Usage:
  from approvalml.mcp_proxy import WrappedServerRegistry
  registry = WrappedServerRegistry.from_yaml("approvalml-config.yaml")
  tools = await registry.list_all_tools()
  result = await registry.call_tool("filesystem", "write_file", {"path": "...", "content": "..."})
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx
import yaml


class WrappedServer:
    def __init__(
        self,
        name: str,
        url: str,
        gate: Optional[list[str]] = None,
        auth: Optional[dict[str, str]] = None,
    ):
        self.name = name
        self.url = url.rstrip("/")
        # None means gate all tools; empty list means gate nothing
        self.gate = gate
        self.auth = auth or {}

    def is_gated(self, tool_name: str) -> bool:
        if self.gate is None:
            return True
        return tool_name in self.gate

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.auth.get("type") == "bearer":
            headers["Authorization"] = f"Bearer {self.auth['token']}"
        return headers

    def list_tools(self) -> list[dict[str, Any]]:
        """Fetch tools from upstream MCP server via tools/list."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(self.url, json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", {}).get("tools", [])

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Forward a tool call to the upstream MCP server."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(self.url, json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"Upstream MCP error: {data['error']}")
            return data.get("result")


class WrappedServerRegistry:
    PREFIX = "guarded__"

    def __init__(self, servers: list[WrappedServer]):
        self._servers: dict[str, WrappedServer] = {s.name: s for s in servers}

    @classmethod
    def from_yaml(cls, config_path: str) -> "WrappedServerRegistry":
        if not os.path.exists(config_path):
            return cls([])
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
        servers = []
        for entry in config.get("wrapped_servers", []):
            servers.append(
                WrappedServer(
                    name=entry["name"],
                    url=entry["url"],
                    gate=entry.get("gate"),
                    auth=entry.get("auth"),
                )
            )
        return cls(servers)

    def list_all_tools(self) -> list[dict[str, Any]]:
        """Return all gated tools from all wrapped servers, prefixed with guarded__."""
        tools = []
        for server in self._servers.values():
            try:
                for tool in server.list_tools():
                    if server.is_gated(tool["name"]):
                        gated = dict(tool)
                        original_name = tool["name"]
                        gated["name"] = f"{self.PREFIX}{server.name}__{original_name}"
                        gated["description"] = (
                            f"⚠️ Requires human approval before execution. "
                            f"Original tool: {original_name} on {server.name}. "
                            + (tool.get("description") or "")
                        )
                        gated["_server"] = server.name
                        gated["_original"] = original_name
                        tools.append(gated)
            except Exception:
                pass  # upstream unavailable — skip silently
        return tools

    def resolve(self, prefixed_name: str) -> Optional[tuple[WrappedServer, str]]:
        """Parse guarded__<server>__<tool> → (WrappedServer, original_tool_name)."""
        if not prefixed_name.startswith(self.PREFIX):
            return None
        rest = prefixed_name[len(self.PREFIX):]
        parts = rest.split("__", 1)
        if len(parts) != 2:
            return None
        server_name, tool_name = parts
        server = self._servers.get(server_name)
        if server is None:
            return None
        return server, tool_name

    def call_tool(self, prefixed_name: str, arguments: dict[str, Any]) -> Any:
        """Forward an approved tool call to the upstream server."""
        resolved = self.resolve(prefixed_name)
        if resolved is None:
            raise ValueError(f"Unknown proxied tool: {prefixed_name}")
        server, tool_name = resolved
        return server.call_tool(tool_name, arguments)
