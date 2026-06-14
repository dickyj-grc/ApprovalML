"""
Runtime regression tests for ApprovalML MCP server dispatch and proxy resolution.

Tests cover: mcp_server native tool dispatch (mocked client), mcp_proxy tool
prefixing and resolution, expression evaluator condition logic, and the mcp_client
request shape (mocked httpx). All tests run without the SaaS backend.

Run with: pytest tests/test_runtime.py -v
"""

import json
import types as builtin_types
from unittest.mock import MagicMock, patch

import pytest


def _cond(field, operator, value):
    """Build a condition object with attribute access (as expected by ConditionEvaluator)."""
    return builtin_types.SimpleNamespace(field=field, operator=operator, value=value)


# ---------------------------------------------------------------------------
# Expression evaluator tests
# ---------------------------------------------------------------------------

# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Proxy (Wrapped-Server Passthrough)]]
def test_condition_evaluator_greater_than():
    """ConditionEvaluator must evaluate numeric > correctly."""
    from approvalml.expression_evaluator import ConditionEvaluator, EvaluationContext

    ctx = EvaluationContext(
        form_data={"amount": 1500, "currency": "USD"},
        workflow_variables={},
        requestor={},
        system={},
    )
    evaluator = ConditionEvaluator(ctx)
    result = evaluator.evaluate_conditions([_cond("amount", ">", 1000)])
    assert result is True


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Proxy (Wrapped-Server Passthrough)]]
def test_condition_evaluator_equals():
    """ConditionEvaluator must evaluate string == correctly."""
    from approvalml.expression_evaluator import ConditionEvaluator, EvaluationContext

    ctx = EvaluationContext(
        form_data={"department": "HR"},
        workflow_variables={},
        requestor={},
        system={},
    )
    evaluator = ConditionEvaluator(ctx)
    result = evaluator.evaluate_conditions([_cond("department", "==", "HR")])
    assert result is True


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Proxy (Wrapped-Server Passthrough)]]
def test_condition_evaluator_false():
    """ConditionEvaluator must return False when condition is not met."""
    from approvalml.expression_evaluator import ConditionEvaluator, EvaluationContext

    ctx = EvaluationContext(
        form_data={"amount": 500},
        workflow_variables={},
        requestor={},
        system={},
    )
    evaluator = ConditionEvaluator(ctx)
    result = evaluator.evaluate_conditions([_cond("amount", ">", 1000)])
    assert result is False


# ---------------------------------------------------------------------------
# mcp_proxy — WrappedServerRegistry tests
# ---------------------------------------------------------------------------

# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Proxy (Wrapped-Server Passthrough)]]
def test_registry_resolve_valid_prefix():
    """resolve() must parse guarded__<server>__<tool> correctly."""
    from approvalml.mcp_proxy import WrappedServer, WrappedServerRegistry

    server = WrappedServer(name="filesystem", url="http://localhost:3001")
    registry = WrappedServerRegistry([server])

    result = registry.resolve("guarded__filesystem__write_file")
    assert result is not None
    resolved_server, tool_name = result
    assert resolved_server.name == "filesystem"
    assert tool_name == "write_file"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Proxy (Wrapped-Server Passthrough)]]
def test_registry_resolve_unknown_server():
    """resolve() must return None for an unknown server name."""
    from approvalml.mcp_proxy import WrappedServerRegistry

    registry = WrappedServerRegistry([])
    assert registry.resolve("guarded__missing__some_tool") is None


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Proxy (Wrapped-Server Passthrough)]]
def test_registry_resolve_no_prefix():
    """resolve() must return None for names without the guarded__ prefix."""
    from approvalml.mcp_proxy import WrappedServer, WrappedServerRegistry

    server = WrappedServer(name="filesystem", url="http://localhost:3001")
    registry = WrappedServerRegistry([server])
    assert registry.resolve("write_file") is None


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Proxy (Wrapped-Server Passthrough)]]
def test_wrapped_server_is_gated_all():
    """WrappedServer with gate=None gates ALL tools."""
    from approvalml.mcp_proxy import WrappedServer

    server = WrappedServer(name="fs", url="http://localhost:3001", gate=None)
    assert server.is_gated("anything") is True
    assert server.is_gated("write_file") is True


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Proxy (Wrapped-Server Passthrough)]]
def test_wrapped_server_is_gated_selective():
    """WrappedServer with gate=[...] only gates listed tools."""
    from approvalml.mcp_proxy import WrappedServer

    server = WrappedServer(name="fs", url="http://localhost:3001", gate=["write_file", "delete_file"])
    assert server.is_gated("write_file") is True
    assert server.is_gated("read_file") is False


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Proxy (Wrapped-Server Passthrough)]]
def test_list_all_tools_prefixes_name():
    """list_all_tools() must prefix gated tool names with guarded__<server>__."""
    from approvalml.mcp_proxy import WrappedServer, WrappedServerRegistry

    mock_tools = [{"name": "write_file", "description": "Write a file"}]
    server = WrappedServer(name="filesystem", url="http://localhost:3001", gate=["write_file"])

    with patch.object(server, "list_tools", return_value=mock_tools):
        registry = WrappedServerRegistry([server])
        tools = registry.list_all_tools()

    assert len(tools) == 1
    assert tools[0]["name"] == "guarded__filesystem__write_file"
    assert "Requires human approval" in tools[0]["description"]


# ---------------------------------------------------------------------------
# mcp_server _dispatch tests
# ---------------------------------------------------------------------------

# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server]]
def test_dispatch_request_approval():
    """_dispatch must call client.request_approval with correct args."""
    from approvalml.mcp_server import _dispatch
    from approvalml.mcp_proxy import WrappedServerRegistry

    mock_client = MagicMock()
    mock_client.request_approval.return_value = {"instance_id": "abc-123", "status": "pending"}
    proxy = WrappedServerRegistry([])

    result = _dispatch(
        "request_approval",
        {"description": "Deploy to prod", "approver_email": "boss@example.com"},
        mock_client,
        proxy,
    )

    mock_client.request_approval.assert_called_once_with(
        description="Deploy to prod",
        approver_email="boss@example.com",
        context=None,
    )
    assert result["instance_id"] == "abc-123"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server]]
def test_dispatch_check_approval_status():
    """_dispatch must call client.check_approval_status with instance_id."""
    from approvalml.mcp_server import _dispatch
    from approvalml.mcp_proxy import WrappedServerRegistry

    mock_client = MagicMock()
    mock_client.check_approval_status.return_value = {"status": "approved"}
    proxy = WrappedServerRegistry([])

    result = _dispatch("check_approval_status", {"instance_id": "abc-123"}, mock_client, proxy)

    mock_client.check_approval_status.assert_called_once_with("abc-123")
    assert result["status"] == "approved"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server]]
def test_dispatch_list_pending():
    """_dispatch must call client.list_pending_approvals for list_pending_approvals tool."""
    from approvalml.mcp_server import _dispatch
    from approvalml.mcp_proxy import WrappedServerRegistry

    mock_client = MagicMock()
    mock_client.list_pending_approvals.return_value = []
    proxy = WrappedServerRegistry([])

    result = _dispatch("list_pending_approvals", {}, mock_client, proxy)
    mock_client.list_pending_approvals.assert_called_once()
    assert result == []


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server]]
def test_dispatch_unknown_tool_raises():
    """_dispatch must raise ValueError for an unrecognised tool name."""
    from approvalml.mcp_server import _dispatch
    from approvalml.mcp_proxy import WrappedServerRegistry

    mock_client = MagicMock()
    proxy = WrappedServerRegistry([])

    with pytest.raises(ValueError, match="Unknown tool"):
        _dispatch("nonexistent_tool", {}, mock_client, proxy)


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server]]
def test_dispatch_proxied_tool_returns_pending():
    """_dispatch for a guarded proxied tool must create an approval gate and return pending."""
    from approvalml.mcp_server import _dispatch
    from approvalml.mcp_proxy import WrappedServer, WrappedServerRegistry

    mock_client = MagicMock()
    mock_client.request_approval.return_value = {"instance_id": "gate-xyz", "status": "pending"}

    server = WrappedServer(name="filesystem", url="http://localhost:3001", gate=["write_file"])
    proxy = WrappedServerRegistry([server])

    result = _dispatch(
        "guarded__filesystem__write_file",
        {"path": "/etc/hosts", "content": "evil"},
        mock_client,
        proxy,
    )

    assert result["pending"] is True
    assert result["instance_id"] == "gate-xyz"
    assert "check_approval_status" in result["message"]


# ---------------------------------------------------------------------------
# mcp_client request shape tests (mocked httpx)
# ---------------------------------------------------------------------------

# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Client]]
def test_client_request_approval_posts_correct_payload():
    """ApprovalMLClient.request_approval must POST the right JSON body."""
    from approvalml.mcp_client import ApprovalMLClient

    client = ApprovalMLClient(api_url="http://localhost:8000", api_token="test-token")

    with patch("httpx.Client") as mock_http:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"instance_id": "x1", "status": "pending"}
        mock_resp.raise_for_status = MagicMock()
        mock_http.return_value.__enter__.return_value.post.return_value = mock_resp

        result = client.request_approval("Deploy to prod", "boss@example.com", context={"env": "prod"})

    call_kwargs = mock_http.return_value.__enter__.return_value.post.call_args
    payload = call_kwargs[1]["json"]
    assert payload["description"] == "Deploy to prod"
    assert payload["approver_email"] == "boss@example.com"
    assert payload["context"] == {"env": "prod"}
    assert result["instance_id"] == "x1"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Client]]
def test_client_uses_bearer_auth():
    """ApprovalMLClient must include Authorization: Bearer header when token is set."""
    from approvalml.mcp_client import ApprovalMLClient

    client = ApprovalMLClient(api_url="http://localhost:8000", api_token="secret-token")

    with patch("httpx.Client") as mock_http:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"instance_id": "x2", "status": "pending"}
        mock_resp.raise_for_status = MagicMock()
        mock_http.return_value.__enter__.return_value.post.return_value = mock_resp

        client.request_approval("Test", "user@example.com")

    call_kwargs = mock_http.return_value.__enter__.return_value.post.call_args
    headers = call_kwargs[1]["headers"]
    assert headers.get("Authorization") == "Bearer secret-token"
