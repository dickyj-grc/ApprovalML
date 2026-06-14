"""
Abstract base classes for the ApprovalML runtime.

Both the lightweight standalone implementation (postgres_store.py / email_smtp.py)
and the full SaaS backend (src/app/) can implement these interfaces, enabling
code sharing via the ApprovalEngine without coupling the two deployments.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ApprovalGate:
    """Single approval request and its current state."""
    id: str
    description: str
    approver_email: str
    status: str                       # pending | approved | rejected
    token: str                        # secret embedded in email links
    created_at: str                   # ISO-8601
    context: Optional[dict[str, Any]] = field(default=None)
    decided_at: Optional[str] = field(default=None)
    decided_by: Optional[str] = field(default=None)
    comment: Optional[str] = field(default=None)
    submitter_email: Optional[str] = field(default=None)


@dataclass
class UserToken:
    """An API token bound to a user email."""
    token: str
    email: str
    name: Optional[str]
    created_at: str


@dataclass
class WorkflowInstance:
    """A running instance of a named workflow."""
    id: str
    workflow_name: str
    form_data: dict[str, Any]
    status: str                       # running | completed | rejected | error
    current_step: Optional[str]       # step name currently active
    created_at: str
    completed_at: Optional[str] = field(default=None)
    metadata: Optional[dict[str, Any]] = field(default=None)
    submitter_email: Optional[str] = field(default=None)


@dataclass
class WorkflowStepRecord:
    """A single step execution within a workflow instance."""
    id: str
    instance_id: str
    step_name: str
    step_type: str
    status: str                       # pending | approved | rejected | skipped | completed
    token: str                        # secret for email decision links
    approver_email: Optional[str]
    created_at: str
    decided_at: Optional[str] = field(default=None)
    decided_by: Optional[str] = field(default=None)
    comment: Optional[str] = field(default=None)
    parent_step_id: Optional[str] = field(default=None)
    metadata: Optional[dict[str, Any]] = field(default=None)


class ApprovalStore(ABC):
    """Storage backend for approval gates — implement per deployment target."""

    @abstractmethod
    async def initialize(self) -> None:
        """Create schema / run migrations. Called once at server startup."""

    @abstractmethod
    async def create_gate(
        self,
        description: str,
        approver_email: str,
        context: Optional[dict[str, Any]] = None,
        submitter_email: Optional[str] = None,
    ) -> ApprovalGate:
        """Persist a new gate in 'pending' state and return it."""

    @abstractmethod
    async def get_gate(self, gate_id: str) -> Optional[ApprovalGate]:
        """Return the gate or None if not found."""

    @abstractmethod
    async def decide_gate(
        self,
        gate_id: str,
        token: str,
        decision: str,
        comment: Optional[str] = None,
        decided_by: Optional[str] = None,
    ) -> tuple[Optional[ApprovalGate], Optional[str]]:
        """Record approve/reject. Returns (updated_gate, None) or (None, error_message)."""

    @abstractmethod
    async def list_pending(self) -> list[ApprovalGate]:
        """Return all gates whose status is 'pending', newest first."""

    async def close(self) -> None:
        """Release resources (connection pool, etc.). Override when needed."""


class WorkflowStore(ApprovalStore):
    """Extended storage interface that adds full workflow instance/step tracking."""

    # ── Workflow definitions ───────────────────────────────────────────────────

    @abstractmethod
    async def upsert_workflow(self, name: str, yaml_content: str) -> None:
        """Store or replace a workflow YAML by name."""

    @abstractmethod
    async def get_workflow_yaml(self, name: str) -> Optional[str]:
        """Return the stored YAML for a workflow, or None if not found."""

    # ── Workflow instances ─────────────────────────────────────────────────────

    @abstractmethod
    async def create_instance(
        self,
        workflow_name: str,
        form_data: dict[str, Any],
        submitter_email: Optional[str] = None,
    ) -> WorkflowInstance:
        """Create a new workflow run in 'running' state."""

    @abstractmethod
    async def get_instance(self, instance_id: str) -> Optional[WorkflowInstance]:
        """Return a workflow instance or None."""

    @abstractmethod
    async def update_instance_status(
        self,
        instance_id: str,
        status: str,
        current_step: Optional[str] = None,
    ) -> None:
        """Update the running status and active step name."""

    # ── Workflow steps ─────────────────────────────────────────────────────────

    @abstractmethod
    async def create_step(
        self,
        instance_id: str,
        step_name: str,
        step_type: str,
        approver_email: Optional[str],
        parent_step_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> WorkflowStepRecord:
        """Create a pending step record and return it."""

    @abstractmethod
    async def get_step(self, step_id: str) -> Optional[WorkflowStepRecord]:
        """Return a step record or None."""

    @abstractmethod
    async def decide_step(
        self,
        step_id: str,
        token: str,
        decision: str,
        comment: Optional[str] = None,
        decided_by: Optional[str] = None,
    ) -> tuple[Optional[WorkflowStepRecord], Optional[str]]:
        """Record approve/reject on a step. Returns (step, None) or (None, error)."""

    @abstractmethod
    async def get_steps_for_instance(self, instance_id: str) -> list[WorkflowStepRecord]:
        """Return all step records for an instance."""

    @abstractmethod
    async def get_child_steps(self, parent_step_id: str) -> list[WorkflowStepRecord]:
        """Return all child steps under a parallel-approval parent."""

    # ── API token management ───────────────────────────────────────────────────

    @abstractmethod
    async def create_token(self, email: str, name: Optional[str] = None) -> UserToken:
        """Generate and store a new API token bound to an email. Returns the token."""

    @abstractmethod
    async def resolve_token(self, token: str) -> Optional[UserToken]:
        """Look up a token in the store. Returns None if not found."""

    @abstractmethod
    async def list_tokens(self) -> list[UserToken]:
        """Return all registered user tokens (tokens are masked)."""

    @abstractmethod
    async def revoke_token(self, token: str) -> bool:
        """Delete a token. Returns True if it existed, False otherwise."""


class EmailSender(ABC):
    """Email delivery backend — implement per deployment target."""

    @abstractmethod
    def send_approval_request(
        self,
        to_email: str,
        description: str,
        approve_url: str,
        reject_url: str,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        """Send the approval-request email. Must not raise — log and continue on failure."""
