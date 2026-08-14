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
class TriggerState:
    """
    Governed enable/disable + run-history state for one cron/one_time trigger
    within a workflow's `triggers:` list. Identity is (workflow_name,
    trigger_index) — the trigger's position in the YAML, since TriggerConfig
    itself carries no stable id. Always created disabled (see
    WorkflowStore.sync_trigger_states); arming it is a separate, audited act.
    """
    workflow_name: str
    trigger_index: int
    enabled: bool
    last_run_at: Optional[str] = field(default=None)
    last_status: Optional[str] = field(default=None)   # 'success' | 'failed' | None (never fired)
    last_error: Optional[str] = field(default=None)
    consecutive_failures: int = 0
    next_run_at: Optional[str] = field(default=None)
    updated_at: Optional[str] = field(default=None)


@dataclass
class WorkflowStepRecord:
    """A single step execution within a workflow instance."""
    id: str
    instance_id: str
    step_name: str
    step_type: str
    status: str                       # pending | approved | rejected | skipped | completed | failed
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

    @abstractmethod
    async def list_workflow_names(self) -> list[str]:
        """Return every registered workflow name."""

    # ── Workflow instances ─────────────────────────────────────────────────────

    @abstractmethod
    async def create_instance(
        self,
        workflow_name: str,
        form_data: dict[str, Any],
        submitter_email: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> WorkflowInstance:
        """
        Create a new workflow run in 'running' state. `metadata` should carry
        `trigger_source` ('api' | 'scheduler' | 'manual') so instances created
        by the WorkflowScheduler, an explicit run_now override, and a normal
        submission are distinguishable in the audit trail.
        """

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

    @abstractmethod
    async def merge_instance_form_data(self, instance_id: str, updates: dict[str, Any]) -> None:
        """
        Merge `updates` into the instance's stored form_data (e.g. an
        `automatic` step's `save_to` result), so later steps or a resumed
        decision see it even after the request that produced it has returned.
        """

    @abstractmethod
    async def has_running_instance_for_trigger(self, workflow_name: str, trigger_index: int) -> bool:
        """
        True if a scheduler-created instance for this trigger is still
        'running'. Used to honor TriggerConfig.allow_concurrent (default
        False — skip a tick rather than overlap with a still-running run).
        """

    # ── Scheduled trigger state (governed enable/disable) ───────────────────────

    @abstractmethod
    async def sync_trigger_states(self, workflow_name: str, trigger_count: int) -> None:
        """
        Ensure exactly `trigger_count` TriggerState rows exist for this
        workflow, each starting disabled. Called on every register_workflow
        so a re-registered YAML's triggers are always represented, and any
        trigger removed from the YAML has its row (and governance history)
        removed too. Never flips an existing row's enabled state.
        """

    @abstractmethod
    async def list_trigger_states(self) -> list[TriggerState]:
        """Return every trigger_state row across all workflows — the scheduler's tick source."""

    @abstractmethod
    async def get_trigger_state(self, workflow_name: str, trigger_index: int) -> Optional[TriggerState]:
        """Return one trigger's state, or None if it doesn't exist."""

    @abstractmethod
    async def set_trigger_enabled(
        self,
        workflow_name: str,
        trigger_index: int,
        enabled: bool,
        actor: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Optional[TriggerState]:
        """
        Governed toggle — the only way a trigger's enabled bit changes short
        of auto-disable. Always appends an audit_log entry with actor+reason.
        Returns None if the trigger doesn't exist.
        """

    @abstractmethod
    async def set_trigger_next_run(
        self, workflow_name: str, trigger_index: int, next_run_at: Optional[str]
    ) -> None:
        """
        Set next_run_at without touching status/failure counters — used to
        arm a freshly enabled trigger's clock on the scheduler's first tick
        after enable, without counting that tick as a firing.
        """

    @abstractmethod
    async def record_trigger_run(
        self,
        workflow_name: str,
        trigger_index: int,
        *,
        success: bool,
        error: Optional[str],
        next_run_at: Optional[str],
    ) -> TriggerState:
        """
        Record one scheduler firing's outcome. Resets consecutive_failures to
        0 on success; increments it on failure. Also appended to the audit
        log — a tick that never happens (process down) is a silent absence,
        but every tick that *does* happen, succeed or fail, is recorded here.
        """

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


class NotificationBackend(ABC):
    """
    Multi-channel notification backend for `type: notification` workflow steps.

    Implementations receive a channel slug, a recipient handle, and a channel-
    agnostic message dict. They are responsible for resolving credentials and
    delivering the message. The backend must not raise for delivery failures;
    it should return (success, error_message_or_none).

    The standalone runtime provides `EnvNotificationBackend` which reads channel
    credentials from environment variables. The SaaS backend provides its own
    implementation that looks up per-employee preferences and company-scoped
    credentials.
    """

    @abstractmethod
    async def send(
        self,
        *,
        channel: str,
        recipient: str,
        message: dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """
        Send one notification.

        Args:
            channel: Channel slug, e.g. 'email', 'slack'.
            recipient: Channel-specific recipient handle (email address, channel
                name, user id, webhook URL, etc.).
            message: Dict with at least 'subject' and 'body'. May include
                'text_body', 'action_url', and 'context'.

        Returns:
            (success, error_message). error_message is None on success.
        """
        pass
