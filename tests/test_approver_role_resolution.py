"""
Unit tests for role-based approver resolution in the standalone runtime.

Pure logic, no DB — uses SimpleNamespace stand-ins for the parsed step
definition, matching the duck-typing test_runtime.py already relies on.
The standalone runtime has no company directory (unlike the SaaS backend's
org-based role_resolver), so a bare role name like `approver: finance_manager`
resolves via the APPROVALML_ROLE_<NAME> environment variable convention.
"""

import os
import types as builtin_types

import pytest

from approvalml.runtime.workflow_engine import WorkflowError, _resolve_approvers, _role_env_var


def _step(approver=None, approvers=None):
    return builtin_types.SimpleNamespace(approver=approver, approvers=approvers)


def _approver_cfg(approver=None, dynamic_approver=None, role=None):
    return builtin_types.SimpleNamespace(approver=approver, dynamic_approver=dynamic_approver, role=role)


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Approver role resolution]]
def test_role_env_var_naming_is_sanitized():
    """Role names are uppercased and non-alphanumeric characters become underscores."""
    assert _role_env_var("finance_manager") == "APPROVALML_ROLE_FINANCE_MANAGER"
    assert _role_env_var("Finance Manager") == "APPROVALML_ROLE_FINANCE_MANAGER"
    assert _role_env_var("cfo") == "APPROVALML_ROLE_CFO"


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Approver role resolution]]
def test_shorthand_role_resolves_via_env(monkeypatch):
    """A bare approver: role_name string resolves through APPROVALML_ROLE_<NAME>."""
    monkeypatch.setenv("APPROVALML_ROLE_FINANCE_MANAGER", "alice@example.com, bob@example.com")
    step_def = _step(approver="finance_manager")
    emails = _resolve_approvers(step_def, {})
    assert emails == ["alice@example.com", "bob@example.com"]


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Approver role resolution]]
def test_shorthand_literal_email_bypasses_role_lookup():
    """A literal email in approver: is used directly — no env var lookup happens."""
    step_def = _step(approver="alice@example.com")
    assert _resolve_approvers(step_def, {}) == ["alice@example.com"]


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Approver role resolution]]
def test_unresolvable_role_raises_clear_error(monkeypatch):
    """A role with no matching env var raises WorkflowError instead of silently producing zero approvers."""
    monkeypatch.delenv("APPROVALML_ROLE_UNKNOWN_ROLE", raising=False)
    step_def = _step(approver="unknown_role")
    with pytest.raises(WorkflowError, match="APPROVALML_ROLE_UNKNOWN_ROLE"):
        _resolve_approvers(step_def, {})


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Approver role resolution]]
def test_unresolved_form_template_is_dropped_not_treated_as_role():
    """An unresolved ${form.field} placeholder is silently dropped, not misinterpreted as a role name."""
    step_def = _step(approver="${form.manager_email}")
    assert _resolve_approvers(step_def, {}) == []


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Approver role resolution]]
def test_resolved_form_template_is_used_as_email():
    """A ${form.field} placeholder that resolves to a real value is used as the approver email."""
    step_def = _step(approver="${form.manager_email}")
    assert _resolve_approvers(step_def, {"manager_email": "carol@example.com"}) == ["carol@example.com"]


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Approver role resolution]]
def test_list_form_role_field_resolves_via_env(monkeypatch):
    """The approvers: [{role: ...}] list form also resolves through the env var convention."""
    monkeypatch.setenv("APPROVALML_ROLE_CFO", "dana@example.com")
    step_def = _step(approvers=[_approver_cfg(role="cfo")])
    assert _resolve_approvers(step_def, {}) == ["dana@example.com"]


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Approver role resolution]]
def test_list_form_role_name_string_resolves_via_env(monkeypatch):
    """A bare role-like string in approvers: [{approver: ...}] also resolves as a role."""
    monkeypatch.setenv("APPROVALML_ROLE_FINANCE_MANAGER", "alice@example.com")
    step_def = _step(approvers=[_approver_cfg(approver="finance_manager")])
    assert _resolve_approvers(step_def, {}) == ["alice@example.com"]
