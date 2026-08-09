"""ApprovalML MCP Server.

Exposes human approval gates as MCP tools so AI agents can request approval
and check results without requiring the agent to know about the underlying
REST API.

Native tools:
  request_approval        — create a single-step approval gate
  check_approval_status   — poll the result of a pending approval
  list_pending_approvals  — list approvals not yet decided

Scheduling management-plane tools (configure and observe, never tick):
  list_workflows           — registered workflows + their trigger summary
  get_schedule_status      — per-trigger enabled/next_run/last_status
  register_workflow        — register/replace a workflow YAML by name
  set_schedule_enabled     — governed enable/disable of one cron trigger
  run_now                  — explicit, recorded manual submission

There is deliberately no "fire this trigger" tool. Cron triggers are ticked
by the runtime's own WorkflowScheduler (see runtime/scheduler.py) — an agent
can arm or observe a schedule, but the clock stays inside the runtime
process, not in the agent's own loop.

Workflow-directory tools (optional, via --workflows-dir/APPROVALML_WORKFLOWS_DIR):
  submit_<name> — one tool per *.yaml/*.yml file in the directory, with an
                  inputSchema generated from that workflow's form fields.
                  Each file is auto-registered with the runtime at startup.

Environment variables:
  APPROVALML_API_URL         base URL of ApprovalML backend (default: http://localhost:8765)
  APPROVALML_API_TOKEN       bearer token
  APPROVALML_WORKFLOWS_DIR   directory of *.yaml/*.yml files to expose as submit_<name> tools

Usage (stdio, for Claude Desktop):
  approvalml mcp-server

Usage (HTTP, for remote access):
  approvalml mcp-server --http --port 3100
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from .mcp_client import ApprovalMLClient

logger = logging.getLogger(__name__)


def _build_server(client: ApprovalMLClient, workflow_tools: dict[str, dict[str, Any]]):
    try:
        import mcp.types as types
        from mcp.server import Server
    except ImportError as e:
        raise ImportError(
            "MCP server dependencies not installed. "
            "Run: pip install 'approvalml[mcp]'"
        ) from e
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
            types.Tool(
                name="register_workflow",
                description=(
                    "Register or replace a named workflow YAML definition on the runtime. "
                    "New workflows are registered with all cron/one_time triggers disabled — "
                    "use set_schedule_enabled to arm one."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Workflow name to register under."},
                        "yaml": {"type": "string", "description": "Full ApprovalML workflow YAML content."},
                    },
                    "required": ["name", "yaml"],
                },
            ),
            types.Tool(
                name="list_workflows",
                description=(
                    "List every workflow registered on the runtime, with a summary of any "
                    "cron/one_time triggers each one declares."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="get_schedule_status",
                description=(
                    "Get the detailed schedule status of one workflow's triggers: enabled/disabled, "
                    "cron expression, next_run, last_run, last_status, and consecutive_failures."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "workflow_name": {"type": "string"},
                    },
                    "required": ["workflow_name"],
                },
            ),
            types.Tool(
                name="set_schedule_enabled",
                description=(
                    "Arm or disarm one cron/one_time trigger on a workflow. This is a governed "
                    "configuration change, not a manual run — it only flips whether the runtime's "
                    "own scheduler will fire this trigger going forward. Always pass a reason; "
                    "the change is written to the runtime's audit log with the calling identity."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "workflow_name": {"type": "string"},
                        "trigger_index": {
                            "type": "integer",
                            "description": "0-based index of the trigger within the workflow's triggers: list.",
                        },
                        "enabled": {"type": "boolean"},
                        "reason": {"type": "string", "description": "Why — recorded in the audit log."},
                    },
                    "required": ["workflow_name", "trigger_index", "enabled"],
                },
            ),
            types.Tool(
                name="run_now",
                description=(
                    "Submit a workflow immediately as an explicit, recorded manual override — "
                    "distinct from a scheduler tick. Use this to test a scheduled workflow or run "
                    "it once outside its normal cadence. Does not affect its cron schedule."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "workflow_name": {"type": "string"},
                        "form_data": {
                            "type": "object",
                            "description": "Optional form values; omitted fields fall back to the workflow's own defaults.",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["workflow_name"],
                },
            ),
        ]

        directory_tools = [
            types.Tool(
                name=tool_name,
                description=info["description"],
                inputSchema=info["input_schema"],
            )
            for tool_name, info in workflow_tools.items()
        ]

        return native + directory_tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        try:
            result = _dispatch(name, arguments, client, workflow_tools)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as exc:
            return [types.TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    return server


def _dispatch(
    name: str,
    arguments: dict[str, Any],
    client: ApprovalMLClient,
    workflow_tools: dict[str, dict[str, Any]],
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

    if name == "register_workflow":
        return client.register_workflow(arguments["name"], arguments["yaml"])

    if name == "list_workflows":
        return client.list_workflows()

    if name == "get_schedule_status":
        return client.get_schedule_status(arguments["workflow_name"])

    if name == "set_schedule_enabled":
        return client.set_schedule_enabled(
            arguments["workflow_name"],
            int(arguments["trigger_index"]),
            bool(arguments["enabled"]),
            arguments.get("reason"),
        )

    if name == "run_now":
        return client.run_now(arguments["workflow_name"], arguments.get("form_data"))

    if name in workflow_tools:
        info = workflow_tools[name]
        form_data = dict(arguments)
        missing = [f for f in info["required"] if f not in form_data]
        if missing:
            raise ValueError(f"Missing required field(s): {', '.join(missing)}")
        return client.submit_workflow(info["workflow_name"], form_data)

    raise ValueError(f"Unknown tool: {name}")


# ── Workflow-directory tool generation ──────────────────────────────────────

_EXCLUDED_FIELD_TYPES = {"hidden", "label", "image"}

_TYPE_SCHEMA = {
    "text": {"type": "string"},
    "textarea": {"type": "string"},
    "richtext": {"type": "string"},
    "email": {"type": "string", "format": "email"},
    "number": {"type": "number"},
    "currency": {"type": "number"},
    "date": {"type": "string", "format": "date"},
    "checkbox": {"type": "boolean"},
    "signature": {"type": "string"},
    "autonumber": {"type": "string"},
    "json": {},
}


def _option_values(options: Any) -> Optional[list[str]]:
    """Extract a static enum list from a field's `options`, or None if dynamic/absent."""
    if not isinstance(options, list):
        return None  # OptionsConfig (dynamic data source) — can't enumerate statically
    values = []
    for opt in options:
        if isinstance(opt, str):
            values.append(opt)
        elif isinstance(opt, dict):
            values.append(opt.get("value", opt.get("label", "")))
    return values or None


def _field_to_schema(field: Any) -> dict[str, Any]:
    """Map an ApprovalML FormField to a JSON Schema property."""
    field_type = field.type.value if hasattr(field.type, "value") else str(field.type)

    if field_type in ("select", "dropdown", "radio"):
        schema: dict[str, Any] = {"type": "string"}
        values = _option_values(field.options)
        if values:
            schema["enum"] = values
        return schema

    if field_type == "multiselect":
        item_schema: dict[str, Any] = {"type": "string"}
        values = _option_values(field.options)
        if values:
            item_schema["enum"] = values
        return {"type": "array", "items": item_schema}

    if field_type == "line_items":
        item_props = {
            f.name: _field_to_schema(f)
            for f in (field.item_fields or [])
            if f.name
        }
        return {"type": "array", "items": {"type": "object", "properties": item_props}}

    return dict(_TYPE_SCHEMA.get(field_type, {"type": "string"}))


def _slugify(name: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "_" for c in name)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")[:60]


def _workflow_to_tool(workflow_name: str, workflow: Any) -> tuple[str, dict[str, Any]]:
    """Build (tool_name, tool_info) from a parsed ApprovalProcess."""
    tool_name = f"submit_{_slugify(workflow_name)}"[:60]
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field_name, field in (workflow.form or {}).items():
        field_type = field.type.value if hasattr(field.type, "value") else str(field.type)
        if field_type in _EXCLUDED_FIELD_TYPES:
            continue
        if field.calculated or field.readonly or field.jsonata:
            continue
        properties[field_name] = _field_to_schema(field)
        if field.required:
            required.append(field_name)

    return tool_name, {
        "workflow_name": workflow_name,
        "description": workflow.description or f"Submit a {workflow.name} request",
        "required": required,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def _load_workflow_tools(client: ApprovalMLClient, workflows_dir: str) -> dict[str, dict[str, Any]]:
    """
    Parse every *.yaml/*.yml file in workflows_dir, register each with the
    runtime (best-effort — failures are logged, not fatal), and return a
    tool_name -> tool_info map for submit_<name> tool generation.
    """
    from approvalml.parser import ApprovalMLParser

    path = Path(workflows_dir)
    if not path.exists():
        logger.warning("APPROVALML_WORKFLOWS_DIR %s does not exist — no directory tools loaded", workflows_dir)
        return {}

    tools: dict[str, dict[str, Any]] = {}
    for yaml_path in sorted(list(path.glob("*.yaml")) + list(path.glob("*.yml"))):
        yaml_content = yaml_path.read_text(encoding="utf-8")
        parser = ApprovalMLParser()
        workflow = parser.parse_yaml(yaml_content)
        if workflow is None or parser.validation_errors:
            logger.warning("Skipping %s: %s", yaml_path.name, "; ".join(parser.validation_errors))
            continue

        workflow_name = yaml_path.stem
        try:
            client.register_workflow(workflow_name, yaml_content)
        except Exception as exc:
            logger.warning("Could not register workflow %s with the runtime: %s", workflow_name, exc)

        tool_name, tool_info = _workflow_to_tool(workflow_name, workflow)
        tools[tool_name] = tool_info
        logger.info("Exposed workflow %s as MCP tool %s", workflow_name, tool_name)

    return tools


async def run_stdio(client: ApprovalMLClient, workflow_tools: dict[str, dict[str, Any]]) -> None:
    try:
        import mcp.server.stdio
        from mcp.server.models import InitializationOptions
    except ImportError as e:
        raise ImportError(
            "MCP server dependencies not installed. "
            "Run: pip install 'approvalml[mcp]'"
        ) from e

    server = _build_server(client, workflow_tools)
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
    workflows_dir: str | None = None,
    http: bool = False,
    port: int = 3100,
) -> None:
    """Entry point called by the CLI."""
    import asyncio

    client = ApprovalMLClient(api_url=api_url, api_token=api_token)
    resolved_workflows_dir = workflows_dir or os.environ.get("APPROVALML_WORKFLOWS_DIR", "")
    workflow_tools = _load_workflow_tools(client, resolved_workflows_dir) if resolved_workflows_dir else {}

    if http:
        raise NotImplementedError(
            "HTTP transport not yet implemented. Use stdio mode (default) for Claude Desktop."
        )

    asyncio.run(run_stdio(client, workflow_tools))
