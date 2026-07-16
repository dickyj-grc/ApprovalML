"""
Integration tests for the standalone runtime's audit log wiring
(PostgresStore._append_audit and its call sites).

Requires a real Postgres reachable via the APPROVALML_TEST_DATABASE_URL env
var — skipped entirely when that isn't set, so a plain local `pytest` run
(no Docker) degrades cleanly. CI provides a `postgres` service (see
bitbucket-pipelines.yml) that can be pointed at via this env var.
"""

import asyncio
import os

import asyncpg
import pytest

from approvalml.audit_hash import verify_chain
from approvalml.runtime.postgres_store import PostgresWorkflowStore, _AUDIT_FIELD_NAMES

DB_URL = os.environ.get("APPROVALML_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DB_URL, reason="APPROVALML_TEST_DATABASE_URL not set — skipping Postgres integration tests"
)


async def _fresh_store() -> PostgresWorkflowStore:
    """A store against a clean schema — drops all runtime tables first so each test starts empty."""
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute(
            "DROP TABLE IF EXISTS audit_log, workflow_steps, api_tokens, "
            "workflow_instances, workflow_definitions, approval_gates CASCADE"
        )
    finally:
        await conn.close()
    store = PostgresWorkflowStore(DB_URL)
    await store.initialize()
    return store


async def _all_audit_rows(store: PostgresWorkflowStore) -> list[dict]:
    pool = store._pool_or_raise()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM audit_log ORDER BY id ASC")
    return [dict(r) for r in rows]


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Global chain wiring]]
@pytest.mark.asyncio
async def test_initialize_seeds_exactly_one_genesis_row():
    """initialize() must create audit_log and seed exactly one genesis row, idempotently."""
    store = await _fresh_store()
    try:
        rows = await _all_audit_rows(store)
        assert len(rows) == 1
        assert rows[0]["event_type"] == "genesis"
        assert rows[0]["prev_hash"] is None

        # Re-initializing must not add a second genesis row.
        await store.initialize()
        rows_again = await _all_audit_rows(store)
        assert len(rows_again) == 1
    finally:
        await store.close()


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Global chain wiring]]
@pytest.mark.asyncio
async def test_gate_lifecycle_appends_audit_rows():
    """create_gate and decide_gate each append one audit row for the gate entity."""
    store = await _fresh_store()
    try:
        gate = await store.create_gate("test gate", "approver@example.com")
        rows = await _all_audit_rows(store)
        assert [r["event_type"] for r in rows] == ["genesis", "created"]
        assert rows[-1]["entity_type"] == "gate"
        assert str(rows[-1]["entity_id"]) == gate.id

        await store.decide_gate(gate.id, gate.token, "approved", decided_by="alice@example.com")
        rows = await _all_audit_rows(store)
        assert [r["event_type"] for r in rows] == ["genesis", "created", "approved"]
        assert rows[-1]["actor"] == "alice@example.com"
    finally:
        await store.close()


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Global chain wiring]]
@pytest.mark.asyncio
async def test_chain_is_global_across_mixed_entity_types():
    """A gate action and a workflow-instance action share one continuous chain, not separate ones."""
    store = await _fresh_store()
    try:
        gate = await store.create_gate("g1", "a@example.com")
        await store.upsert_workflow("wf1", "name: wf1\nworkflow: {}")
        instance = await store.create_instance("wf1", {"field": "value"})

        rows = await _all_audit_rows(store)
        assert [r["event_type"] for r in rows] == ["genesis", "created", "created"]
        assert rows[1]["entity_type"] == "gate"
        assert rows[2]["entity_type"] == "instance"
        # The instance's creation row chains directly off the gate's creation row.
        assert rows[2]["prev_hash"] == rows[1]["entry_hash"]

        is_valid, messages = verify_chain(rows, _AUDIT_FIELD_NAMES)
        assert is_valid, messages
    finally:
        await store.close()


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Global chain wiring]]
@pytest.mark.asyncio
async def test_parallel_skip_path_appends_audit_rows():
    """_check_parallel_completion's raw-SQL skip path logs a 'skipped' row per sibling plus the parent outcome."""
    from approvalml.runtime.workflow_engine import WorkflowEngine

    store = await _fresh_store()
    try:
        await store.upsert_workflow("wf_parallel", "name: wf_parallel\nworkflow: {}")
        instance = await store.create_instance("wf_parallel", {})
        parent = await store.create_step(
            instance.id, "review", "parallel_approval", None,
            metadata={"approval_strategy": "any_one", "required_approvals": 1, "total_approvers": 2},
        )
        child_a = await store.create_step(instance.id, "review_a", "decision", "a@example.com", parent_step_id=parent.id)
        child_b = await store.create_step(instance.id, "review_b", "decision", "b@example.com", parent_step_id=parent.id)

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.wstore = store
        await store.decide_step(child_a.id, child_a.token, "approved", decided_by="a@example.com")
        decided_child_a = await store.get_step(child_a.id)
        await engine._check_parallel_completion(instance, decided_child_a, {}, {}, {})

        rows = await _all_audit_rows(store)
        event_types = [r["event_type"] for r in rows]
        assert "skipped" in event_types
        assert "approved" in event_types

        skipped_rows = [r for r in rows if r["event_type"] == "skipped"]
        assert len(skipped_rows) == 1
        assert str(skipped_rows[0]["entity_id"]) == child_b.id

        is_valid, messages = verify_chain(rows, _AUDIT_FIELD_NAMES)
        assert is_valid, messages
    finally:
        await store.close()


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Concurrency]]
@pytest.mark.asyncio
async def test_concurrent_appends_do_not_fork_the_chain():
    """Firing many _append_audit calls concurrently must still produce one unbroken chain."""
    store = await _fresh_store()
    try:
        gate = await store.create_gate("concurrency target", "a@example.com")

        async def decide_once(n: int):
            pool = store._pool_or_raise()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await store._append_audit(conn, "gate", gate.id, "note", {"n": n})

        await asyncio.gather(*(decide_once(n) for n in range(10)))

        rows = await _all_audit_rows(store)
        # genesis + gate-created + 10 concurrent notes
        assert len(rows) == 12
        is_valid, messages = verify_chain(rows, _AUDIT_FIELD_NAMES)
        assert is_valid, messages
        # No two rows should share a prev_hash — that would mean the chain forked.
        prev_hashes = [r["prev_hash"] for r in rows if r["prev_hash"] is not None]
        assert len(prev_hashes) == len(set(prev_hashes))
    finally:
        await store.close()


# @lat: [[open-source#Open-Source: ApprovalML Package#Standalone Runtime#Audit Trail#Chain verification]]
@pytest.mark.asyncio
async def test_verify_chain_detects_tampering_on_real_rows():
    """After a realistic sequence of actions, corrupting one stored row must break verification."""
    store = await _fresh_store()
    try:
        gate = await store.create_gate("g", "a@example.com")
        await store.decide_gate(gate.id, gate.token, "approved", decided_by="a@example.com")

        rows = await _all_audit_rows(store)
        is_valid, _ = verify_chain(rows, _AUDIT_FIELD_NAMES)
        assert is_valid is True

        pool = store._pool_or_raise()
        tampered_id = rows[1]["id"]
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE audit_log SET event_data = '{\"description\": \"tampered\"}'::jsonb WHERE id = $1",
                tampered_id,
            )

        rows_after = await _all_audit_rows(store)
        is_valid_after, messages = verify_chain(rows_after, _AUDIT_FIELD_NAMES)
        assert is_valid_after is False
        assert any(f"id={tampered_id}" in m for m in messages)
    finally:
        await store.close()
