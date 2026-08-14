"""
Unit tests for WorkflowScheduler — the standalone runtime's deterministic
cron tick loop. Exercises tick()/arm/fire/auto-disable logic against an
in-memory fake store (no Postgres required); see test_audit_log.py for the
opt-in Postgres integration tests (APPROVALML_TEST_DATABASE_URL).

Run with: pytest tests/test_scheduler.py -v
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from approvalml.runtime.base import TriggerState
from approvalml.runtime.scheduler import WorkflowScheduler

CRON_YAML = """
name: Daily Scan
triggers:
  - type: cron
    schedule: "0 2 * * *"
    preset_form_data:
      severity_threshold: critical
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


class _FakeStore:
    """Minimal in-memory stand-in for WorkflowStore's trigger-state surface."""

    def __init__(self, yaml_content: str = CRON_YAML) -> None:
        self.yaml_content = yaml_content
        self.states: dict[tuple[str, int], TriggerState] = {}
        self.running_instances: set[tuple[str, int]] = set()

    def seed(self, workflow_name: str, trigger_index: int, **overrides) -> None:
        state = TriggerState(workflow_name=workflow_name, trigger_index=trigger_index, enabled=True)
        self.states[(workflow_name, trigger_index)] = replace(state, **overrides)

    async def list_trigger_states(self) -> list[TriggerState]:
        return list(self.states.values())

    async def get_workflow_yaml(self, name: str) -> Optional[str]:
        return self.yaml_content if name == "daily-scan" else None

    async def set_trigger_next_run(self, workflow_name, trigger_index, next_run_at) -> None:
        key = (workflow_name, trigger_index)
        self.states[key] = replace(self.states[key], next_run_at=next_run_at)

    async def set_trigger_enabled(self, workflow_name, trigger_index, enabled, actor=None, reason=None):
        key = (workflow_name, trigger_index)
        self.states[key] = replace(self.states[key], enabled=enabled)
        return self.states[key]

    async def record_trigger_run(self, workflow_name, trigger_index, *, success, error, next_run_at):
        key = (workflow_name, trigger_index)
        prev = self.states[key]
        failures = 0 if success else prev.consecutive_failures + 1
        self.states[key] = replace(
            prev,
            last_status="success" if success else "failed",
            last_error=error,
            next_run_at=next_run_at,
            consecutive_failures=failures,
        )
        return self.states[key]

    async def has_running_instance_for_trigger(self, workflow_name, trigger_index) -> bool:
        return (workflow_name, trigger_index) in self.running_instances


class _FakeEngine:
    def __init__(self, store: _FakeStore) -> None:
        self.wstore = store
        self.submitted: list[dict[str, Any]] = []
        self._raise: Optional[Exception] = None

    def fail_next_submit(self, exc: Exception) -> None:
        self._raise = exc

    async def submit_workflow(self, workflow_name, form_data, submitter_email=None, metadata=None):
        if self._raise is not None:
            exc, self._raise = self._raise, None
            raise exc
        self.submitted.append(
            {"workflow_name": workflow_name, "form_data": form_data,
             "submitter_email": submitter_email, "metadata": metadata}
        )
        return {"instance_id": "i1", "status": "running"}


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_tick_arms_a_freshly_enabled_trigger_without_firing():
    """A trigger with enabled=True and no next_run_at must be armed, not fired, on its first tick."""
    store = _FakeStore()
    store.seed("daily-scan", 0)  # enabled, next_run_at=None
    engine = _FakeEngine(store)
    scheduler = WorkflowScheduler(engine)

    asyncio.run(scheduler.tick())

    assert engine.submitted == []
    state = store.states[("daily-scan", 0)]
    assert state.next_run_at is not None


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_tick_fires_a_due_trigger_and_reschedules():
    """A trigger whose next_run_at is in the past must fire and get a fresh future next_run_at."""
    store = _FakeStore()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    store.seed("daily-scan", 0, next_run_at=past)
    engine = _FakeEngine(store)
    scheduler = WorkflowScheduler(engine)

    asyncio.run(scheduler.tick())

    assert len(engine.submitted) == 1
    submission = engine.submitted[0]
    assert submission["workflow_name"] == "daily-scan"
    assert submission["form_data"] == {"severity_threshold": "critical"}
    assert submission["metadata"] == {"trigger_source": "scheduler", "trigger_index": 0}

    state = store.states[("daily-scan", 0)]
    assert state.last_status == "success"
    assert state.consecutive_failures == 0
    assert datetime.fromisoformat(state.next_run_at) > datetime.now(timezone.utc)


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_tick_skips_a_trigger_not_yet_due():
    """A trigger whose next_run_at is in the future must not fire."""
    store = _FakeStore()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    store.seed("daily-scan", 0, next_run_at=future)
    engine = _FakeEngine(store)
    scheduler = WorkflowScheduler(engine)

    asyncio.run(scheduler.tick())

    assert engine.submitted == []


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_tick_ignores_a_disabled_trigger():
    """A disabled trigger must never fire, even if technically due."""
    store = _FakeStore()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    store.seed("daily-scan", 0, enabled=False, next_run_at=past)
    engine = _FakeEngine(store)
    scheduler = WorkflowScheduler(engine)

    asyncio.run(scheduler.tick())

    assert engine.submitted == []


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_auto_disables_after_max_consecutive_failures():
    """A trigger must be auto-disabled once it hits max_consecutive_failures in a row."""
    store = _FakeStore()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    store.seed("daily-scan", 0, next_run_at=past, consecutive_failures=2)
    engine = _FakeEngine(store)
    engine.fail_next_submit(RuntimeError("boom"))
    scheduler = WorkflowScheduler(engine, max_consecutive_failures=3)

    asyncio.run(scheduler.tick())

    state = store.states[("daily-scan", 0)]
    assert state.consecutive_failures == 3
    assert state.enabled is False


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_skips_tick_when_previous_run_still_in_progress():
    """allow_concurrent defaults to False — a still-running instance must skip this tick."""
    store = _FakeStore()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    store.seed("daily-scan", 0, next_run_at=past)
    store.running_instances.add(("daily-scan", 0))
    engine = _FakeEngine(store)
    scheduler = WorkflowScheduler(engine)

    asyncio.run(scheduler.tick())

    assert engine.submitted == []


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_resolve_requestor_prefers_explicit_email():
    """_resolve_requestor must prefer requestor_email over requestor_company_role."""
    from approvalml.parser import ApprovalMLParser

    yaml_content = CRON_YAML.replace(
        "severity_threshold: critical",
        "severity_threshold: critical\n    requestor_email: scanner@example.com",
    )
    parsed = ApprovalMLParser().parse_yaml(yaml_content)
    trigger = parsed.triggers[0]

    engine = _FakeEngine(_FakeStore())
    scheduler = WorkflowScheduler(engine)

    result = asyncio.run(scheduler._resolve_requestor(trigger))
    assert result == "scanner@example.com"
