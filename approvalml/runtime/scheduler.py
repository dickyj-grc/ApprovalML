"""
WorkflowScheduler — the deterministic tick loop for cron-triggered workflows.

This is the only thing that fires a scheduled workflow. An agent (via the MCP
management-plane tools in mcp_server.py, or the equivalent REST endpoints in
server.py) may register a workflow, arm or disarm one of its triggers, run it
once manually, or observe its schedule status — but it never ticks a trigger
directly. There is deliberately no "fire this trigger now" tool: if an agent
were calling something on a cadence, the cadence guarantee — and the ability
to detect a missed tick — would be gone.

Lifecycle of one trigger:
  1. register_workflow() -> WorkflowStore.sync_trigger_states() creates a
     disabled trigger_state row for every cron/one_time trigger in the YAML.
  2. set_schedule_enabled(True) flips it on (governed — see server.py). Its
     next_run_at is still unset.
  3. The next tick sees enabled=True with no next_run_at and *arms* it —
     computes and stores the first upcoming cron occurrence without firing,
     so enabling a schedule never causes an immediate spurious run.
  4. Every tick thereafter fires it once now >= next_run_at, records the
     outcome (success/failed) to trigger_state + the audit log, and
     schedules the next occurrence.
  5. After max_consecutive_failures in a row, the trigger is auto-disabled
     and the reason is written to the audit log — the dangerous direction
     for an unattended control is "silently stuck on", not "stopped".
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from croniter import croniter

from .base import TriggerState
from .workflow_engine import WorkflowEngine

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 30.0
DEFAULT_MAX_CONSECUTIVE_FAILURES = 5


class WorkflowScheduler:
    def __init__(
        self,
        engine: WorkflowEngine,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    ) -> None:
        self.engine = engine
        self.poll_interval = poll_interval
        self.max_consecutive_failures = max_consecutive_failures
        self._last_tick_at: Optional[datetime] = None
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Start the background tick loop. Idempotent."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("WorkflowScheduler tick failed")
            await asyncio.sleep(self.poll_interval)

    async def tick(self) -> None:
        now = datetime.now(timezone.utc)
        if self._last_tick_at is not None:
            gap = (now - self._last_tick_at).total_seconds()
            if gap > self.poll_interval * 3:
                # The process itself was likely down or stalled across this
                # gap — any trigger due during it fires now rather than being
                # silently skipped, but the gap is worth surfacing on its own.
                logger.warning(
                    "WorkflowScheduler resumed after a %.0fs gap (expected ~%.0fs poll interval) "
                    "— triggers due during the gap will fire on this tick",
                    gap, self.poll_interval,
                )
        self._last_tick_at = now

        for state in await self.engine.wstore.list_trigger_states():
            if not state.enabled:
                continue
            try:
                await self._process_trigger(state, now)
            except Exception:
                logger.exception(
                    "Error processing trigger %s[%d]", state.workflow_name, state.trigger_index
                )

    async def _process_trigger(self, state: TriggerState, now: datetime) -> None:
        next_run = _parse_iso(state.next_run_at)

        if next_run is None:
            # Freshly enabled — arm the clock on this tick without firing.
            await self._arm(state, now)
            return

        if next_run > now:
            return

        await self._fire(state, now)

    async def _arm(self, state: TriggerState, now: datetime) -> None:
        trigger = await self._load_trigger(state)
        if trigger is None:
            return
        if trigger.type.value != "cron":
            return  # one_time/webhook triggers aren't ticked by this loop
        next_run_at = _next_cron_run(trigger.schedule, now)
        await self.engine.wstore.set_trigger_next_run(
            state.workflow_name, state.trigger_index, _iso(next_run_at)
        )
        logger.info(
            "Armed %s[%d] — next run at %s", state.workflow_name, state.trigger_index, _iso(next_run_at)
        )

    async def _fire(self, state: TriggerState, now: datetime) -> None:
        trigger = await self._load_trigger(state)
        if trigger is None:
            return
        if trigger.type.value != "cron":
            return

        next_run_at = _next_cron_run(trigger.schedule, now)

        if trigger.data_condition is not None:
            await self._record_failure(
                state,
                "data_condition triggers require SaaS connector infrastructure and are "
                "not supported by the standalone runtime",
                next_run_at,
            )
            return

        if not trigger.allow_concurrent:
            still_running = await self.engine.wstore.has_running_instance_for_trigger(
                state.workflow_name, state.trigger_index
            )
            if still_running:
                logger.info(
                    "Skipping tick for %s[%d] — previous run still in progress",
                    state.workflow_name, state.trigger_index,
                )
                await self.engine.wstore.set_trigger_next_run(
                    state.workflow_name, state.trigger_index, _iso(next_run_at)
                )
                return

        try:
            submitter_email = await self._resolve_requestor(trigger)
            form_data = dict(trigger.preset_form_data or {})
            await self.engine.submit_workflow(
                state.workflow_name,
                form_data,
                submitter_email=submitter_email,
                metadata={"trigger_source": "scheduler", "trigger_index": state.trigger_index},
            )
        except Exception as exc:
            await self._record_failure(state, str(exc), next_run_at)
            return

        await self.engine.wstore.record_trigger_run(
            state.workflow_name, state.trigger_index,
            success=True, error=None, next_run_at=_iso(next_run_at),
        )

    async def _record_failure(self, state: TriggerState, error: str, next_run_at: datetime) -> None:
        updated = await self.engine.wstore.record_trigger_run(
            state.workflow_name, state.trigger_index,
            success=False, error=error, next_run_at=_iso(next_run_at),
        )
        if updated.consecutive_failures >= self.max_consecutive_failures:
            await self.engine.wstore.set_trigger_enabled(
                state.workflow_name, state.trigger_index, False,
                actor="scheduler",
                reason=f"auto-disabled after {updated.consecutive_failures} consecutive failures",
            )
            logger.error(
                "Auto-disabled %s[%d] after %d consecutive failures: %s",
                state.workflow_name, state.trigger_index, updated.consecutive_failures, error,
            )

    async def _load_trigger(self, state: TriggerState):
        """Return the parsed TriggerConfig at state.trigger_index, or None if it's gone."""
        yaml_content = await self.engine.wstore.get_workflow_yaml(state.workflow_name)
        if yaml_content is None:
            logger.warning("Trigger for missing workflow '%s' — skipping", state.workflow_name)
            return None

        from approvalml.parser import ApprovalMLParser
        parser = ApprovalMLParser()
        parsed = parser.parse_yaml(yaml_content)
        triggers = (parsed.triggers or []) if parsed else []
        if state.trigger_index >= len(triggers):
            logger.warning(
                "Trigger index %d out of range for '%s' (only %d triggers now) — disabling",
                state.trigger_index, state.workflow_name, len(triggers),
            )
            await self.engine.wstore.set_trigger_enabled(
                state.workflow_name, state.trigger_index, False,
                actor="scheduler", reason="trigger no longer exists in the registered YAML",
            )
            return None
        return triggers[state.trigger_index]

    async def _resolve_requestor(self, trigger) -> Optional[str]:
        """
        Priority mirrors Aptiwise SaaS's ScheduledExecutionService._resolve_requestor,
        minus the workflow.created_by fallback (the standalone runtime doesn't
        track it): explicit requestor_email -> requestor_company_role (resolved
        via the same APPROVALML_ROLE_<NAME> convention as approver roles) ->
        no submitter (runs as admin/open access, like an unauthenticated call).
        """
        if trigger.requestor_email:
            return trigger.requestor_email
        if trigger.requestor_company_role:
            from .workflow_engine import _resolve_role
            emails = _resolve_role(trigger.requestor_company_role)
            if emails:
                return emails[0]
        return None


def _next_cron_run(cron_expression: str, base: datetime) -> datetime:
    return croniter(cron_expression, base).get_next(datetime)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None
