"""
Tests for the standalone notification backend and workflow notification steps.

Run with: pytest tests/test_notification_backend.py -v
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest

from approvalml.runtime.base import (
    NotificationBackend,
    WorkflowInstance,
    WorkflowStepRecord,
)
from approvalml.runtime.workflow_engine import WorkflowEngine


class _DummyEmailSender:
    def send_approval_request(
        self,
        to_email: str,
        description: str,
        approve_url: str,
        reject_url: str,
        context: Optional[dict] = None,
    ) -> None:
        pass


class _CapturingNotificationBackend(NotificationBackend):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def send(
        self,
        *,
        channel: str,
        recipient: str,
        message: dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        self.calls.append((channel, recipient, message))
        return True, None


class _MemoryWorkflowStore:
    def __init__(self) -> None:
        self.workflows: dict[str, str] = {}
        self.instances: dict[str, WorkflowInstance] = {}
        self.steps: list[WorkflowStepRecord] = []
        self._step_counter = 0
        self._instance_counter = 0

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def upsert_workflow(self, name: str, yaml_content: str) -> None:
        self.workflows[name] = yaml_content

    async def get_workflow_yaml(self, name: str) -> Optional[str]:
        return self.workflows.get(name)

    async def create_instance(
        self,
        workflow_name: str,
        form_data: dict[str, Any],
        submitter_email: Optional[str] = None,
    ) -> WorkflowInstance:
        self._instance_counter += 1
        inst = WorkflowInstance(
            id=f"inst-{self._instance_counter}",
            workflow_name=workflow_name,
            form_data=form_data,
            status="running",
            current_step=None,
            created_at="2026-01-01T00:00:00Z",
            submitter_email=submitter_email,
        )
        self.instances[inst.id] = inst
        return inst

    async def get_instance(self, instance_id: str) -> Optional[WorkflowInstance]:
        return self.instances.get(instance_id)

    async def update_instance_status(
        self,
        instance_id: str,
        status: str,
        current_step: Optional[str] = None,
    ) -> None:
        inst = self.instances.get(instance_id)
        if inst:
            inst.status = status
            inst.current_step = current_step

    async def create_step(
        self,
        instance_id: str,
        step_name: str,
        step_type: str,
        approver_email: Optional[str],
        parent_step_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> WorkflowStepRecord:
        self._step_counter += 1
        step = WorkflowStepRecord(
            id=f"step-{self._step_counter}",
            instance_id=instance_id,
            step_name=step_name,
            step_type=step_type,
            status="pending",
            token=f"token-{self._step_counter}",
            approver_email=approver_email,
            created_at="2026-01-01T00:00:00Z",
            parent_step_id=parent_step_id,
            metadata=metadata,
        )
        self.steps.append(step)
        return step

    async def get_step(self, step_id: str) -> Optional[WorkflowStepRecord]:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    async def decide_step(
        self,
        step_id: str,
        token: str,
        decision: str,
        comment: Optional[str] = None,
        decided_by: Optional[str] = None,
    ) -> tuple[Optional[WorkflowStepRecord], Optional[str]]:
        step = await self.get_step(step_id)
        if step is None:
            return None, "Step not found"
        step.status = decision
        step.decided_by = decided_by
        step.comment = comment
        return step, None

    async def get_steps_for_instance(self, instance_id: str) -> list[WorkflowStepRecord]:
        return [s for s in self.steps if s.instance_id == instance_id]

    async def get_child_steps(self, parent_step_id: str) -> list[WorkflowStepRecord]:
        return [s for s in self.steps if s.parent_step_id == parent_step_id]


def test_notification_step_dispatches_to_backend():
    """A type: notification step must call the injected backend for each recipient."""
    store = _MemoryWorkflowStore()
    backend = _CapturingNotificationBackend()
    engine = WorkflowEngine(
        store=store,
        email=_DummyEmailSender(),
        server_url="http://localhost:8765",
        notification_backend=backend,
    )

    yaml = """
name: Notify Test
form:
  note:
    type: text
    label: Note
    required: false
workflow:
  notify:
    name: notify
    type: notification
    recipients:
      - channel: slack
        to: "#approvals"
      - channel: email
        to: "user@example.com"
    notification:
      message:
        subject: "Request received"
        body: "Your request has been received."
    on_complete:
      continue_to: end
  end:
    name: end
    type: end
"""

    async def _run():
        await engine.register_workflow("notify_test", yaml)
        return await engine.submit_workflow("notify_test", {"note": "hello"})

    result = asyncio.run(_run())
    assert result["status"] == "running"
    assert len(backend.calls) == 2

    channels = [call[0] for call in backend.calls]
    recipients = [call[1] for call in backend.calls]
    assert "slack" in channels
    assert "email" in channels
    assert "#approvals" in recipients
    assert "user@example.com" in recipients

    for _, _, message in backend.calls:
        assert message["subject"] == "Request received"
        assert "request has been received" in message["body"]


def test_notification_step_falls_back_to_default_email_channel():
    """Recipients without an explicit channel default to email."""
    store = _MemoryWorkflowStore()
    backend = _CapturingNotificationBackend()
    engine = WorkflowEngine(
        store=store,
        email=_DummyEmailSender(),
        server_url="http://localhost:8765",
        notification_backend=backend,
    )

    yaml = """
name: Email Fallback Test
form:
  note:
    type: text
    label: Note
    required: false
workflow:
  notify:
    name: notify
    type: notification
    recipients:
      - email: "fallback@example.com"
    notification:
      message:
        subject: "Hello"
        body: "World"
    on_complete:
      continue_to: end
  end:
    name: end
    type: end
"""

    async def _run():
        await engine.register_workflow("email_fallback", yaml)
        return await engine.submit_workflow("email_fallback", {})

    asyncio.run(_run())
    assert len(backend.calls) == 1
    assert backend.calls[0][0] == "email"
    assert backend.calls[0][1] == "fallback@example.com"


def test_env_notification_backend_reads_slack_credentials(monkeypatch):
    """EnvNotificationBackend must build the Slack config from environment variables."""
    from approvalml.runtime.env_notifications import EnvNotificationBackend

    monkeypatch.setenv("APPROVALML_NOTIFICATION_SLACK_BOT_TOKEN", "xoxb-test-token")
    backend = EnvNotificationBackend()
    config = backend._channel_config("slack", "#approvals")

    assert config is not None
    assert config["bot_token"] == "xoxb-test-token"
    assert config["channel"] == "#approvals"


def test_env_notification_backend_skips_unconfigured_channel():
    """EnvNotificationBackend must report an error when credentials are missing."""
    from approvalml.runtime.env_notifications import EnvNotificationBackend

    backend = EnvNotificationBackend()
    config = backend._channel_config("teams", "ignored")
    assert config is None
