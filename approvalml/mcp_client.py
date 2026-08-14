"""HTTP client for the ApprovalML REST API.

Configure via environment variables:
  APPROVALML_API_URL   - base URL of the ApprovalML backend  (default: http://localhost:8000)
  APPROVALML_API_TOKEN - bearer token for authentication
"""

import os
from typing import Any, Optional

import httpx


class ApprovalMLClient:
    def __init__(
        self,
        api_url: Optional[str] = None,
        api_token: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.base_url = (api_url or os.environ.get("APPROVALML_API_URL", "http://localhost:8765")).rstrip("/")
        self.token = api_token or os.environ.get("APPROVALML_API_TOKEN", "")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request_approval(
        self,
        description: str,
        approver_email: str,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Submit a single-step approval gate. Returns { instance_id, status }."""
        payload: dict[str, Any] = {
            "description": description,
            "approver_email": approver_email,
        }
        if context:
            payload["context"] = context

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/services/v1/approvals/gate",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def check_approval_status(self, instance_id: str) -> dict[str, Any]:
        """Return current status of an approval instance."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{self.base_url}/services/v1/approvals/{instance_id}/status",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def list_pending_approvals(self) -> list[dict[str, Any]]:
        """Return approval instances that are still pending."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{self.base_url}/services/v1/approvals/pending",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def submit_workflow(
        self,
        workflow_id: int,
        form_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit a full named workflow (for advanced use cases)."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/services/v1/approvals/",
                json={"workflow_id": workflow_id, "form_data": form_data},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def get_workflow_status(self, instance_id: str) -> dict[str, Any]:
        """Return full status of a workflow instance, including all steps."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{self.base_url}/services/v1/approvals/{instance_id}/workflow",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def register_workflow(self, name: str, yaml_content: str) -> dict[str, Any]:
        """Register (or replace) a workflow YAML definition by name. Admin token required."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/services/v1/workflows",
                json={"name": name, "yaml": yaml_content},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def list_workflows(self) -> list[dict[str, Any]]:
        """Return every registered workflow with a summary of its scheduled triggers, if any."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(f"{self.base_url}/services/v1/workflows", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    def get_schedule_status(self, workflow_name: str) -> dict[str, Any]:
        """Return per-trigger schedule state (enabled, next_run, last_status, failures) for one workflow."""
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{self.base_url}/services/v1/workflows/{workflow_name}/schedule",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def set_schedule_enabled(
        self,
        workflow_name: str,
        trigger_index: int,
        enabled: bool,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Governed enable/disable of one cron/one_time trigger. Admin token required.

        This is a management-plane configuration change, not a tick — the
        WorkflowScheduler inside the runtime owns every subsequent firing.
        Recorded to the audit log with the calling actor and reason.
        """
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/services/v1/workflows/{workflow_name}/schedule/{trigger_index}/enabled",
                json={"enabled": enabled, "reason": reason},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def run_now(self, workflow_name: str, form_data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """
        Explicit, recorded manual submission of a (typically scheduled) workflow —
        distinct from a scheduler tick. Tagged trigger_source='manual' in the
        instance's audit trail so it's never confused with an automated run.
        """
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/services/v1/approvals/",
                json={
                    "workflow_id": workflow_name,
                    "form_data": form_data or {},
                    "trigger_source": "manual",
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
