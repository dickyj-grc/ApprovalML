"""
PostgreSQL implementation of ApprovalStore and WorkflowStore using asyncpg.

Schema is deliberately minimal — suitable for the standalone runtime
without the full SaaS schema. All tables are created on initialize().
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from .base import ApprovalStore, ApprovalGate, WorkflowStore, WorkflowInstance, WorkflowStepRecord, UserToken


# ── DDL ────────────────────────────────────────────────────────────────────────

_CREATE_APPROVAL_GATES = """
CREATE TABLE IF NOT EXISTS approval_gates (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    description TEXT        NOT NULL,
    approver_email TEXT     NOT NULL,
    context     JSONB,
    status      TEXT        NOT NULL DEFAULT 'pending',
    token       TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at  TIMESTAMPTZ,
    decided_by  TEXT,
    comment     TEXT
);
"""

_CREATE_WORKFLOW_DEFINITIONS = """
CREATE TABLE IF NOT EXISTS workflow_definitions (
    name        TEXT        PRIMARY KEY,
    yaml_content TEXT       NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_CREATE_WORKFLOW_INSTANCES = """
CREATE TABLE IF NOT EXISTS workflow_instances (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_name   TEXT        NOT NULL REFERENCES workflow_definitions(name),
    form_data       JSONB       NOT NULL DEFAULT '{}',
    status          TEXT        NOT NULL DEFAULT 'running',
    current_step    TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);
"""

_CREATE_API_TOKENS = """
CREATE TABLE IF NOT EXISTS api_tokens (
    token       TEXT        PRIMARY KEY,
    email       TEXT        NOT NULL,
    name        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);
"""

# Migration columns added after initial schema was deployed
_MIGRATE_SUBMITTER_EMAILS = """
ALTER TABLE approval_gates    ADD COLUMN IF NOT EXISTS submitter_email TEXT;
ALTER TABLE workflow_instances ADD COLUMN IF NOT EXISTS submitter_email TEXT;
"""

_CREATE_WORKFLOW_STEPS = """
CREATE TABLE IF NOT EXISTS workflow_steps (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id     UUID        NOT NULL REFERENCES workflow_instances(id),
    step_name       TEXT        NOT NULL,
    step_type       TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'pending',
    token           TEXT        NOT NULL,
    approver_email  TEXT,
    parent_step_id  UUID        REFERENCES workflow_steps(id),
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at      TIMESTAMPTZ,
    decided_by      TEXT,
    comment         TEXT
);
"""


class PostgresStore(ApprovalStore):
    """Approval gate storage backed by a single PostgreSQL table."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def initialize(self) -> None:
        self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)
        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_APPROVAL_GATES)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    def _pool_or_raise(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgresStore not initialized — call initialize() first")
        return self._pool

    @staticmethod
    def _row_to_gate(row: asyncpg.Record) -> ApprovalGate:
        ctx = row["context"]
        if isinstance(ctx, str):
            ctx = json.loads(ctx)
        return ApprovalGate(
            id=str(row["id"]),
            description=row["description"],
            approver_email=row["approver_email"],
            context=ctx,
            status=row["status"],
            token=row["token"],
            created_at=_iso(row["created_at"]),
            decided_at=_iso(row["decided_at"]) if row["decided_at"] else None,
            decided_by=row["decided_by"],
            comment=row["comment"],
            submitter_email=row["submitter_email"] if "submitter_email" in row.keys() else None,
        )

    async def create_gate(
        self,
        description: str,
        approver_email: str,
        context: Optional[dict[str, Any]] = None,
        submitter_email: Optional[str] = None,
    ) -> ApprovalGate:
        gate_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO approval_gates
                       (id, description, approver_email, context, status, token,
                        created_at, submitter_email)
                   VALUES ($1, $2, $3, $4::jsonb, 'pending', $5, $6, $7)""",
                gate_id,
                description,
                approver_email,
                json.dumps(context) if context is not None else None,
                token,
                now,
                submitter_email,
            )
        return ApprovalGate(
            id=gate_id,
            description=description,
            approver_email=approver_email,
            context=context,
            status="pending",
            token=token,
            created_at=_iso(now),
            submitter_email=submitter_email,
        )

    async def get_gate(self, gate_id: str) -> Optional[ApprovalGate]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM approval_gates WHERE id = $1", gate_id
            )
        return self._row_to_gate(row) if row else None

    async def decide_gate(
        self,
        gate_id: str,
        token: str,
        decision: str,
        comment: Optional[str] = None,
        decided_by: Optional[str] = None,
    ) -> tuple[Optional[ApprovalGate], Optional[str]]:
        gate = await self.get_gate(gate_id)
        if gate is None:
            return None, "Not found"
        if gate.status != "pending":
            return None, f"Already {gate.status}"
        if not secrets.compare_digest(gate.token, token):
            return None, "Invalid token"
        now = datetime.now(timezone.utc)
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE approval_gates
                   SET status=$1, decided_at=$2, decided_by=$3, comment=$4
                   WHERE id=$5""",
                decision, now, decided_by, comment, gate_id,
            )
        gate.status = decision
        gate.decided_at = _iso(now)
        gate.decided_by = decided_by
        gate.comment = comment
        return gate, None

    async def list_pending(self) -> list[ApprovalGate]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM approval_gates WHERE status = 'pending' ORDER BY created_at DESC"
            )
        return [self._row_to_gate(r) for r in rows]


class PostgresWorkflowStore(PostgresStore, WorkflowStore):
    """Extends PostgresStore with full workflow instance + step tracking."""

    async def initialize(self) -> None:
        await super().initialize()
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(_CREATE_WORKFLOW_DEFINITIONS)
            await conn.execute(_CREATE_WORKFLOW_INSTANCES)
            await conn.execute(_CREATE_WORKFLOW_STEPS)
            await conn.execute(_CREATE_API_TOKENS)
            await conn.execute(_MIGRATE_SUBMITTER_EMAILS)

    # ── Workflow definitions ───────────────────────────────────────────────────

    async def upsert_workflow(self, name: str, yaml_content: str) -> None:
        pool = self._pool_or_raise()
        now = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO workflow_definitions (name, yaml_content, updated_at)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (name) DO UPDATE
                     SET yaml_content = EXCLUDED.yaml_content,
                         updated_at   = EXCLUDED.updated_at""",
                name, yaml_content, now,
            )

    async def get_workflow_yaml(self, name: str) -> Optional[str]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT yaml_content FROM workflow_definitions WHERE name = $1", name
            )
        return row["yaml_content"] if row else None

    # ── Workflow instances ─────────────────────────────────────────────────────

    async def create_instance(
        self,
        workflow_name: str,
        form_data: dict[str, Any],
        submitter_email: Optional[str] = None,
    ) -> WorkflowInstance:
        inst_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO workflow_instances
                       (id, workflow_name, form_data, status, created_at, submitter_email)
                   VALUES ($1, $2, $3::jsonb, 'running', $4, $5)""",
                inst_id, workflow_name, json.dumps(form_data), now, submitter_email,
            )
        return WorkflowInstance(
            id=inst_id,
            workflow_name=workflow_name,
            form_data=form_data,
            status="running",
            current_step=None,
            created_at=_iso(now),
            submitter_email=submitter_email,
        )

    async def get_instance(self, instance_id: str) -> Optional[WorkflowInstance]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM workflow_instances WHERE id = $1", instance_id
            )
        return _row_to_instance(row) if row else None

    async def update_instance_status(
        self,
        instance_id: str,
        status: str,
        current_step: Optional[str] = None,
    ) -> None:
        pool = self._pool_or_raise()
        now = datetime.now(timezone.utc) if status in ("completed", "rejected", "error") else None
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE workflow_instances
                   SET status=$1, current_step=$2, completed_at=$3
                   WHERE id=$4""",
                status, current_step, now, instance_id,
            )

    # ── Workflow steps ─────────────────────────────────────────────────────────

    async def create_step(
        self,
        instance_id: str,
        step_name: str,
        step_type: str,
        approver_email: Optional[str],
        parent_step_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> WorkflowStepRecord:
        step_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO workflow_steps
                       (id, instance_id, step_name, step_type, status, token,
                        approver_email, parent_step_id, metadata, created_at)
                   VALUES ($1, $2, $3, $4, 'pending', $5, $6, $7, $8::jsonb, $9)""",
                step_id, instance_id, step_name, step_type, token,
                approver_email,
                parent_step_id,
                json.dumps(metadata) if metadata is not None else None,
                now,
            )
        return WorkflowStepRecord(
            id=step_id,
            instance_id=instance_id,
            step_name=step_name,
            step_type=step_type,
            status="pending",
            token=token,
            approver_email=approver_email,
            parent_step_id=parent_step_id,
            metadata=metadata,
            created_at=_iso(now),
        )

    async def get_step(self, step_id: str) -> Optional[WorkflowStepRecord]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM workflow_steps WHERE id = $1", step_id
            )
        return _row_to_step(row) if row else None

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
            return None, "Not found"
        if step.status != "pending":
            return None, f"Already {step.status}"
        if not secrets.compare_digest(step.token, token):
            return None, "Invalid token"
        now = datetime.now(timezone.utc)
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE workflow_steps
                   SET status=$1, decided_at=$2, decided_by=$3, comment=$4
                   WHERE id=$5""",
                decision, now, decided_by, comment, step_id,
            )
        step.status = decision
        step.decided_at = _iso(now)
        step.decided_by = decided_by
        step.comment = comment
        return step, None

    async def get_steps_for_instance(self, instance_id: str) -> list[WorkflowStepRecord]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM workflow_steps WHERE instance_id = $1 ORDER BY created_at ASC",
                instance_id,
            )
        return [_row_to_step(r) for r in rows]

    async def get_child_steps(self, parent_step_id: str) -> list[WorkflowStepRecord]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM workflow_steps WHERE parent_step_id = $1 ORDER BY created_at ASC",
                parent_step_id,
            )
        return [_row_to_step(r) for r in rows]

    # ── API token management ───────────────────────────────────────────────────

    async def create_token(self, email: str, name: Optional[str] = None) -> UserToken:
        token = "awat_" + secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO api_tokens (token, email, name, created_at) VALUES ($1, $2, $3, $4)",
                token, email, name, now,
            )
        return UserToken(token=token, email=email, name=name, created_at=_iso(now))

    async def resolve_token(self, token: str) -> Optional[UserToken]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM api_tokens WHERE token = $1", token)
            if row:
                await conn.execute(
                    "UPDATE api_tokens SET last_used_at = NOW() WHERE token = $1", token
                )
        return _row_to_user_token(row) if row else None

    async def list_tokens(self) -> list[UserToken]:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM api_tokens ORDER BY created_at DESC"
            )
        return [_row_to_user_token(r) for r in rows]

    async def revoke_token(self, token: str) -> bool:
        pool = self._pool_or_raise()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM api_tokens WHERE token = $1", token)
        return result == "DELETE 1"


# ── Row converters ─────────────────────────────────────────────────────────────

def _row_to_instance(row: asyncpg.Record) -> WorkflowInstance:
    fd = row["form_data"]
    if isinstance(fd, str):
        fd = json.loads(fd)
    meta = row["metadata"] if "metadata" in row.keys() else None
    if isinstance(meta, str):
        meta = json.loads(meta)
    return WorkflowInstance(
        id=str(row["id"]),
        workflow_name=row["workflow_name"],
        form_data=fd or {},
        status=row["status"],
        current_step=row["current_step"],
        created_at=_iso(row["created_at"]),
        completed_at=_iso(row["completed_at"]) if row["completed_at"] else None,
        metadata=meta,
        submitter_email=row["submitter_email"] if "submitter_email" in row.keys() else None,
    )


def _row_to_step(row: asyncpg.Record) -> WorkflowStepRecord:
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return WorkflowStepRecord(
        id=str(row["id"]),
        instance_id=str(row["instance_id"]),
        step_name=row["step_name"],
        step_type=row["step_type"],
        status=row["status"],
        token=row["token"],
        approver_email=row["approver_email"],
        parent_step_id=str(row["parent_step_id"]) if row["parent_step_id"] else None,
        metadata=meta,
        created_at=_iso(row["created_at"]),
        decided_at=_iso(row["decided_at"]) if row["decided_at"] else None,
        decided_by=row["decided_by"],
        comment=row["comment"],
    )


def _row_to_user_token(row: asyncpg.Record) -> UserToken:
    return UserToken(
        token=row["token"],
        email=row["email"],
        name=row["name"],
        created_at=_iso(row["created_at"]),
    )


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if hasattr(dt, "isoformat"):
        return dt.isoformat()
    return str(dt)
