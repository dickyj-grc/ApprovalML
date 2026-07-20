"""
Unit tests for resolve_gated_call — the shared gate/workflow dispatch helper
in mcp_wrap.py, including the _approval_instance_id re-call fix.
"""

from unittest.mock import MagicMock

import pytest

from approvalml.mcp_wrap import INSTANCE_ID_PARAM, resolve_gated_call


def _client(**overrides) -> MagicMock:
    client = MagicMock()
    client.request_approval = MagicMock(return_value={"instance_id": "gate-1", "status": "pending"})
    client.submit_workflow = MagicMock(return_value={"instance_id": "wf-1", "status": "running"})
    client.check_approval_status = MagicMock(return_value={"status": "pending"})
    client.get_workflow_status = MagicMock(return_value={"status": "running"})
    for k, v in overrides.items():
        setattr(client, k, v)
    return client


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Gate and workflow dispatch]]
@pytest.mark.asyncio
async def test_first_call_creates_gate():
    """A first call (no instance id present) creates a new gate, not a check."""
    client = _client()
    result = await resolve_gated_call(client, "gate", None, "delete_file", {"path": "x"}, "a@example.com")
    client.request_approval.assert_called_once()
    assert result["pending"] is True
    assert result["instance_id"] == "gate-1"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Gate and workflow dispatch]]
@pytest.mark.asyncio
async def test_recall_with_instance_id_checks_status_instead_of_creating_new_gate():
    """This is the bug fix: re-calling with _approval_instance_id must not create a second gate."""
    client = _client()
    result = await resolve_gated_call(
        client, "gate", None, "delete_file",
        {"path": "x", INSTANCE_ID_PARAM: "gate-1"}, "a@example.com",
    )
    client.request_approval.assert_not_called()
    client.check_approval_status.assert_called_once_with("gate-1")
    assert result.get("_forward") is not True  # still pending in this mock


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Gate and workflow dispatch]]
@pytest.mark.asyncio
async def test_recall_forwards_once_gate_approved():
    """Once check_approval_status reports approved, the caller is told to forward."""
    client = _client(check_approval_status=MagicMock(return_value={"status": "approved"}))
    result = await resolve_gated_call(
        client, "gate", None, "delete_file",
        {"path": "x", INSTANCE_ID_PARAM: "gate-1"}, "a@example.com",
    )
    assert result == {"_forward": True}


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Gate and workflow dispatch]]
@pytest.mark.asyncio
async def test_first_call_submits_workflow_with_merged_form_data():
    """Workflow action merges tool_name and the raw tool arguments (nested under 'arguments') into form_data."""
    client = _client()
    await resolve_gated_call(
        client, "workflow", "github_merge_guard", "merge_pull_request",
        {"base": "main"}, "a@example.com",
    )
    client.submit_workflow.assert_called_once_with(
        "github_merge_guard", {"tool_name": "merge_pull_request", "arguments": {"base": "main"}}
    )


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Gate and workflow dispatch]]
@pytest.mark.asyncio
async def test_recall_forwards_once_workflow_completed():
    """Once get_workflow_status reports completed, the caller is told to forward."""
    client = _client(get_workflow_status=MagicMock(return_value={"status": "completed"}))
    result = await resolve_gated_call(
        client, "workflow", "github_merge_guard", "merge_pull_request",
        {"base": "main", INSTANCE_ID_PARAM: "wf-1"}, "a@example.com",
    )
    assert result == {"_forward": True}
    client.submit_workflow.assert_not_called()
