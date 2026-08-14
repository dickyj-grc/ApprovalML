"""
Integration tests for the standalone runtime's trigger_state storage layer
(PostgresWorkflowStore's sync_trigger_states/set_trigger_enabled/
record_trigger_run/has_running_instance_for_trigger and related methods).

Requires a real Postgres reachable via the APPROVALML_TEST_DATABASE_URL env
var — skipped entirely when that isn't set, so a plain local `pytest` run
(no Docker) degrades cleanly. Uses asyncio.run() per test rather than
@pytest.mark.asyncio, matching test_scheduler.py/test_sources_registry.py —
this project's dev extras don't include a pytest-asyncio plugin, so the
@pytest.mark.asyncio pattern in test_audit_log.py does not actually execute
without one installed separately.
"""

import asyncio
import json
import os

import asyncpg
import pytest

from approvalml.runtime.postgres_store import PostgresWorkflowStore, _AUDIT_FIELD_NAMES
from approvalml.audit_hash import verify_chain

DB_URL = os.environ.get("APPROVALML_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DB_URL, reason="APPROVALML_TEST_DATABASE_URL not set — skipping Postgres integration tests"
)


async def _fresh_store() -> PostgresWorkflowStore:
    """A store against a clean schema — drops all runtime tables first so each test starts empty."""
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute(
            "DROP TABLE IF EXISTS trigger_state, audit_log, workflow_steps, api_tokens, "
            "workflow_instances, workflow_definitions, approval_gates CASCADE"
        )
    finally:
        await conn.close()
    store = PostgresWorkflowStore(DB_URL)
    await store.initialize()
    return store


async def _all_audit_rows(store: PostgresWorkflowStore) -> list[dict]:
    """Rows with event_data JSON-decoded — asyncpg returns JSONB as a raw string with no codec registered."""
    pool = store._pool_or_raise()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM audit_log ORDER BY id ASC")
    entries = [dict(r) for r in rows]
    for entry in entries:
        if isinstance(entry.get("event_data"), str):
            entry["event_data"] = json.loads(entry["event_data"] or "{}")
    return entries


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_sync_trigger_states_creates_disabled_rows():
    """sync_trigger_states must create one disabled row per declared trigger."""
    async def _run():
        store = await _fresh_store()
        try:
            await store.upsert_workflow("daily-scan", "name: daily-scan\nworkflow: {}")
            await store.sync_trigger_states("daily-scan", 2)

            states = await store.list_trigger_states()
            assert [(s.trigger_index, s.enabled) for s in states] == [(0, False), (1, False)]
        finally:
            await store.close()

    asyncio.run(_run())


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_sync_trigger_states_is_idempotent_and_never_re_enables():
    """Re-syncing after a trigger was manually enabled must not reset it back to disabled."""
    async def _run():
        store = await _fresh_store()
        try:
            await store.upsert_workflow("daily-scan", "name: daily-scan\nworkflow: {}")
            await store.sync_trigger_states("daily-scan", 1)
            await store.set_trigger_enabled("daily-scan", 0, True, actor="alice", reason="go-live")

            await store.sync_trigger_states("daily-scan", 1)  # re-register, same trigger count

            state = await store.get_trigger_state("daily-scan", 0)
            assert state.enabled is True
        finally:
            await store.close()

    asyncio.run(_run())


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_sync_trigger_states_deletes_rows_for_removed_triggers():
    """Shrinking a workflow's triggers: list must delete the now-unmatched trigger_state rows."""
    async def _run():
        store = await _fresh_store()
        try:
            await store.upsert_workflow("daily-scan", "name: daily-scan\nworkflow: {}")
            await store.sync_trigger_states("daily-scan", 3)
            assert len(await store.list_trigger_states()) == 3

            await store.sync_trigger_states("daily-scan", 1)

            states = await store.list_trigger_states()
            assert [s.trigger_index for s in states] == [0]
        finally:
            await store.close()

    asyncio.run(_run())


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_set_trigger_enabled_is_governed_and_audited():
    """set_trigger_enabled must flip the bit and append an audited entry with actor + reason."""
    async def _run():
        store = await _fresh_store()
        try:
            await store.upsert_workflow("daily-scan", "name: daily-scan\nworkflow: {}")
            await store.sync_trigger_states("daily-scan", 1)

            state = await store.set_trigger_enabled(
                "daily-scan", 0, True, actor="alice@example.com", reason="daily CVE scan per SOC 2"
            )
            assert state.enabled is True

            rows = await _all_audit_rows(store)
            trigger_rows = [r for r in rows if r["entity_type"] == "trigger"]
            assert len(trigger_rows) == 1
            assert trigger_rows[0]["event_type"] == "enabled"
            assert trigger_rows[0]["actor"] == "alice@example.com"
            assert trigger_rows[0]["event_data"]["reason"] == "daily CVE scan per SOC 2"

            is_valid, messages = verify_chain(rows, _AUDIT_FIELD_NAMES)
            assert is_valid, messages
        finally:
            await store.close()

    asyncio.run(_run())


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_set_trigger_enabled_returns_none_for_missing_trigger():
    """set_trigger_enabled must return None (not raise) when the trigger doesn't exist."""
    async def _run():
        store = await _fresh_store()
        try:
            await store.upsert_workflow("daily-scan", "name: daily-scan\nworkflow: {}")
            await store.sync_trigger_states("daily-scan", 1)

            result = await store.set_trigger_enabled("daily-scan", 5, True)
            assert result is None
        finally:
            await store.close()

    asyncio.run(_run())


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_record_trigger_run_resets_failures_on_success_and_increments_on_failure():
    """consecutive_failures must increment on each failed run and reset to 0 on a success."""
    async def _run():
        store = await _fresh_store()
        try:
            await store.upsert_workflow("daily-scan", "name: daily-scan\nworkflow: {}")
            await store.sync_trigger_states("daily-scan", 1)

            s1 = await store.record_trigger_run("daily-scan", 0, success=False, error="boom", next_run_at=None)
            assert s1.consecutive_failures == 1
            assert s1.last_status == "failed"

            s2 = await store.record_trigger_run("daily-scan", 0, success=False, error="boom again", next_run_at=None)
            assert s2.consecutive_failures == 2

            s3 = await store.record_trigger_run("daily-scan", 0, success=True, error=None, next_run_at=None)
            assert s3.consecutive_failures == 0
            assert s3.last_status == "success"
            assert s3.last_error is None

            rows = await _all_audit_rows(store)
            run_rows = [r for r in rows if r["entity_type"] == "trigger"]
            assert [r["event_type"] for r in run_rows] == ["run_failed", "run_failed", "run_success"]
            assert all(r["actor"] == "scheduler" for r in run_rows)
        finally:
            await store.close()

    asyncio.run(_run())


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_set_trigger_next_run_does_not_touch_failure_counters():
    """Arming a trigger (set_trigger_next_run) must not affect last_status/consecutive_failures."""
    async def _run():
        store = await _fresh_store()
        try:
            await store.upsert_workflow("daily-scan", "name: daily-scan\nworkflow: {}")
            await store.sync_trigger_states("daily-scan", 1)
            await store.record_trigger_run("daily-scan", 0, success=False, error="boom", next_run_at=None)

            await store.set_trigger_next_run("daily-scan", 0, "2026-01-02T02:00:00+00:00")

            state = await store.get_trigger_state("daily-scan", 0)
            assert state.next_run_at == "2026-01-02T02:00:00+00:00"
            assert state.consecutive_failures == 1  # unchanged
            assert state.last_status == "failed"    # unchanged
        finally:
            await store.close()

    asyncio.run(_run())


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_has_running_instance_for_trigger():
    """has_running_instance_for_trigger must reflect only running, scheduler-tagged instances for that trigger."""
    async def _run():
        store = await _fresh_store()
        try:
            await store.upsert_workflow("daily-scan", "name: daily-scan\nworkflow: {}")
            await store.sync_trigger_states("daily-scan", 1)

            assert await store.has_running_instance_for_trigger("daily-scan", 0) is False

            instance = await store.create_instance(
                "daily-scan", {}, metadata={"trigger_source": "scheduler", "trigger_index": 0}
            )
            assert await store.has_running_instance_for_trigger("daily-scan", 0) is True

            # A manual submission (no trigger metadata) must not count.
            await store.create_instance("daily-scan", {}, metadata={"trigger_source": "manual"})
            assert await store.has_running_instance_for_trigger("daily-scan", 1) is False

            await store.update_instance_status(instance.id, "completed")
            assert await store.has_running_instance_for_trigger("daily-scan", 0) is False
        finally:
            await store.close()

    asyncio.run(_run())


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Sources Registry & Automatic Steps]]
def test_merge_instance_form_data():
    """merge_instance_form_data must JSONB-merge updates into the stored form_data."""
    async def _run():
        store = await _fresh_store()
        try:
            await store.upsert_workflow("match-po", "name: match-po\nworkflow: {}")
            instance = await store.create_instance("match-po", {"po_number": "PO-1"})

            await store.merge_instance_form_data(instance.id, {"po": {"status": "matched"}})

            reloaded = await store.get_instance(instance.id)
            assert reloaded.form_data == {"po_number": "PO-1", "po": {"status": "matched"}}
        finally:
            await store.close()

    asyncio.run(_run())


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Scheduled Workflow Execution]]
def test_list_workflow_names():
    """list_workflow_names must return every registered workflow, alphabetically."""
    async def _run():
        store = await _fresh_store()
        try:
            await store.upsert_workflow("b-workflow", "name: b\nworkflow: {}")
            await store.upsert_workflow("a-workflow", "name: a\nworkflow: {}")

            assert await store.list_workflow_names() == ["a-workflow", "b-workflow"]
        finally:
            await store.close()

    asyncio.run(_run())
