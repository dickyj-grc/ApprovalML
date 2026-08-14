"""
Runtime regression tests for ApprovalML MCP server dispatch, workflow-directory
tool generation, and the mcp_client request shape.

Tests cover: expression evaluator condition logic, mcp_server native + workflow-
directory tool dispatch (mocked client), and mcp_client request shape (mocked
httpx). All tests run without the SaaS backend and without a live Postgres.

Run with: pytest tests/test_runtime.py -v
"""

import types as builtin_types
from unittest.mock import MagicMock, patch

import pytest


def _cond(field, operator, value):
    """Build a condition object with attribute access (as expected by ConditionEvaluator)."""
    return builtin_types.SimpleNamespace(field=field, operator=operator, value=value)


# ---------------------------------------------------------------------------
# Expression evaluator tests
# ---------------------------------------------------------------------------

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
# mcp_server _dispatch tests — native tools
# ---------------------------------------------------------------------------

# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server]]
def test_dispatch_request_approval():
    """_dispatch must call client.request_approval with correct args."""
    from approvalml.mcp_server import _dispatch

    mock_client = MagicMock()
    mock_client.request_approval.return_value = {"instance_id": "abc-123", "status": "pending"}

    result = _dispatch(
        "request_approval",
        {"description": "Deploy to prod", "approver_email": "boss@example.com"},
        mock_client,
        {},
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

    mock_client = MagicMock()
    mock_client.check_approval_status.return_value = {"status": "approved"}

    result = _dispatch("check_approval_status", {"instance_id": "abc-123"}, mock_client, {})

    mock_client.check_approval_status.assert_called_once_with("abc-123")
    assert result["status"] == "approved"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server]]
def test_dispatch_list_pending():
    """_dispatch must call client.list_pending_approvals for list_pending_approvals tool."""
    from approvalml.mcp_server import _dispatch

    mock_client = MagicMock()
    mock_client.list_pending_approvals.return_value = []

    result = _dispatch("list_pending_approvals", {}, mock_client, {})
    mock_client.list_pending_approvals.assert_called_once()
    assert result == []


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server]]
def test_dispatch_unknown_tool_raises():
    """_dispatch must raise ValueError for an unrecognised tool name."""
    from approvalml.mcp_server import _dispatch

    mock_client = MagicMock()

    with pytest.raises(ValueError, match="Unknown tool"):
        _dispatch("nonexistent_tool", {}, mock_client, {})


# ---------------------------------------------------------------------------
# mcp_server _dispatch tests — scheduling management-plane tools
# ---------------------------------------------------------------------------

# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_dispatch_register_workflow():
    """_dispatch must forward register_workflow to client.register_workflow."""
    from approvalml.mcp_server import _dispatch

    mock_client = MagicMock()
    mock_client.register_workflow.return_value = {"name": "leave-request", "valid": True}

    result = _dispatch(
        "register_workflow", {"name": "leave-request", "yaml": "name: x"}, mock_client, {}
    )

    mock_client.register_workflow.assert_called_once_with("leave-request", "name: x")
    assert result["valid"] is True


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_dispatch_set_schedule_enabled():
    """_dispatch must coerce trigger_index/enabled and forward reason."""
    from approvalml.mcp_server import _dispatch

    mock_client = MagicMock()
    mock_client.set_schedule_enabled.return_value = {
        "workflow_name": "cve-scan", "trigger_index": 0, "enabled": True,
    }

    result = _dispatch(
        "set_schedule_enabled",
        {"workflow_name": "cve-scan", "trigger_index": 0, "enabled": True, "reason": "go-live"},
        mock_client,
        {},
    )

    mock_client.set_schedule_enabled.assert_called_once_with("cve-scan", 0, True, "go-live")
    assert result["enabled"] is True


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_dispatch_run_now():
    """_dispatch must forward run_now to client.run_now, defaulting form_data to None."""
    from approvalml.mcp_server import _dispatch

    mock_client = MagicMock()
    mock_client.run_now.return_value = {"instance_id": "i1", "status": "running"}

    result = _dispatch("run_now", {"workflow_name": "cve-scan"}, mock_client, {})

    mock_client.run_now.assert_called_once_with("cve-scan", None)
    assert result["instance_id"] == "i1"


# ---------------------------------------------------------------------------
# mcp_server — workflow-directory tool generation and dispatch
# ---------------------------------------------------------------------------

def _field(name, type_, required=False, options=None, **kw):
    from approvalml.parser import FormField
    return FormField(name=name, label=name, type=type_, required=required, options=options, **kw)


class _FakeWorkflow:
    def __init__(self, name, description, form):
        self.name = name
        self.description = description
        self.form = form


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server#Expose a Workflow Directory as MCP]]
def test_field_to_schema_select_extracts_enum():
    """_field_to_schema must extract a static enum list from a select field's options."""
    from approvalml.mcp_server import _field_to_schema

    field = _field("severity", "select", options=["critical", "high", "medium"])
    schema = _field_to_schema(field)
    assert schema == {"type": "string", "enum": ["critical", "high", "medium"]}


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server#Expose a Workflow Directory as MCP]]
def test_field_to_schema_number_and_email():
    """_field_to_schema must map number/email types to the documented JSON Schema shapes."""
    from approvalml.mcp_server import _field_to_schema

    assert _field_to_schema(_field("amount", "currency")) == {"type": "number"}
    assert _field_to_schema(_field("contact", "email")) == {"type": "string", "format": "email"}


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server#Expose a Workflow Directory as MCP]]
def test_workflow_to_tool_excludes_calculated_and_hidden_fields():
    """_workflow_to_tool must exclude calculated/readonly/hidden fields from the input schema."""
    from approvalml.mcp_server import _workflow_to_tool

    form = {
        "amount": _field("amount", "number", required=True),
        "internal_id": _field("internal_id", "hidden"),
        "total": _field("total", "number", calculated=True, formula="amount * 2"),
    }
    workflow = _FakeWorkflow("purchase-request", "Buy stuff", form)

    tool_name, info = _workflow_to_tool("purchase-request", workflow)

    assert tool_name == "submit_purchase_request"
    assert info["required"] == ["amount"]
    assert set(info["input_schema"]["properties"].keys()) == {"amount"}


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server#Expose a Workflow Directory as MCP]]
def test_dispatch_directory_tool_missing_required_field_raises():
    """_dispatch for a directory-loaded tool must reject a call missing a required field."""
    from approvalml.mcp_server import _dispatch

    workflow_tools = {
        "submit_leave_request": {
            "workflow_name": "leave-request",
            "required": ["leave_type"],
            "description": "x",
            "input_schema": {"type": "object", "properties": {}},
        }
    }
    mock_client = MagicMock()

    with pytest.raises(ValueError, match="Missing required field"):
        _dispatch("submit_leave_request", {}, mock_client, workflow_tools)

    mock_client.submit_workflow.assert_not_called()


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server#Expose a Workflow Directory as MCP]]
def test_dispatch_directory_tool_submits_workflow():
    """_dispatch for a directory-loaded tool must submit the underlying workflow by name."""
    from approvalml.mcp_server import _dispatch

    workflow_tools = {
        "submit_leave_request": {
            "workflow_name": "leave-request",
            "required": ["leave_type"],
            "description": "x",
            "input_schema": {"type": "object", "properties": {}},
        }
    }
    mock_client = MagicMock()
    mock_client.submit_workflow.return_value = {"instance_id": "i1", "status": "running"}

    result = _dispatch(
        "submit_leave_request", {"leave_type": "vacation"}, mock_client, workflow_tools
    )

    mock_client.submit_workflow.assert_called_once_with("leave-request", {"leave_type": "vacation"})
    assert result["instance_id"] == "i1"


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


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_client_set_schedule_enabled_posts_correct_payload():
    """ApprovalMLClient.set_schedule_enabled must POST to the per-trigger enabled endpoint."""
    from approvalml.mcp_client import ApprovalMLClient

    client = ApprovalMLClient(api_url="http://localhost:8765", api_token="admin-token")

    with patch("httpx.Client") as mock_http:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"workflow_name": "cve-scan", "trigger_index": 0, "enabled": True}
        mock_resp.raise_for_status = MagicMock()
        mock_http.return_value.__enter__.return_value.post.return_value = mock_resp

        result = client.set_schedule_enabled("cve-scan", 0, True, reason="go-live")

    call_args, call_kwargs = mock_http.return_value.__enter__.return_value.post.call_args
    assert call_args[0] == "http://localhost:8765/services/v1/workflows/cve-scan/schedule/0/enabled"
    assert call_kwargs["json"] == {"enabled": True, "reason": "go-live"}
    assert result["enabled"] is True


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_client_register_workflow_posts_name_and_yaml():
    """ApprovalMLClient.register_workflow must POST {name, yaml} to /services/v1/workflows."""
    from approvalml.mcp_client import ApprovalMLClient

    client = ApprovalMLClient(api_url="http://localhost:8765", api_token="admin-token")

    with patch("httpx.Client") as mock_http:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"name": "cve-scan", "valid": True}
        mock_resp.raise_for_status = MagicMock()
        mock_http.return_value.__enter__.return_value.post.return_value = mock_resp

        result = client.register_workflow("cve-scan", "name: cve-scan\nworkflow: {}")

    call_args, call_kwargs = mock_http.return_value.__enter__.return_value.post.call_args
    assert call_args[0] == "http://localhost:8765/services/v1/workflows"
    assert call_kwargs["json"] == {"name": "cve-scan", "yaml": "name: cve-scan\nworkflow: {}"}
    assert result["valid"] is True


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_client_list_workflows_gets_correct_url():
    """ApprovalMLClient.list_workflows must GET /services/v1/workflows."""
    from approvalml.mcp_client import ApprovalMLClient

    client = ApprovalMLClient(api_url="http://localhost:8765", api_token="admin-token")

    with patch("httpx.Client") as mock_http:
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"name": "cve-scan", "trigger_count": 1, "triggers": []}]
        mock_resp.raise_for_status = MagicMock()
        mock_http.return_value.__enter__.return_value.get.return_value = mock_resp

        result = client.list_workflows()

    call_args, _ = mock_http.return_value.__enter__.return_value.get.call_args
    assert call_args[0] == "http://localhost:8765/services/v1/workflows"
    assert result[0]["name"] == "cve-scan"


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_client_get_schedule_status_gets_per_workflow_url():
    """ApprovalMLClient.get_schedule_status must GET /services/v1/workflows/{name}/schedule."""
    from approvalml.mcp_client import ApprovalMLClient

    client = ApprovalMLClient(api_url="http://localhost:8765", api_token="admin-token")

    with patch("httpx.Client") as mock_http:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"workflow_name": "cve-scan", "triggers": []}
        mock_resp.raise_for_status = MagicMock()
        mock_http.return_value.__enter__.return_value.get.return_value = mock_resp

        result = client.get_schedule_status("cve-scan")

    call_args, _ = mock_http.return_value.__enter__.return_value.get.call_args
    assert call_args[0] == "http://localhost:8765/services/v1/workflows/cve-scan/schedule"
    assert result["workflow_name"] == "cve-scan"


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_client_run_now_tags_manual_trigger_source():
    """ApprovalMLClient.run_now must POST with trigger_source='manual', distinct from a normal submit."""
    from approvalml.mcp_client import ApprovalMLClient

    client = ApprovalMLClient(api_url="http://localhost:8765", api_token="admin-token")

    with patch("httpx.Client") as mock_http:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"instance_id": "i1", "status": "running"}
        mock_resp.raise_for_status = MagicMock()
        mock_http.return_value.__enter__.return_value.post.return_value = mock_resp

        result = client.run_now("cve-scan", {"severity_threshold": "high"})

    call_args, call_kwargs = mock_http.return_value.__enter__.return_value.post.call_args
    assert call_args[0] == "http://localhost:8765/services/v1/approvals/"
    assert call_kwargs["json"] == {
        "workflow_id": "cve-scan",
        "form_data": {"severity_threshold": "high"},
        "trigger_source": "manual",
    }
    assert result["instance_id"] == "i1"


# ---------------------------------------------------------------------------
# mcp_server — _load_workflow_tools against a real directory
# ---------------------------------------------------------------------------

# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server#Expose a Workflow Directory as MCP]]
def test_load_workflow_tools_scans_directory_and_registers(tmp_path):
    """_load_workflow_tools must parse every *.yaml file, register it, and build one tool per file."""
    from approvalml.mcp_server import _load_workflow_tools

    (tmp_path / "leave-request.yaml").write_text(
        "name: Leave Request\n"
        "form:\n"
        "  leave_type:\n"
        "    type: text\n"
        "    label: Type\n"
        "    required: true\n"
        "workflow:\n"
        "  end:\n"
        "    name: end\n"
        "    type: end\n"
    )
    (tmp_path / "not-a-workflow.txt").write_text("ignored — wrong extension")

    mock_client = MagicMock()
    tools = _load_workflow_tools(mock_client, str(tmp_path))

    assert set(tools.keys()) == {"submit_leave_request"}
    assert tools["submit_leave_request"]["workflow_name"] == "leave-request"
    assert tools["submit_leave_request"]["required"] == ["leave_type"]
    mock_client.register_workflow.assert_called_once()
    call_args = mock_client.register_workflow.call_args[0]
    assert call_args[0] == "leave-request"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server#Expose a Workflow Directory as MCP]]
def test_load_workflow_tools_skips_invalid_yaml_without_raising(tmp_path):
    """An invalid workflow file in the directory must be skipped (logged), not crash startup."""
    from approvalml.mcp_server import _load_workflow_tools

    (tmp_path / "broken.yaml").write_text("name: Broken\n# missing required form/workflow keys\n")

    mock_client = MagicMock()
    tools = _load_workflow_tools(mock_client, str(tmp_path))

    assert tools == {}
    mock_client.register_workflow.assert_not_called()


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server#Expose a Workflow Directory as MCP]]
def test_load_workflow_tools_registration_failure_does_not_drop_the_tool(tmp_path):
    """If the runtime is unreachable at startup, the tool must still be listed (best-effort registration)."""
    from approvalml.mcp_server import _load_workflow_tools

    (tmp_path / "leave-request.yaml").write_text(
        "name: Leave Request\n"
        "form:\n"
        "  leave_type:\n"
        "    type: text\n"
        "    label: Type\n"
        "    required: false\n"
        "workflow:\n"
        "  end:\n"
        "    name: end\n"
        "    type: end\n"
    )

    mock_client = MagicMock()
    mock_client.register_workflow.side_effect = ConnectionError("runtime unreachable")

    tools = _load_workflow_tools(mock_client, str(tmp_path))

    assert "submit_leave_request" in tools
