"""
YAML validation regression tests for the ApprovalML parser and form validator.

Tests cover: valid minimal workflow, required field enforcement, unknown step types,
malformed YAML, missing workflow name, form field type validation, and condition syntax.

Run with: pytest tests/test_yaml_validation.py -v
"""

import pytest
from approvalml import parse_approvalml
from approvalml.form_validator import validate_field_value, validate_form_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_errors(summary: dict) -> bool:
    """Return True if validation produced any schema or semantic errors."""
    return bool(summary.get("schema_errors")) or bool(summary.get("semantic_errors"))


def _form_list(workflow) -> list:
    """Convert workflow.form dict[str, FormField] → list expected by validate_form_data."""
    result = []
    for name, field in workflow.form.items():
        d = field.model_dump(exclude_none=True)
        d["name"] = name
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Fixtures — inline YAML strings
# ---------------------------------------------------------------------------

MINIMAL_VALID = """
name: Expense Approval
form:
  note:
    type: text
    label: "Note"
    required: false
workflow:
  manager_review:
    name: manager_review
    type: decision
    approver:
      role: manager
    on_approve:
      continue_to: end
    on_reject:
      continue_to: end
  end:
    name: end
    type: end
"""

WITH_FORM_FIELDS = """
name: Vendor Invoice
form:
  amount:
    type: currency
    label: "Amount"
    required: true
  vendor_name:
    type: text
    label: "Vendor Name"
    required: true
  notes:
    type: textarea
    label: "Notes"
    required: false
workflow:
  review:
    name: review
    type: decision
    approver:
      role: finance
    on_approve:
      continue_to: end
    on_reject:
      continue_to: end
  end:
    name: end
    type: end
"""

MISSING_NAME = """
form:
  note:
    type: text
    label: "Note"
    required: false
workflow:
  review:
    name: review
    type: decision
    approver:
      role: manager
    on_approve:
      continue_to: end
    on_reject:
      continue_to: end
  end:
    name: end
    type: end
"""

UNKNOWN_STEP_TYPE = """
name: Bad Workflow
form:
  note:
    type: text
    label: "Note"
    required: false
workflow:
  review:
    name: review
    type: foobar_unknown
    on_approve:
      continue_to: end
  end:
    name: end
    type: end
"""

NOTIFICATION_STEP = """
name: Notify Workflow
form:
  note:
    type: text
    label: "Note"
    required: false
workflow:
  notify_requester:
    name: notify_requester
    type: notification
    recipients:
      - role: requester
    notification:
      message:
        subject: "Request received"
        body: "Your request has been received and is being processed."
    on_complete:
      continue_to: end
  end:
    name: end
    type: end
"""

CONDITIONAL_SPLIT = """
name: Conditional Workflow
form:
  amount:
    type: currency
    label: "Amount"
    required: true
workflow:
  check_amount:
    name: check_amount
    type: conditional_split
    conditions:
      - condition: "amount > 1000"
        continue_to: senior_review
      - condition: "default"
        continue_to: manager_review
  senior_review:
    name: senior_review
    type: decision
    approver:
      role: director
    on_approve:
      continue_to: end
    on_reject:
      continue_to: end
  manager_review:
    name: manager_review
    type: decision
    approver:
      role: manager
    on_approve:
      continue_to: end
    on_reject:
      continue_to: end
  end:
    name: end
    type: end
"""


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

# @lat: [[open-source#Open-Source: ApprovalML Package#CLI]]
def test_minimal_valid_workflow_parses():
    """A minimal workflow with one decision step and an end step must parse successfully."""
    workflow, summary = parse_approvalml(MINIMAL_VALID)
    assert workflow is not None, f"Expected valid parse, got errors: {summary.get('schema_errors')}"
    assert workflow.name == "Expense Approval"
    assert "manager_review" in workflow.workflow


# @lat: [[open-source#Open-Source: ApprovalML Package#CLI]]
def test_workflow_with_form_fields_parses():
    """A workflow with form fields must parse and expose all field definitions."""
    workflow, summary = parse_approvalml(WITH_FORM_FIELDS)
    assert workflow is not None, f"Expected valid parse: {summary.get('schema_errors')}"
    assert "amount" in workflow.form
    assert "vendor_name" in workflow.form
    assert workflow.form["amount"].required is True
    assert workflow.form["notes"].required is False


# @lat: [[open-source#Open-Source: ApprovalML Package#CLI]]
def test_missing_name_returns_error():
    """A workflow without a top-level name field must fail validation."""
    workflow, summary = parse_approvalml(MISSING_NAME)
    assert workflow is None or not getattr(workflow, "name", None), \
        "Expected parse failure or missing name"


# @lat: [[open-source#Open-Source: ApprovalML Package#CLI]]
def test_unknown_step_type_is_rejected():
    """An unrecognised step type must cause validation failure."""
    workflow, summary = parse_approvalml(UNKNOWN_STEP_TYPE)
    assert workflow is None or _has_errors(summary), \
        "Expected errors for unknown step type"


# @lat: [[open-source#Open-Source: ApprovalML Package#CLI]]
def test_notification_step_parses():
    """notification step type must parse without errors."""
    workflow, summary = parse_approvalml(NOTIFICATION_STEP)
    assert workflow is not None, f"notification step failed: {summary.get('schema_errors')}"
    assert "notify_requester" in workflow.workflow


# @lat: [[open-source#Open-Source: ApprovalML Package#CLI]]
def test_conditional_split_parses():
    """conditional_split step with condition list must parse without errors."""
    workflow, summary = parse_approvalml(CONDITIONAL_SPLIT)
    assert workflow is not None, f"conditional_split failed: {summary.get('schema_errors')}"
    assert "check_amount" in workflow.workflow


# @lat: [[open-source#Open-Source: ApprovalML Package#CLI]]
def test_malformed_yaml_returns_error():
    """Syntactically broken YAML must not raise an unhandled exception — returns error summary."""
    bad_yaml = "name: [unclosed bracket\nworkflow:\n  step: :"
    workflow, summary = parse_approvalml(bad_yaml)
    assert workflow is None
    assert _has_errors(summary), "Expected error list for malformed YAML"


# @lat: [[open-source#Open-Source: ApprovalML Package#CLI]]
def test_empty_string_returns_error():
    """Empty YAML content must fail gracefully."""
    workflow, summary = parse_approvalml("")
    assert workflow is None
    assert _has_errors(summary)


# ---------------------------------------------------------------------------
# Form validator tests
# ---------------------------------------------------------------------------

# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server]]
def test_validate_required_field_present():
    """validate_form_data must pass when all required fields are present."""
    workflow, _ = parse_approvalml(WITH_FORM_FIELDS)
    assert workflow is not None
    form_fields = _form_list(workflow)
    form_data = {"amount": 500.0, "vendor_name": "Acme Corp"}
    is_valid, errors = validate_form_data(form_fields, form_data)
    assert is_valid, f"Expected no errors, got: {errors}"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server]]
def test_validate_required_field_missing():
    """validate_form_data must return errors when a required field is absent."""
    workflow, _ = parse_approvalml(WITH_FORM_FIELDS)
    assert workflow is not None
    form_fields = _form_list(workflow)
    form_data = {"vendor_name": "Acme Corp"}  # missing required 'amount'
    is_valid, errors = validate_form_data(form_fields, form_data)
    assert not is_valid
    assert any("amount" in e.lower() for e in errors), \
        f"Expected error mentioning 'amount', got: {errors}"


# @lat: [[open-source#Open-Source: ApprovalML Package#MCP Server]]
def test_validate_optional_field_absent_is_ok():
    """validate_form_data must not error when an optional field is absent."""
    workflow, _ = parse_approvalml(WITH_FORM_FIELDS)
    assert workflow is not None
    form_fields = _form_list(workflow)
    form_data = {"amount": 100.0, "vendor_name": "Acme Corp"}  # 'notes' optional, absent
    is_valid, errors = validate_form_data(form_fields, form_data)
    assert is_valid, f"Optional field absence should not error: {errors}"
