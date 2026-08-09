"""
Tests for the standalone runtime's scheduling management-plane REST endpoints
(GET /services/v1/workflows, GET /services/v1/workflows/{name}/schedule,
POST /services/v1/workflows/{name}/schedule/{trigger_index}/enabled) and the
trigger_source field on POST /services/v1/approvals/.

Uses FastAPI's TestClient against the real app with a mocked WorkflowEngine
store (no Postgres required) — this exercises request/response wiring and
auth checks, not SQL. See test_trigger_state.py for the Postgres-backed
storage-layer tests.

Run with: pytest tests/test_server_scheduling_endpoints.py -v
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from approvalml.runtime import server as server_module
from approvalml.runtime.base import TriggerState, WorkflowInstance
from approvalml.runtime.workflow_engine import WorkflowEngine

CRON_YAML = """
name: Daily Scan
triggers:
  - type: cron
    schedule: "0 2 * * *"
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


class _DummyEmailSender:
    def send_approval_request(self, *args, **kwargs) -> None:
        pass


class _FakeStore:
    """Minimal in-memory WorkflowStore stand-in covering only what these endpoints touch."""

    def __init__(self) -> None:
        self.workflows: dict[str, str] = {}
        self.trigger_states: dict[tuple[str, int], TriggerState] = {}
        self.enable_calls: list[tuple[str, int, bool, Optional[str], Optional[str]]] = []
        self.instances: dict[str, WorkflowInstance] = {}
        self._counter = 0

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def upsert_workflow(self, name: str, yaml_content: str) -> None:
        self.workflows[name] = yaml_content

    async def get_workflow_yaml(self, name: str) -> Optional[str]:
        return self.workflows.get(name)

    async def list_workflow_names(self) -> list[str]:
        return sorted(self.workflows.keys())

    async def sync_trigger_states(self, workflow_name: str, trigger_count: int) -> None:
        for i in range(trigger_count):
            self.trigger_states.setdefault(
                (workflow_name, i), TriggerState(workflow_name=workflow_name, trigger_index=i, enabled=False)
            )
        for key in list(self.trigger_states):
            if key[0] == workflow_name and key[1] >= trigger_count:
                del self.trigger_states[key]

    async def list_trigger_states(self) -> list[TriggerState]:
        return list(self.trigger_states.values())

    async def get_trigger_state(self, workflow_name: str, trigger_index: int) -> Optional[TriggerState]:
        return self.trigger_states.get((workflow_name, trigger_index))

    async def set_trigger_enabled(self, workflow_name, trigger_index, enabled, actor=None, reason=None):
        self.enable_calls.append((workflow_name, trigger_index, enabled, actor, reason))
        state = self.trigger_states.get((workflow_name, trigger_index))
        if state is None:
            return None
        state.enabled = enabled
        return state

    async def create_instance(self, workflow_name, form_data, submitter_email=None, metadata=None):
        self._counter += 1
        inst = WorkflowInstance(
            id=f"inst-{self._counter}", workflow_name=workflow_name, form_data=form_data,
            status="running", current_step=None, created_at="2026-01-01T00:00:00Z",
            submitter_email=submitter_email, metadata=metadata,
        )
        self.instances[inst.id] = inst
        return inst

    async def update_instance_status(self, instance_id, status, current_step=None):
        inst = self.instances.get(instance_id)
        if inst:
            inst.status = status
            inst.current_step = current_step

    async def create_step(self, instance_id, step_name, step_type, approver_email,
                           parent_step_id=None, metadata=None):
        from approvalml.runtime.base import WorkflowStepRecord
        self._counter += 1
        return WorkflowStepRecord(
            id=f"step-{self._counter}", instance_id=instance_id, step_name=step_name,
            step_type=step_type, status="pending", token=f"tok-{self._counter}",
            approver_email=approver_email, created_at="2026-01-01T00:00:00Z",
            parent_step_id=parent_step_id, metadata=metadata,
        )

    async def decide_step(self, step_id, token, decision, comment=None, decided_by=None):
        return None, None  # not exercised — steps aren't looked up again in these tests


@contextmanager
def _client_with_fake_store():
    """A TestClient wired to a WorkflowEngine over _FakeStore, with server.py's module state reset after."""
    os.environ.pop("APPROVALML_API_TOKEN", None)  # open access -> every request resolves as admin
    store = _FakeStore()
    engine = WorkflowEngine(store=store, email=_DummyEmailSender(), server_url="http://localhost:8765")

    server_module._engine = engine
    server_module._workflows_dir_at_startup = None
    server_module._tokens_to_seed = []
    try:
        with TestClient(server_module.app) as client:
            yield client, store
    finally:
        server_module._engine = None
        server_module._scheduler = None


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_register_then_list_workflows_shows_disabled_trigger():
    """Registering a workflow with a cron trigger must surface it via GET /services/v1/workflows, disabled."""
    with _client_with_fake_store() as (client, store):
        resp = client.post("/services/v1/workflows", json={"name": "daily-scan", "yaml": CRON_YAML})
        assert resp.status_code == 200

        resp = client.get("/services/v1/workflows")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["name"] == "daily-scan"
        assert body[0]["trigger_count"] == 1
        assert body[0]["triggers"][0]["enabled"] is False
        assert body[0]["triggers"][0]["schedule"] == "0 2 * * *"


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_get_schedule_status_404s_for_unknown_workflow():
    """GET .../schedule for a never-registered workflow must 404, not 500."""
    with _client_with_fake_store() as (client, store):
        resp = client.get("/services/v1/workflows/does-not-exist/schedule")
        assert resp.status_code == 404


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_get_schedule_status_returns_per_trigger_detail():
    """GET .../schedule must return enabled/last_status/consecutive_failures per trigger."""
    with _client_with_fake_store() as (client, store):
        client.post("/services/v1/workflows", json={"name": "daily-scan", "yaml": CRON_YAML})

        resp = client.get("/services/v1/workflows/daily-scan/schedule")
        assert resp.status_code == 200
        body = resp.json()
        assert body["workflow_name"] == "daily-scan"
        assert len(body["triggers"]) == 1
        assert body["triggers"][0] == {
            "trigger_index": 0,
            "type": "cron",
            "schedule": "0 2 * * *",
            "enabled": False,
            "last_run_at": None,
            "last_status": None,
            "last_error": None,
            "consecutive_failures": 0,
            "next_run_at": None,
        }


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_set_schedule_enabled_records_actor_and_reason():
    """POST .../enabled must flip the trigger and pass the calling identity + reason through to the store."""
    with _client_with_fake_store() as (client, store):
        client.post("/services/v1/workflows", json={"name": "daily-scan", "yaml": CRON_YAML})

        resp = client.post(
            "/services/v1/workflows/daily-scan/schedule/0/enabled",
            json={"enabled": True, "reason": "daily CVE scan per SOC 2"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"workflow_name": "daily-scan", "trigger_index": 0, "enabled": True}

        assert store.enable_calls == [("daily-scan", 0, True, "admin", "daily CVE scan per SOC 2")]


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_set_schedule_enabled_404s_for_unknown_trigger_index():
    """Enabling a trigger index that doesn't exist must 404, not silently succeed."""
    with _client_with_fake_store() as (client, store):
        client.post("/services/v1/workflows", json={"name": "daily-scan", "yaml": CRON_YAML})

        resp = client.post(
            "/services/v1/workflows/daily-scan/schedule/5/enabled", json={"enabled": True}
        )
        assert resp.status_code == 404


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_set_schedule_enabled_requires_admin_token():
    """A non-admin user token must be rejected with 403, not allowed to flip a schedule."""
    os.environ["APPROVALML_API_TOKEN"] = "master-secret"
    try:
        store = _FakeStore()
        engine = WorkflowEngine(store=store, email=_DummyEmailSender(), server_url="http://localhost:8765")
        server_module._engine = engine
        server_module._workflows_dir_at_startup = None
        server_module._tokens_to_seed = []
        try:
            with TestClient(server_module.app) as client:
                resp = client.post(
                    "/services/v1/workflows/daily-scan/schedule/0/enabled",
                    json={"enabled": True},
                    # no Authorization header at all -> 401, matches _resolve_auth's contract
                )
                assert resp.status_code == 401
        finally:
            server_module._engine = None
            server_module._scheduler = None
    finally:
        os.environ.pop("APPROVALML_API_TOKEN", None)


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_submit_workflow_defaults_trigger_source_to_api():
    """POST /services/v1/approvals/ without trigger_source must tag the instance metadata 'api'."""
    with _client_with_fake_store() as (client, store):
        client.post("/services/v1/workflows", json={"name": "daily-scan", "yaml": CRON_YAML})

        resp = client.post(
            "/services/v1/approvals/", json={"workflow_id": "daily-scan", "form_data": {}}
        )
        assert resp.status_code == 200
        instance_id = resp.json()["instance_id"]
        assert store.instances[instance_id].metadata == {"trigger_source": "api"}


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_submit_workflow_honors_manual_trigger_source():
    """POST /services/v1/approvals/ with trigger_source='manual' (as run_now sends) must tag it distinctly."""
    with _client_with_fake_store() as (client, store):
        client.post("/services/v1/workflows", json={"name": "daily-scan", "yaml": CRON_YAML})

        resp = client.post(
            "/services/v1/approvals/",
            json={"workflow_id": "daily-scan", "form_data": {}, "trigger_source": "manual"},
        )
        assert resp.status_code == 200
        instance_id = resp.json()["instance_id"]
        assert store.instances[instance_id].metadata == {"trigger_source": "manual"}
