"""
ApprovalEngine — orchestrates ApprovalStore + EmailSender.

This is the only place where the two abstractions are combined into
business logic: create a gate, send the email, return the instance_id.
Both the standalone runtime and the SaaS backend share this class.
"""

from __future__ import annotations

from typing import Any, Optional

from .base import ApprovalStore, EmailSender, ApprovalGate


class ApprovalEngine:
    def __init__(
        self,
        store: ApprovalStore,
        email: EmailSender,
        server_url: str,
    ) -> None:
        self.store = store
        self.email = email
        self.server_url = server_url.rstrip("/")

    def _decision_urls(self, gate_id: str, token: str) -> tuple[str, str]:
        base = f"{self.server_url}/decide/{gate_id}"
        return (
            f"{base}/approve?token={token}",
            f"{base}/reject?token={token}",
        )

    async def request_gate(
        self,
        description: str,
        approver_email: str,
        context: Optional[dict[str, Any]] = None,
        submitter_email: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create an approval gate, send email, return {instance_id, status}."""
        gate = await self.store.create_gate(description, approver_email, context, submitter_email)
        approve_url, reject_url = self._decision_urls(gate.id, gate.token)
        self.email.send_approval_request(
            approver_email, description, approve_url, reject_url, context
        )
        return {"instance_id": gate.id, "status": gate.status}

    async def get_status(self, gate_id: str) -> Optional[dict[str, Any]]:
        """Return status dict or None if not found."""
        gate = await self.store.get_gate(gate_id)
        if gate is None:
            return None
        return {
            "instance_id": gate.id,
            "status": gate.status,
            "decided_by": gate.decided_by,
            "comment": gate.comment,
            "decided_at": gate.decided_at,
            "submitter_email": gate.submitter_email,
        }

    async def list_pending(self) -> list[dict[str, Any]]:
        """Return simplified list of pending gates."""
        gates = await self.store.list_pending()
        return [
            {
                "instance_id": g.id,
                "description": g.description,
                "approver_email": g.approver_email,
                "submitter_email": g.submitter_email,
                "submitted_at": g.created_at,
            }
            for g in gates
        ]

    async def decide(
        self,
        gate_id: str,
        token: str,
        decision: str,
        comment: Optional[str] = None,
        decided_by: Optional[str] = None,
    ) -> tuple[Optional[ApprovalGate], Optional[str]]:
        """Record an approve/reject decision. Returns (gate, None) or (None, error)."""
        return await self.store.decide_gate(gate_id, token, decision, comment, decided_by)
