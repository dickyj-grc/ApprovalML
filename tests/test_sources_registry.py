"""
Unit tests for the standalone runtime's `sources:` registry and the
`automatic` step executor (WorkflowEngine._execute_automatic_step) — the
YAML-resolvable stand-in for Aptiwise SaaS's data_connectors/data_sources.

Run with: pytest tests/test_sources_registry.py -v
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from approvalml.runtime.base import WorkflowInstance, WorkflowStepRecord
from approvalml.runtime.workflow_engine import WorkflowEngine, WorkflowError

AUTOMATIC_YAML = """
name: Match PO
sources:
  vendor_po:
    connector:
      type: rest_api
      base_url: "http://vendor.example.com"
      auth: { type: bearer, token: "secret-token" }
    source:
      endpoint: "/pos/123"
      method: GET
form:
  po_number:
    type: text
    label: PO Number
    required: false
workflow:
  match_po:
    name: match_po
    type: automatic
    data_processor:
      source_name: vendor_po
      save_to: po
      params:
        - name: po_id
          from_field: field.po_number
    on_complete:
      continue_to: done
    on_failure:
      continue_to: failed
  done:
    name: done
    type: end
  failed:
    name: failed
    type: end
    metadata:
      outcome: rejected
"""

ENV_TOKEN_YAML = """
name: Match PO
sources:
  vendor_po:
    connector:
      type: rest_api
      base_url: "http://vendor.example.com"
      auth: { type: bearer, token: "${env.VENDOR_TOKEN}" }
    source:
      endpoint: "/pos/123"
      method: GET
form:
  po_number:
    type: text
    label: PO Number
    required: false
workflow:
  match_po:
    name: match_po
    type: automatic
    data_processor:
      source_name: vendor_po
      save_to: po
    on_complete:
      continue_to: done
  done:
    name: done
    type: end
"""

NO_SOURCES_YAML = """
name: No Sources
form:
  note:
    type: text
    label: Note
    required: false
workflow:
  match_po:
    name: match_po
    type: automatic
    data_processor:
      source_name: vendor_po
      save_to: po
    on_complete:
      continue_to: done
  done:
    name: done
    type: end
"""


class _DummyEmailSender:
    def send_approval_request(self, *args, **kwargs) -> None:
        pass


class _MemoryStore:
    def __init__(self) -> None:
        self.workflows: dict[str, str] = {}
        self.instances: dict[str, WorkflowInstance] = {}
        self.steps: list[WorkflowStepRecord] = []
        self._counter = 0

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def upsert_workflow(self, name: str, yaml_content: str) -> None:
        self.workflows[name] = yaml_content

    async def get_workflow_yaml(self, name: str) -> Optional[str]:
        return self.workflows.get(name)

    async def sync_trigger_states(self, workflow_name: str, trigger_count: int) -> None:
        pass

    async def create_instance(self, workflow_name, form_data, submitter_email=None, metadata=None):
        self._counter += 1
        inst = WorkflowInstance(
            id=f"inst-{self._counter}", workflow_name=workflow_name, form_data=form_data,
            status="running", current_step=None, created_at="2026-01-01T00:00:00Z",
            submitter_email=submitter_email, metadata=metadata,
        )
        self.instances[inst.id] = inst
        return inst

    async def get_instance(self, instance_id):
        return self.instances.get(instance_id)

    async def update_instance_status(self, instance_id, status, current_step=None):
        inst = self.instances.get(instance_id)
        if inst:
            inst.status = status
            inst.current_step = current_step

    async def merge_instance_form_data(self, instance_id, updates):
        inst = self.instances.get(instance_id)
        if inst:
            inst.form_data = {**inst.form_data, **updates}

    async def create_step(self, instance_id, step_name, step_type, approver_email,
                           parent_step_id=None, metadata=None):
        self._counter += 1
        step = WorkflowStepRecord(
            id=f"step-{self._counter}", instance_id=instance_id, step_name=step_name,
            step_type=step_type, status="pending", token=f"tok-{self._counter}",
            approver_email=approver_email, created_at="2026-01-01T00:00:00Z",
            parent_step_id=parent_step_id, metadata=metadata,
        )
        self.steps.append(step)
        return step

    async def get_step(self, step_id):
        return next((s for s in self.steps if s.id == step_id), None)

    async def decide_step(self, step_id, token, decision, comment=None, decided_by=None):
        step = await self.get_step(step_id)
        step.status = decision
        step.comment = comment
        return step, None

    async def get_steps_for_instance(self, instance_id):
        return [s for s in self.steps if s.instance_id == instance_id]

    async def get_child_steps(self, parent_step_id):
        return [s for s in self.steps if s.parent_step_id == parent_step_id]


def _engine() -> WorkflowEngine:
    return WorkflowEngine(store=_MemoryStore(), email=_DummyEmailSender(), server_url="http://localhost:8765")


def _mock_httpx_client(json_body: dict[str, Any]):
    """Build a mock for `async with httpx.AsyncClient(...) as client: await client.get(...)`."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=json_body)

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.request = AsyncMock(return_value=mock_response)

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_client_cls, mock_client


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Sources Registry & Automatic Steps]]
def test_automatic_step_missing_source_raises_clear_error():
    """An automatic step whose source_name isn't in the workflow's sources: registry must raise WorkflowError."""
    engine = _engine()

    async def _run():
        await engine.register_workflow("no-sources", NO_SOURCES_YAML)
        await engine.submit_workflow("no-sources", {})

    with pytest.raises(WorkflowError, match="sources:"):
        asyncio.run(_run())


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Sources Registry & Automatic Steps]]
def test_automatic_step_calls_rest_api_and_saves_result():
    """A resolvable source_name must call the configured REST endpoint and merge save_to into form_data."""
    engine = _engine()
    mock_client_cls, mock_client = _mock_httpx_client({"po_id": "123", "status": "matched"})

    async def _run():
        await engine.register_workflow("match-po", AUTOMATIC_YAML)
        return await engine.submit_workflow("match-po", {"po_number": "PO-123"})

    with patch("httpx.AsyncClient", mock_client_cls):
        result = asyncio.run(_run())

    # Bearer auth header and param built from data_processor.params[].from_field
    call_kwargs = mock_client.get.call_args.kwargs
    assert call_kwargs["headers"]["Authorization"] == "Bearer secret-token"
    assert call_kwargs["params"] == {"po_id": "PO-123"}

    status = asyncio.run(engine.get_instance_status(result["instance_id"]))
    assert status["status"] == "completed"

    inst = engine.wstore.instances[result["instance_id"]]
    assert inst.form_data["po"] == {"po_id": "123", "status": "matched"}


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Sources Registry & Automatic Steps]]
def test_automatic_step_routes_to_on_failure_when_call_errors():
    """A failing REST call must route to on_failure.continue_to rather than hard-erroring the instance."""
    engine = _engine()
    mock_client_cls = MagicMock()
    mock_client_cls.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("connection refused"))

    async def _run():
        await engine.register_workflow("match-po", AUTOMATIC_YAML)
        return await engine.submit_workflow("match-po", {"po_number": "PO-123"})

    with patch("httpx.AsyncClient", mock_client_cls):
        result = asyncio.run(_run())

    status = asyncio.run(engine.get_instance_status(result["instance_id"]))
    assert status["status"] == "rejected"  # routed to the 'failed' end step (outcome: rejected)


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Sources Registry & Automatic Steps]]
def test_automatic_step_resolves_env_var_in_auth_token():
    """${env.VAR_NAME} in connector.auth.token must resolve from the process environment."""
    engine = _engine()
    mock_client_cls, mock_client = _mock_httpx_client({"status": "matched"})

    async def _run():
        await engine.register_workflow("match-po", ENV_TOKEN_YAML)
        return await engine.submit_workflow("match-po", {"po_number": "PO-123"})

    with patch.dict("os.environ", {"VENDOR_TOKEN": "env-resolved-secret"}), \
         patch("httpx.AsyncClient", mock_client_cls):
        result = asyncio.run(_run())

    call_kwargs = mock_client.get.call_args.kwargs
    assert call_kwargs["headers"]["Authorization"] == "Bearer env-resolved-secret"

    status = asyncio.run(engine.get_instance_status(result["instance_id"]))
    assert status["status"] == "completed"
