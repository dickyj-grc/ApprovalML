"""
Unit tests for the trigger adapter layer: registry dispatch, built-in
adapter validation parity with the old parser rules, runtime-state init
shape, and parser-level delegation.

Run with: pytest tests/test_trigger_adapters.py -v
"""

import pytest

from approvalml.parser import parse_approvalml
from approvalml.triggers import (
    CronAdapter,
    OneTimeAdapter,
    TriggerAdapter,
    TriggerRegistry,
    UnknownTriggerTypeError,
    WebhookAdapter,
    default_registry,
    register_builtin_adapters,
)

BASE_YAML = """
name: Daily Scan
triggers:
{triggers}
form:
  note:
    type: text
    label: Note
    required: false
workflow:
  end:
    name: end
    type: end
"""


def _workflow_with(trigger_block: str):
    return BASE_YAML.format(triggers=trigger_block)


def _errors(yaml_content: str) -> str:
    """Parse YAML and return the joined validation errors ("" if valid)."""
    workflow, summary = parse_approvalml(yaml_content)
    assert workflow is None or summary["is_valid"]
    return "\n".join(summary["schema_errors"])


# ---------------------------------------------------------------------------
# Registry dispatch
# ---------------------------------------------------------------------------

def test_default_registry_resolves_builtin_types():
    assert default_registry.get("cron") is CronAdapter
    assert default_registry.get("one_time") is OneTimeAdapter
    assert default_registry.get("webhook") is WebhookAdapter
    assert default_registry.list_types() == ["cron", "one_time", "webhook"]


def test_registry_unknown_type_raises():
    with pytest.raises(UnknownTriggerTypeError) as exc_info:
        default_registry.get("asset_expiry")
    assert "asset_expiry" in str(exc_info.value)
    assert not default_registry.is_registered("asset_expiry")


def test_custom_registry_register_and_get():
    class CustomAdapter(TriggerAdapter):
        trigger_type = "custom_thing"

    registry = TriggerRegistry()
    registry.register(CustomAdapter)
    assert registry.get("custom_thing") is CustomAdapter
    assert registry.list_types() == ["custom_thing"]

    with pytest.raises(ValueError, match="already registered"):
        registry.register(CustomAdapter)


def test_register_builtin_adapters_is_idempotent():
    register_builtin_adapters(default_registry)
    assert default_registry.list_types() == ["cron", "one_time", "webhook"]


# ---------------------------------------------------------------------------
# Built-in adapter validation (parity with old parser rules)
# ---------------------------------------------------------------------------

def test_cron_requires_schedule():
    issues = CronAdapter.validate({})
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].field == "schedule"
    assert "schedule" in issues[0].message
    assert CronAdapter.validate({"schedule": ""})[0].field == "schedule"
    assert CronAdapter.validate({"schedule": "0 2 * * *"}) == []


def test_one_time_requires_schedule():
    issues = OneTimeAdapter.validate({})
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].field == "schedule"
    assert OneTimeAdapter.validate({"schedule": "2026-10-01 09:00:00"}) == []


def test_webhook_rejects_schedule():
    issues = WebhookAdapter.validate({"schedule": "0 2 * * *"})
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].field == "schedule"
    assert WebhookAdapter.validate({}) == []


@pytest.mark.parametrize("adapter", [CronAdapter, OneTimeAdapter, WebhookAdapter])
def test_max_runs_must_be_at_least_one(adapter):
    config = {"max_runs": 0, "schedule": "0 2 * * *"}
    if adapter is WebhookAdapter:
        config.pop("schedule")  # webhook rejects schedules; keep the test max-runs-only
    issues = adapter.validate(config)
    assert any(i.severity == "error" and i.field == "max_runs" for i in issues)
    config["max_runs"] = 1
    assert adapter.validate(config) == []


# ---------------------------------------------------------------------------
# tunable_fields declarations
# ---------------------------------------------------------------------------

def test_tunable_fields_contents():
    cron_tunables = {
        "schedule", "max_runs", "allow_concurrent",
        "requestor_email", "requestor_company_role",
        "preset_form_data", "data_condition",
    }
    assert CronAdapter.tunable_fields == frozenset(cron_tunables)
    assert OneTimeAdapter.tunable_fields == frozenset(cron_tunables)
    assert WebhookAdapter.tunable_fields == frozenset(cron_tunables - {"schedule"})


def test_classification_flags():
    assert CronAdapter.is_schedulable is True
    assert OneTimeAdapter.is_schedulable is True
    assert WebhookAdapter.is_schedulable is False
    assert WebhookAdapter.generates_webhook_token is True
    for adapter in (CronAdapter, OneTimeAdapter, WebhookAdapter):
        assert adapter.is_external_engine is False
        assert isinstance(adapter.tunable_fields, frozenset)


# ---------------------------------------------------------------------------
# initialize() runtime-state shape parity with SchedulerService.initialize_triggers
# ---------------------------------------------------------------------------

def _expected_runtime_state(trigger_type, schedule=None, max_runs=None, requestor_default=42, **overrides):
    state = {
        "trigger_type": trigger_type,
        "schedule": schedule,
        "webhook_token": None,
        "next_run_at": None,
        "last_run_at": None,
        "is_paused": False,
        "run_count": 0,
        "max_runs": max_runs,
        "preset_form_data": None,
        "requestor_email": None,
        "requestor_company_role": None,
        "requestor_id": requestor_default,
        "data_condition": None,
    }
    state.update(overrides)
    return state


def test_initialize_matches_runtime_state_shape():
    config = {
        "type": "cron",
        "schedule": "0 2 * * *",
        "max_runs": 10,
        "preset_form_data": {"severity_threshold": "critical"},
        "data_condition": {"data_processor_name": "GCP IAM Users"},
    }
    state = CronAdapter.initialize(config, requestor_default=42)

    expected = _expected_runtime_state(
        "cron",
        schedule="0 2 * * *",
        max_runs=10,
        preset_form_data={"severity_threshold": "critical"},
        data_condition={"data_processor_name": "GCP IAM Users"},
    )
    for key, value in expected.items():
        assert state[key] == value, key
    # created_at is set by the adapter; trigger_index/next_run_at are caller-side.
    assert isinstance(state["created_at"], str) and state["created_at"]
    assert "trigger_index" not in state
    assert set(state.keys()) == set(expected.keys()) | {"created_at"}


def test_initialize_requestor_id_fallback_logic():
    # No named requestor → fall back to the caller-supplied default.
    assert CronAdapter.initialize({"schedule": "0 2 * * *"}, requestor_default=7)["requestor_id"] == 7
    # Named requestor (role or email) → requestor_id must stay None.
    assert CronAdapter.initialize(
        {"schedule": "0 2 * * *", "requestor_company_role": "security_team"}, requestor_default=7
    )["requestor_id"] is None
    assert CronAdapter.initialize(
        {"schedule": "0 2 * * *", "requestor_email": "a@example.com"}, requestor_default=7
    )["requestor_id"] is None


def test_initialize_webhook_leaves_token_for_app():
    state = WebhookAdapter.initialize({}, requestor_default=None)
    assert state["webhook_token"] is None
    assert state["trigger_type"] == "webhook"
    assert state["schedule"] is None


# ---------------------------------------------------------------------------
# Parser-level delegation
# ---------------------------------------------------------------------------

def test_parser_accepts_cron_trigger():
    yaml_content = _workflow_with('  - type: cron\n    schedule: "0 2 * * *"\n    max_runs: 5')
    workflow, summary = parse_approvalml(yaml_content)
    assert workflow is not None, summary
    assert workflow.triggers[0].type == "cron"
    assert workflow.triggers[0].schedule == "0 2 * * *"


def test_parser_rejects_unknown_trigger_type():
    errors = _errors(_workflow_with("  - type: asset_expiry\n    schema: Calibration Record"))
    assert "asset_expiry" in errors
    assert "No trigger adapter registered" in errors


def test_parser_rejects_cron_without_schedule():
    errors = _errors(_workflow_with("  - type: cron"))
    assert "Cron triggers must have a 'schedule' field" in errors


def test_parser_rejects_one_time_without_schedule():
    errors = _errors(_workflow_with("  - type: one_time"))
    assert "One-time triggers must have a 'schedule' field" in errors


def test_parser_rejects_webhook_with_schedule():
    errors = _errors(_workflow_with('  - type: webhook\n    schedule: "0 2 * * *"'))
    assert "Webhook triggers should not have a 'schedule' field" in errors


def test_parser_rejects_max_runs_below_one():
    errors = _errors(_workflow_with('  - type: cron\n    schedule: "0 2 * * *"\n    max_runs: 0'))
    assert "max_runs must be at least 1" in errors


def test_parser_webhook_without_schedule_is_valid():
    workflow, summary = parse_approvalml(_workflow_with("  - type: webhook"))
    assert workflow is not None, summary
    assert workflow.triggers[0].type == "webhook"
