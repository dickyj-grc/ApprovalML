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
        self.base_url = (api_url or os.environ.get("APPROVALML_API_URL", "http://localhost:8000")).rstrip("/")
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
