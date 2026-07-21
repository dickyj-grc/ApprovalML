"""
Per-server MCP wrapper: spawns a single upstream MCP server as a stdio
subprocess and re-exposes a gated version of its tools over its own stdio.

Usage (as a Claude Desktop / MCP client entry, no subcommand):
  approvalml -- <upstream-command> <upstream-args...>

Every tool from the upstream server is classified as one of:
  auto     - forwarded directly, no approval step
  gate     - a single-step approval gate (request_approval)
  workflow - a full named YAML workflow (submit_workflow)
  deny     - never exposed

Classification source, in priority order:
  1. APPROVALML_CONFIG YAML if set — either shape:
     a. guards.tools: a glob->action map, doubling as the escalation workflow
        (tools not matched fall through to this same file's own workflow:,
        submitted under this file's own name:)
     b. flat rules:/default_action list, escalating to a separately named workflow
  2. Built-in zero-config heuristic (annotations + tool-name prefixes)

Environment variables:
  APPROVALML_APPROVER  - default approver_email for 'gate' classified tools
  APPROVALML_NOTIFY    - "<channel>:<target>" notification delivery, e.g.
                         "slack:https://hooks.slack.com/services/XXX"
  APPROVALML_CONFIG    - path to a flat classification YAML (optional)
  APPROVALML_API_URL / APPROVALML_API_TOKEN - ApprovalML backend (standalone
                         runtime or Aptiwise SaaS — same REST contract)

Since exactly one upstream server exists per process, there is no
possibility of a tool-name collision, so tool names are not server-scoped:
'auto' tools keep their real name; 'gate'/'workflow' tools are exposed as
'guarded__<tool>'.
"""

from __future__ import annotations

import fnmatch
import json
import os
from typing import Any, Optional

import httpx
import yaml

from .mcp_client import ApprovalMLClient

GUARD_PREFIX = "guarded__"
INSTANCE_ID_PARAM = "_approval_instance_id"

_SAFE_PREFIXES = ("get_", "list_", "search_", "read_", "describe_")
_SENSITIVE_PREFIXES = ("create_", "update_", "delete_", "merge_", "write_", "send_", "execute_")

_VALID_ACTIONS = {"auto", "gate", "workflow", "deny"}


# ── Zero-config classification ──────────────────────────────────────────────

def _annotation_signal(annotations: Optional[dict]) -> Optional[bool]:
    """True/False if the tool's annotations indicate safe/unsafe, None if absent."""
    if not annotations:
        return None
    read_only = annotations.get("readOnlyHint")
    destructive = annotations.get("destructiveHint")
    if read_only is None and destructive is None:
        return None
    return bool(read_only) and not bool(destructive)


def _name_signal(name: str) -> Optional[bool]:
    """True/False if the tool name's prefix indicates safe/unsafe, None if unclear."""
    if name.startswith(_SAFE_PREFIXES):
        return True
    if name.startswith(_SENSITIVE_PREFIXES):
        return False
    return None


def classify_tool_zero_config(tool: dict[str, Any]) -> str:
    """
    Classify a tool as 'auto' or 'gate' with no YAML config present.

    Two independent signals (MCP tool annotations, tool-name prefix) must
    agree that a tool is safe for it to auto-pass; a missing signal or any
    disagreement defaults to 'gate' ("ambiguity pends").
    """
    name = tool.get("name", "")
    signals = [
        s for s in (_annotation_signal(tool.get("annotations")), _name_signal(name))
        if s is not None
    ]
    if signals and all(signals):
        return "auto"
    return "gate"


# ── Classification config (APPROVALML_CONFIG) ───────────────────────────────

def _normalize_guards_config(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize a guards.tools document into the internal rules:/default_action:
    shape, so classify_tool() only ever has to handle one format.

    Unmatched tools escalate into this same file's own workflow: section
    (submitted under this file's own name:) when one is present, else fall
    back to the file's default_action (or 'gate').
    """
    tools = raw["guards"]["tools"]
    rules = [{"match": pattern, "action": action} for pattern, action in tools.items()]
    if "workflow" in raw:
        return {"rules": rules, "default_action": "workflow", "default_workflow": raw.get("name")}
    return {"rules": rules, "default_action": raw.get("default_action", "gate")}


def load_classification_config(path: str) -> dict[str, Any]:
    """
    Load a classification document — either the guards.tools shape (see
    _normalize_guards_config) or the flat rules:/default_action shape.
    """
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    if "guards" in raw:
        return _normalize_guards_config(raw)
    return raw


def classify_tool(tool: dict[str, Any], config: Optional[dict[str, Any]]) -> tuple[str, Optional[str]]:
    """
    Classify a tool using the flat rules:/default_action config if provided
    (ordered, first-match-wins, fnmatch glob), falling back to the
    zero-config heuristic otherwise.

    Returns (action, workflow_name) — workflow_name is only set when
    action == "workflow".
    """
    name = tool.get("name", "")
    if config:
        for rule in config.get("rules", []):
            if fnmatch.fnmatch(name, rule["match"]):
                return rule["action"], rule.get("workflow")
        return config.get("default_action", "gate"), config.get("default_workflow")
    return classify_tool_zero_config(tool), None


# ── APPROVALML_NOTIFY ────────────────────────────────────────────────────────

def parse_notify_env(value: str) -> tuple[str, str]:
    """Parse '<channel>:<target>' — target may itself contain ':' (e.g. a URL)."""
    channel, sep, target = value.partition(":")
    if not sep:
        raise ValueError(f"APPROVALML_NOTIFY must be '<channel>:<target>', got: {value!r}")
    return channel, target


def _notify_adapter(channel: str):
    from .runtime.chat_adapters import SlackAdapter, TeamsAdapter, LarkAdapter, GoogleChatAdapter
    adapters = {
        "slack": SlackAdapter,
        "teams": TeamsAdapter,
        "lark": LarkAdapter,
        "google_chat": GoogleChatAdapter,
    }
    adapter_cls = adapters.get(channel)
    if adapter_cls is None:
        raise ValueError(
            f"Unsupported APPROVALML_NOTIFY channel: {channel!r} "
            f"(supported: {', '.join(sorted(adapters))})"
        )
    return adapter_cls()


async def send_env_notify(
    notify_value: str,
    subject: str,
    body: str,
    action_url: Optional[str] = None,
) -> None:
    """
    Send a notification per APPROVALML_NOTIFY=<channel>:<target>, delivered
    as a plain incoming-webhook POST (no bot token needed — the target
    already is the webhook URL).
    """
    channel, target = parse_notify_env(notify_value)
    adapter = _notify_adapter(channel)
    payload = adapter.build_notification_payload(subject=subject, body=body, action_url=action_url)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(target, json=payload)
        resp.raise_for_status()


# ── Gate/workflow dispatch ───────────────────────────────────────────────────

async def resolve_gated_call(
    client: ApprovalMLClient,
    action: str,
    workflow_name: Optional[str],
    tool_name: str,
    arguments: dict[str, Any],
    approver_email: str,
) -> dict[str, Any]:
    """
    Create-or-check-and-forward for a gate/workflow classified tool call.

    If arguments contains INSTANCE_ID_PARAM, check that instance's status
    instead of creating a new gate/workflow — first call (no instance id)
    creates one; a re-call with the instance id forwards only once resolved.
    Returns {"_forward": True} when the caller should forward to upstream.
    """
    arguments = dict(arguments)
    instance_id = arguments.pop(INSTANCE_ID_PARAM, None)

    if instance_id is None:
        if action == "workflow":
            result = client.submit_workflow(workflow_name, {"tool_name": tool_name, "arguments": arguments})
        else:
            result = client.request_approval(
                description=f"AI agent wants to call `{tool_name}`",
                approver_email=approver_email,
                context={"tool": tool_name, "arguments": arguments},
            )
        new_id = result.get("instance_id")
        return {
            "pending": True,
            "instance_id": new_id,
            "message": (
                f"Approval requested. Call this tool again with "
                f"{INSTANCE_ID_PARAM}='{new_id}' once approved."
            ),
        }

    if action == "workflow":
        status = client.get_workflow_status(instance_id)
        if status.get("status") == "completed":
            return {"_forward": True}
        return {"pending": True, "instance_id": instance_id, "status": status.get("status")}

    status = client.check_approval_status(instance_id)
    if status.get("status") == "approved":
        return {"_forward": True}
    return {"pending": True, "instance_id": instance_id, "status": status.get("status")}


def with_instance_id_param(schema: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Inject the optional INSTANCE_ID_PARAM property into a tool's inputSchema."""
    schema = dict(schema) if schema else {"type": "object", "properties": {}}
    properties = dict(schema.get("properties") or {})
    properties[INSTANCE_ID_PARAM] = {
        "type": "string",
        "description": (
            "If retrying after a pending response, pass the instance_id here "
            "instead of calling check_approval_status separately."
        ),
    }
    schema["properties"] = properties
    return schema


# ── Stdio relay ──────────────────────────────────────────────────────────────

async def run_wrapped_stdio(upstream_command: str, upstream_args: list[str]) -> None:
    """Spawn upstream_command as a stdio MCP server and re-expose a gated version of it."""
    try:
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp import ClientSession
        import mcp.server.stdio
        import mcp.types as types
        from mcp.server import NotificationOptions, Server
        from mcp.server.models import InitializationOptions
    except ImportError as e:
        raise ImportError(
            "MCP wrap dependencies not installed. Run: pip install 'approvalml[mcp]'"
        ) from e

    config_path = os.environ.get("APPROVALML_CONFIG")
    config = (
        load_classification_config(config_path)
        if config_path and os.path.exists(config_path)
        else None
    )
    approver_email = os.environ.get("APPROVALML_APPROVER", "")
    notify_value = os.environ.get("APPROVALML_NOTIFY")
    client = ApprovalMLClient()

    params = StdioServerParameters(command=upstream_command, args=upstream_args, env=os.environ.copy())

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as upstream:
            await upstream.initialize()
            server = Server("approvalml-wrap")

            # entity_type -> (action, workflow_name), populated by list_tools()
            classifications: dict[str, tuple[str, Optional[str]]] = {}

            @server.list_tools()
            async def list_tools() -> list[types.Tool]:
                upstream_tools = (await upstream.list_tools()).tools
                exposed: list[types.Tool] = []
                for t in upstream_tools:
                    tool_dict = t.model_dump()
                    action, workflow_name = classify_tool(tool_dict, config)
                    classifications[t.name] = (action, workflow_name)
                    if action == "deny":
                        continue
                    if action == "auto":
                        exposed.append(t)
                        continue
                    exposed.append(
                        types.Tool(
                            name=f"{GUARD_PREFIX}{t.name}",
                            description=(
                                f"⚠️ Requires human approval before execution. "
                                f"{t.description or ''}"
                            ),
                            inputSchema=with_instance_id_param(t.inputSchema),
                        )
                    )
                return exposed

            @server.call_tool()
            async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
                try:
                    return await _dispatch(name, arguments)
                except Exception as exc:
                    return [types.TextContent(type="text", text=json.dumps({"error": str(exc)}))]

            async def _dispatch(name: str, arguments: dict[str, Any]) -> list[Any]:
                if name.startswith(GUARD_PREFIX):
                    original_name = name[len(GUARD_PREFIX):]
                    action, workflow_name = classifications.get(original_name, ("gate", None))
                    resolved = await resolve_gated_call(
                        client, action, workflow_name, original_name, arguments, approver_email
                    )
                    if resolved.get("_forward"):
                        forward_args = {k: v for k, v in arguments.items() if k != INSTANCE_ID_PARAM}
                        result = await upstream.call_tool(original_name, forward_args)
                        return list(result.content)
                    if resolved.get("pending") and notify_value and not arguments.get(INSTANCE_ID_PARAM):
                        await send_env_notify(
                            notify_value,
                            subject=f"Approval needed: {original_name}",
                            body=f"Arguments: {json.dumps({k: v for k, v in arguments.items() if k != INSTANCE_ID_PARAM})}",
                        )
                    return [types.TextContent(type="text", text=json.dumps(resolved, indent=2))]
                result = await upstream.call_tool(name, arguments)
                return list(result.content)

            async with mcp.server.stdio.stdio_server() as (in_r, in_w):
                await server.run(
                    in_r,
                    in_w,
                    InitializationOptions(
                        server_name="approvalml-wrap",
                        server_version="0.1.0",
                        capabilities=server.get_capabilities(
                            notification_options=NotificationOptions(),
                            experimental_capabilities={},
                        ),
                    ),
                )
