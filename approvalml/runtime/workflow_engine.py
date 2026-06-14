"""
WorkflowEngine — executes full ApprovalML YAML workflows.

Supported step types: decision, parallel_approval, conditional_split,
notification, end. Unsupported types (data_processor, spawn, automatic)
raise WorkflowError with a clear message.

Decision flow after a step resolves:
  - decision:           on_approve.continue_to  /  on_reject.continue_to
  - parallel_approval:  on_complete.continue_to when strategy satisfied,
                        on_reject.continue_to   when strategy failed early
  - conditional_split:  first matching choice continue_to / default
  - notification:       on_complete.continue_to
  - end:                marks instance completed / rejected
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .base import WorkflowStore, WorkflowInstance, WorkflowStepRecord, EmailSender
from .engine import ApprovalEngine

logger = logging.getLogger(__name__)


class WorkflowError(Exception):
    pass


class WorkflowEngine(ApprovalEngine):
    """Extends ApprovalEngine with YAML workflow execution."""

    def __init__(
        self,
        store: WorkflowStore,
        email: EmailSender,
        server_url: str,
    ) -> None:
        super().__init__(store, email, server_url)
        self.wstore = store  # typed reference for workflow-specific methods

    # ── Public API ─────────────────────────────────────────────────────────────

    async def register_workflow(self, name: str, yaml_content: str) -> dict[str, Any]:
        """Validate and store a workflow YAML. Returns {name, valid: True}."""
        from approvalml.parser import ApprovalMLParser
        parser = ApprovalMLParser()
        result = parser.parse_yaml(yaml_content)
        if result is None or parser.validation_errors:
            raise WorkflowError(f"Invalid workflow YAML: {'; '.join(parser.validation_errors)}")
        await self.wstore.upsert_workflow(name, yaml_content)
        return {"name": name, "valid": True}

    async def submit_workflow(
        self,
        workflow_name: str,
        form_data: dict[str, Any],
        submitter_email: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new workflow instance and advance to the first step."""
        yaml_content = await self.wstore.get_workflow_yaml(workflow_name)
        if yaml_content is None:
            raise WorkflowError(f"Workflow '{workflow_name}' not found")

        from approvalml.parser import ApprovalMLParser
        parser = ApprovalMLParser()
        parse_result = parser.parse_yaml(yaml_content)
        if parse_result is None:
            raise WorkflowError(f"Workflow '{workflow_name}' failed to parse: {'; '.join(parser.validation_errors)}")
        if not parse_result.workflow:
            raise WorkflowError(f"Workflow '{workflow_name}' has no steps")

        instance = await self.wstore.create_instance(workflow_name, form_data, submitter_email)
        await self._advance(instance, parse_result.workflow, form_data)
        return {"instance_id": instance.id, "status": "running"}

    async def get_instance_status(self, instance_id: str) -> Optional[dict[str, Any]]:
        """Return full status of a workflow instance."""
        inst = await self.wstore.get_instance(instance_id)
        if inst is None:
            return None
        steps = await self.wstore.get_steps_for_instance(instance_id)
        return {
            "instance_id": inst.id,
            "workflow_name": inst.workflow_name,
            "status": inst.status,
            "current_step": inst.current_step,
            "submitter_email": inst.submitter_email,
            "created_at": inst.created_at,
            "completed_at": inst.completed_at,
            "steps": [
                {
                    "id": s.id,
                    "step_name": s.step_name,
                    "step_type": s.step_type,
                    "status": s.status,
                    "approver_email": s.approver_email,
                    "decided_by": s.decided_by,
                    "comment": s.comment,
                    "decided_at": s.decided_at,
                }
                for s in steps
            ],
        }

    async def decide_workflow_step(
        self,
        step_id: str,
        token: str,
        decision: str,
        comment: Optional[str] = None,
        decided_by: Optional[str] = None,
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """Record a decision on a workflow step and advance the workflow."""
        step, err = await self.wstore.decide_step(step_id, token, decision, comment, decided_by)
        if err:
            return None, err

        inst = await self.wstore.get_instance(step.instance_id)
        if inst is None:
            return None, "Instance not found"

        yaml_content = await self.wstore.get_workflow_yaml(inst.workflow_name)
        if yaml_content is None:
            return None, f"Workflow definition '{inst.workflow_name}' missing"

        from approvalml.parser import ApprovalMLParser
        parser = ApprovalMLParser()
        parse_result = parser.parse_yaml(yaml_content)
        step_def = parse_result.workflow.get(step.step_name) if parse_result and parse_result.workflow else None

        if step_def is None:
            return None, f"Step definition '{step.step_name}' missing from workflow"

        await self._after_decision(inst, step, step_def, parse_result.workflow, inst.form_data)
        return {"step_id": step.id, "status": step.status}, None

    # ── Internal execution ─────────────────────────────────────────────────────

    async def _advance(
        self,
        instance: WorkflowInstance,
        workflow: dict,
        form_data: dict[str, Any],
    ) -> None:
        """Find and execute the first step of the workflow."""
        first_step_name = _find_entry_step(workflow)
        if first_step_name is None:
            await self.wstore.update_instance_status(instance.id, "error")
            raise WorkflowError("Could not determine workflow entry point")
        await self._execute_step(instance, first_step_name, workflow, form_data)

    async def _execute_step(
        self,
        instance: WorkflowInstance,
        step_name: str,
        workflow: dict,
        form_data: dict[str, Any],
        parent_step_id: Optional[str] = None,
    ) -> None:
        """Execute a single step by type."""
        step_def = workflow.get(step_name)
        if step_def is None:
            await self.wstore.update_instance_status(instance.id, "error")
            raise WorkflowError(f"Step '{step_name}' not found in workflow definition")

        step_type = step_def.type.value if hasattr(step_def.type, "value") else str(step_def.type)
        await self.wstore.update_instance_status(instance.id, "running", step_name)

        if step_type == "decision":
            await self._start_decision_step(instance, step_name, step_def, workflow, form_data)
        elif step_type == "parallel_approval":
            await self._start_parallel_step(instance, step_name, step_def, workflow, form_data)
        elif step_type == "conditional_split":
            await self._execute_conditional_step(instance, step_name, step_def, workflow, form_data)
        elif step_type == "notification":
            await self._execute_notification_step(instance, step_name, step_def, workflow, form_data)
        elif step_type == "end":
            await self._execute_end_step(instance, step_name, step_def)
        else:
            await self.wstore.update_instance_status(instance.id, "error")
            raise WorkflowError(
                f"Step type '{step_type}' is not supported in the standalone runtime. "
                "Supported types: decision, parallel_approval, conditional_split, notification, end."
            )

    # ── decision ───────────────────────────────────────────────────────────────

    async def _start_decision_step(
        self,
        instance: WorkflowInstance,
        step_name: str,
        step_def: Any,
        workflow: dict,
        form_data: dict[str, Any],
    ) -> None:
        approvers = _resolve_approvers(step_def, form_data)
        for approver_email in approvers:
            step_record = await self.wstore.create_step(
                instance.id, step_name, "decision", approver_email
            )
            approve_url, reject_url = self._step_decision_urls(step_record)
            desc = step_def.description or f"Approval required: {step_name}"
            self.email.send_approval_request(
                approver_email, desc, approve_url, reject_url,
                context={"form_data": form_data, "workflow": instance.workflow_name},
            )

    # ── parallel_approval ──────────────────────────────────────────────────────

    async def _start_parallel_step(
        self,
        instance: WorkflowInstance,
        step_name: str,
        step_def: Any,
        workflow: dict,
        form_data: dict[str, Any],
    ) -> None:
        strategy = (
            step_def.strategy.value
            if step_def.strategy and hasattr(step_def.strategy, "value")
            else "all"
        )
        approvers = _resolve_approvers(step_def, form_data)
        required = _required_for_strategy(strategy, len(approvers))

        # Create a parent "container" step to group child approvals under
        parent = await self.wstore.create_step(
            instance.id, step_name, "parallel_approval", None,
            metadata={
                "approval_strategy": strategy,
                "required_approvals": required,
                "total_approvers": len(approvers),
            },
        )

        for approver_email in approvers:
            child = await self.wstore.create_step(
                instance.id, step_name, "decision", approver_email,
                parent_step_id=parent.id,
            )
            approve_url, reject_url = self._step_decision_urls(child)
            desc = step_def.description or f"Parallel approval required: {step_name}"
            self.email.send_approval_request(
                approver_email, desc, approve_url, reject_url,
                context={"form_data": form_data, "workflow": instance.workflow_name},
            )

    # ── conditional_split ──────────────────────────────────────────────────────

    async def _execute_conditional_step(
        self,
        instance: WorkflowInstance,
        step_name: str,
        step_def: Any,
        workflow: dict,
        form_data: dict[str, Any],
    ) -> None:
        next_step = _evaluate_choices(step_def, form_data)
        # Record a completed step for audit trail
        step_record = await self.wstore.create_step(
            instance.id, step_name, "conditional_split", None,
            metadata={"resolved_to": next_step},
        )
        await self.wstore.decide_step(
            step_record.id, step_record.token, "completed",
            comment=f"Resolved to: {next_step}",
        )
        if next_step:
            await self._execute_step(instance, next_step, workflow, form_data)
        else:
            await self.wstore.update_instance_status(instance.id, "completed")

    # ── notification ───────────────────────────────────────────────────────────

    async def _execute_notification_step(
        self,
        instance: WorkflowInstance,
        step_name: str,
        step_def: Any,
        workflow: dict,
        form_data: dict[str, Any],
    ) -> None:
        recipients = _resolve_notification_recipients(step_def, form_data)
        msg = step_def.notification.message if step_def.notification else None

        for email_addr in recipients:
            if msg:
                self.email.send_approval_request(
                    email_addr,
                    msg.subject,
                    approve_url="",
                    reject_url="",
                    context={"body": msg.body, "form_data": form_data},
                )

        step_record = await self.wstore.create_step(
            instance.id, step_name, "notification", None,
        )
        await self.wstore.decide_step(step_record.id, step_record.token, "completed")

        next_step = _action_target(step_def.on_complete)
        if next_step:
            await self._execute_step(instance, next_step, workflow, form_data)
        else:
            await self.wstore.update_instance_status(instance.id, "completed")

    # ── end ────────────────────────────────────────────────────────────────────

    async def _execute_end_step(
        self,
        instance: WorkflowInstance,
        step_name: str,
        step_def: Any,
    ) -> None:
        metadata = step_def.metadata or {}
        outcome = metadata.get("outcome", "completed")
        final_status = "rejected" if outcome == "rejected" else "completed"

        step_record = await self.wstore.create_step(
            instance.id, step_name, "end", None,
            metadata={"outcome": outcome},
        )
        await self.wstore.decide_step(step_record.id, step_record.token, "completed")
        await self.wstore.update_instance_status(instance.id, final_status)

    # ── Post-decision routing ──────────────────────────────────────────────────

    async def _after_decision(
        self,
        instance: WorkflowInstance,
        step: WorkflowStepRecord,
        step_def: Any,
        workflow: dict,
        form_data: dict[str, Any],
    ) -> None:
        """Route workflow after a decision step resolves."""
        if step.parent_step_id:
            # This is a child of a parallel_approval — check if strategy is satisfied
            await self._check_parallel_completion(instance, step, step_def, workflow, form_data)
            return

        # Direct decision step
        if step.status == "approved":
            next_step = _action_target(step_def.on_approve)
        else:
            next_step = _action_target(step_def.on_reject)

        if next_step:
            await self._execute_step(instance, next_step, workflow, form_data)
        else:
            final = "completed" if step.status == "approved" else "rejected"
            await self.wstore.update_instance_status(instance.id, final)

    async def _check_parallel_completion(
        self,
        instance: WorkflowInstance,
        child_step: WorkflowStepRecord,
        step_def: Any,
        workflow: dict,
        form_data: dict[str, Any],
    ) -> None:
        """Evaluate parallel_approval strategy and advance workflow if resolved."""
        parent = await self.wstore.get_step(child_step.parent_step_id)
        if parent is None:
            return

        children = await self.wstore.get_child_steps(parent.id)
        meta = parent.metadata or {}
        strategy = meta.get("approval_strategy", "all")
        required = meta.get("required_approvals", len(children))
        total = meta.get("total_approvers", len(children))

        approved = sum(1 for c in children if c.status == "approved")
        rejected = sum(1 for c in children if c.status == "rejected")
        pending = sum(1 for c in children if c.status == "pending")

        outcome: Optional[str] = None

        if strategy == "all":
            if rejected > 0:
                outcome = "rejected"
            elif approved == total:
                outcome = "approved"
        elif strategy == "any_one":
            if approved >= 1:
                outcome = "approved"
            elif pending == 0:
                outcome = "rejected"
        elif strategy == "majority":
            if approved >= required:
                outcome = "approved"
            elif rejected > (total - required):
                outcome = "rejected"

        if outcome is None:
            return  # still waiting

        # Mark parent and remaining children as skipped
        pool = self.wstore._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE workflow_steps SET status=$1 WHERE parent_step_id=$2 AND status='pending'""",
                "skipped", parent.id,
            )
            await conn.execute(
                "UPDATE workflow_steps SET status=$1 WHERE id=$2",
                outcome, parent.id,
            )

        # Look up the parent step definition (parallel_approval step)
        parent_step_def = workflow.get(parent.step_name)
        if parent_step_def is None:
            await self.wstore.update_instance_status(instance.id, "error")
            return

        if outcome == "approved":
            next_step = _action_target(getattr(parent_step_def, "on_complete", None))
        else:
            next_step = _action_target(getattr(parent_step_def, "on_reject", None))

        if next_step:
            await self._execute_step(instance, next_step, workflow, form_data)
        else:
            final = "completed" if outcome == "approved" else "rejected"
            await self.wstore.update_instance_status(instance.id, final)

    # ── URL builders ──────────────────────────────────────────────────────────

    def _step_decision_urls(self, step: WorkflowStepRecord) -> tuple[str, str]:
        base = f"{self.server_url}/workflow-step/{step.id}"
        return (
            f"{base}/approve?token={step.token}",
            f"{base}/reject?token={step.token}",
        )


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _find_entry_step(workflow: dict) -> Optional[str]:
    """Return the name of the step that no other step points to (entry point)."""
    all_steps = set(workflow.keys())
    referenced: set[str] = set()

    for step_def in workflow.values():
        for action_attr in ("on_approve", "on_reject", "on_complete", "on_failure", "on_timeout"):
            action = getattr(step_def, action_attr, None)
            if action and action.continue_to:
                referenced.add(action.continue_to)
        if step_def.choices:
            for choice in step_def.choices:
                if isinstance(choice, dict) and "continue_to" in choice:
                    referenced.add(choice["continue_to"])
        if step_def.default and isinstance(step_def.default, dict) and "continue_to" in step_def.default:
            referenced.add(step_def.default["continue_to"])

    unreferenced = all_steps - referenced
    if len(unreferenced) == 1:
        return next(iter(unreferenced))
    # Multiple unreferenced steps — pick the one that isn't 'end' type as a heuristic
    non_end = [n for n in unreferenced if getattr(workflow[n], "type", None) and
               str(workflow[n].type.value if hasattr(workflow[n].type, "value") else workflow[n].type) != "end"]
    return next(iter(non_end)) if non_end else next(iter(unreferenced), None)


def _resolve_approvers(step_def: Any, form_data: dict[str, Any]) -> list[str]:
    """Extract approver email addresses from a step definition."""
    emails: list[str] = []

    # shorthand: approver: email@example.com
    if step_def.approver:
        raw = step_def.approver
        if isinstance(raw, str):
            emails.append(_resolve_template(raw, form_data))
        elif isinstance(raw, dict) and "email" in raw:
            emails.append(_resolve_template(raw["email"], form_data))

    # full list: approvers: [{approver: email}, ...]
    if step_def.approvers:
        for cfg in step_def.approvers:
            if cfg.approver:
                if isinstance(cfg.approver, str):
                    emails.append(_resolve_template(cfg.approver, form_data))
                elif hasattr(cfg.approver, "email"):
                    emails.append(_resolve_template(cfg.approver.email, form_data))
            elif cfg.dynamic_approver:
                resolved = _resolve_template(cfg.dynamic_approver, form_data)
                if resolved != cfg.dynamic_approver:  # successfully resolved
                    emails.append(resolved)

    return [e for e in emails if e and "@" in e]


def _resolve_template(tmpl: str, form_data: dict[str, Any]) -> str:
    """Replace ${form.field_name} with the value from form_data."""
    import re
    def replace(m: re.Match) -> str:
        path = m.group(1)
        parts = path.split(".")
        if len(parts) == 2 and parts[0] == "form":
            val = form_data.get(parts[1])
            return str(val) if val is not None else m.group(0)
        return m.group(0)
    return re.sub(r"\$\{([^}]+)\}", replace, tmpl)


def _required_for_strategy(strategy: str, total: int) -> int:
    if strategy == "any_one":
        return 1
    if strategy == "majority":
        return (total // 2) + 1
    return total  # "all"


def _action_target(action: Any) -> Optional[str]:
    """Return continue_to from an ActionConfig, or None."""
    if action is None:
        return None
    if action.end_workflow:
        return None
    return action.continue_to


def _evaluate_choices(step_def: Any, form_data: dict[str, Any]) -> Optional[str]:
    """Return the continue_to of the first matching choice, or default."""
    if step_def.choices:
        from approvalml.expression_evaluator import ConditionEvaluator, EvaluationContext
        ctx = EvaluationContext(
            form_data=form_data,
            workflow_variables={},
            requestor={},
            system={},
        )
        evaluator = ConditionEvaluator(ctx)
        for choice in step_def.choices:
            if not isinstance(choice, dict):
                continue
            conditions = choice.get("conditions", "")
            try:
                if evaluator.evaluate(conditions):
                    return choice.get("continue_to")
            except Exception:
                continue

    if step_def.default and isinstance(step_def.default, dict):
        return step_def.default.get("continue_to")

    return None


def _resolve_notification_recipients(step_def: Any, form_data: dict[str, Any]) -> list[str]:
    emails: list[str] = []
    if not step_def.recipients:
        return emails
    for r in step_def.recipients:
        if r.email:
            emails.append(_resolve_template(r.email, form_data))
    return [e for e in emails if e and "@" in e]
