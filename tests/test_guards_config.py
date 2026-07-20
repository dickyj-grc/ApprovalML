"""
Unit tests for GuardsConfig — the guards.tools schema on ApprovalProcess (parser.py).
"""

import pytest
from pydantic import ValidationError

from approvalml.parser import ApprovalProcess


def _base_doc(**guards_tools):
    return {
        "name": "Test Guard",
        "guards": {"tools": guards_tools},
        "form": {"fields": [{"name": "tool_name", "type": "text", "label": "Tool"}]},
        "workflow": {"done": {"name": "done", "type": "end"}},
    }


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Guards config (single-file classifier + workflow)]]
def test_guards_tools_accepts_valid_actions():
    """auto/gate/deny are all accepted values for a guards.tools entry."""
    doc = _base_doc(**{"get_*": "auto", "delete_*": "gate", "drop_*": "deny"})
    process = ApprovalProcess(**doc)
    assert process.guards.tools == {"get_*": "auto", "delete_*": "gate", "drop_*": "deny"}


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Guards config (single-file classifier + workflow)]]
def test_guards_tools_rejects_invalid_action():
    """A typo'd or unsupported action value (e.g. 'aut') is rejected at parse time, not silently accepted."""
    doc = _base_doc(**{"get_*": "aut"})
    with pytest.raises(ValidationError):
        ApprovalProcess(**doc)


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Wrap (Per-Server Stdio Gateway)#Guards config (single-file classifier + workflow)]]
def test_guards_tools_rejects_workflow_action():
    """'workflow' is not a valid guards.tools value — falling through to workflow: already is the escalation path."""
    doc = _base_doc(**{"merge_*": "workflow"})
    with pytest.raises(ValidationError):
        ApprovalProcess(**doc)
