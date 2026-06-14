"""
ApprovalML standalone HTTP server.

Authentication model:
  - APPROVALML_API_TOKEN  — master/admin token; no submitter email; sees all data
  - api_tokens DB table   — per-user tokens created via POST /services/v1/tokens;
                            each token maps to an email that is recorded as submitter
  - APPROVALML_TOKENS env — seed tokens at startup: "token1:email1,token2:email2:Name"
  - No APPROVALML_API_TOKEN set → open access (development only)

User tokens scope list_pending / submit_workflow to their own email.
Admin token and open access see everything.

API surface:
  POST /services/v1/approvals/gate          — create approval gate (simple, no YAML)
  GET  /services/v1/approvals/{id}/status   — poll gate status
  GET  /services/v1/approvals/pending       — list pending gates
  POST /services/v1/workflows               — register a workflow YAML by name (admin)
  POST /services/v1/approvals/              — submit a named workflow instance
  GET  /services/v1/approvals/{id}/workflow — get workflow instance status
  POST /services/v1/tokens                  — create a user token (admin only)
  GET  /services/v1/tokens                  — list user tokens (admin only)
  DELETE /services/v1/tokens/{token}        — revoke a user token (admin only)
  GET  /decide/{id}/approve?token=...       — approve link (simple gate, from email)
  GET  /decide/{id}/reject?token=...        — reject link (simple gate, from email)
  GET  /workflow-step/{id}/approve?token=…  — approve link (workflow step, from email)
  GET  /workflow-step/{id}/reject?token=…   — reject link (workflow step, from email)
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Optional, Union

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from .engine import ApprovalEngine
from .workflow_engine import WorkflowEngine, WorkflowError

# Module-level engine instance — set by start()
_engine: Optional[Union[ApprovalEngine, WorkflowEngine]] = None


def _get_engine() -> ApprovalEngine:
    if _engine is None:
        raise RuntimeError("Runtime not started")
    return _engine


def _get_workflow_engine() -> WorkflowEngine:
    if not isinstance(_engine, WorkflowEngine):
        raise HTTPException(status_code=501, detail="Workflow execution not enabled")
    return _engine


# ── Authentication ─────────────────────────────────────────────────────────────

@dataclass
class _AuthResult:
    is_admin: bool            # True = master token or open access
    submitter_email: Optional[str]  # None for admin/open, email for user tokens


async def _resolve_auth(authorization: Optional[str]) -> _AuthResult:
    """
    Resolve a Bearer token to an auth context.

    Priority:
      1. No master token configured  → open access (admin, no email)
      2. Matches APPROVALML_API_TOKEN → admin access (no email)
      3. Found in api_tokens DB table → user access with email
      4. None of the above           → 403
    """
    master = os.environ.get("APPROVALML_API_TOKEN", "")
    if not master:
        return _AuthResult(is_admin=True, submitter_email=None)

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> required")

    given = authorization[len("Bearer "):]

    if secrets.compare_digest(given, master):
        return _AuthResult(is_admin=True, submitter_email=None)

    # Try user token lookup
    engine = _get_engine()
    if hasattr(engine.store, "resolve_token"):
        user_token = await engine.store.resolve_token(given)
        if user_token:
            return _AuthResult(is_admin=False, submitter_email=user_token.email)

    raise HTTPException(status_code=403, detail="Invalid token")


def _require_admin(auth: _AuthResult) -> None:
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin token required")


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(app: FastAPI):
    engine = _get_engine()
    await engine.store.initialize()
    if _tokens_to_seed:
        await _seed_tokens(engine)
    if _workflows_dir_at_startup and isinstance(engine, WorkflowEngine):
        await _load_workflows_from_dir(engine, _workflows_dir_at_startup)
    yield
    await engine.store.close()


app = FastAPI(
    title="ApprovalML Standalone Runtime",
    description="Self-contained approval server for the open-source MCP integration.",
    version="0.3.0",
    lifespan=_lifespan,
)


# ── Simple gate endpoints ──────────────────────────────────────────────────────

@app.post("/services/v1/approvals/gate")
async def create_gate(request: Request) -> dict[str, Any]:
    """Create a single-step approval gate and send email to the approver."""
    auth = await _resolve_auth(request.headers.get("authorization"))
    body: dict[str, Any] = await request.json()
    description = body.get("description", "")
    approver_email = body.get("approver_email", "")
    if not description or not approver_email:
        raise HTTPException(status_code=422, detail="description and approver_email are required")
    return await _get_engine().request_gate(
        description, approver_email, body.get("context"),
        submitter_email=auth.submitter_email,
    )


@app.get("/services/v1/approvals/pending")
async def list_pending(request: Request) -> list[dict[str, Any]]:
    """Return pending gates. User tokens see only their own; admin sees all."""
    auth = await _resolve_auth(request.headers.get("authorization"))
    gates = await _get_engine().list_pending()
    if not auth.is_admin and auth.submitter_email:
        gates = [g for g in gates if g.get("submitter_email") == auth.submitter_email]
    return gates


@app.get("/services/v1/approvals/{gate_id}/status")
async def get_gate_status(gate_id: str, request: Request) -> dict[str, Any]:
    """Return current status of a simple approval gate."""
    await _resolve_auth(request.headers.get("authorization"))
    result = await _get_engine().get_status(gate_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Gate not found")
    return result


# ── Workflow endpoints ─────────────────────────────────────────────────────────

@app.post("/services/v1/workflows")
async def register_workflow(request: Request) -> dict[str, Any]:
    """Register (or replace) a workflow YAML definition by name. Admin only."""
    auth = await _resolve_auth(request.headers.get("authorization"))
    _require_admin(auth)
    body: dict[str, Any] = await request.json()
    name = body.get("name", "").strip()
    yaml_content = body.get("yaml", "").strip()
    if not name or not yaml_content:
        raise HTTPException(status_code=422, detail="name and yaml are required")
    engine = _get_workflow_engine()
    try:
        return await engine.register_workflow(name, yaml_content)
    except WorkflowError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/services/v1/approvals/")
async def submit_workflow(request: Request) -> dict[str, Any]:
    """Submit a workflow instance. Body: {workflow_id: name, form_data: {...}}."""
    auth = await _resolve_auth(request.headers.get("authorization"))
    body: dict[str, Any] = await request.json()
    workflow_name = str(body.get("workflow_id", "")).strip()
    form_data = body.get("form_data", {}) or {}
    if not workflow_name:
        raise HTTPException(status_code=422, detail="workflow_id (workflow name) is required")
    engine = _get_workflow_engine()
    try:
        return await engine.submit_workflow(
            workflow_name, form_data, submitter_email=auth.submitter_email
        )
    except WorkflowError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/services/v1/approvals/{instance_id}/workflow")
async def get_workflow_status(instance_id: str, request: Request) -> dict[str, Any]:
    """Return full status of a workflow instance including all steps."""
    await _resolve_auth(request.headers.get("authorization"))
    engine = _get_workflow_engine()
    result = await engine.get_instance_status(instance_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Workflow instance not found")
    return result


# ── Token management (admin only) ─────────────────────────────────────────────

@app.post("/services/v1/tokens")
async def create_token(request: Request) -> dict[str, Any]:
    """Create a new user API token. Body: {email, name?}. Admin only."""
    auth = await _resolve_auth(request.headers.get("authorization"))
    _require_admin(auth)
    body: dict[str, Any] = await request.json()
    email = (body.get("email") or "").strip()
    name = (body.get("name") or "").strip() or None
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="Valid email is required")
    engine = _get_engine()
    if not hasattr(engine.store, "create_token"):
        raise HTTPException(status_code=501, detail="Token management not available")
    user_token = await engine.store.create_token(email, name)
    return {"token": user_token.token, "email": user_token.email, "name": user_token.name}


@app.get("/services/v1/tokens")
async def list_tokens(request: Request) -> list[dict[str, Any]]:
    """List all user tokens (token values are shown — store them securely). Admin only."""
    auth = await _resolve_auth(request.headers.get("authorization"))
    _require_admin(auth)
    engine = _get_engine()
    if not hasattr(engine.store, "list_tokens"):
        raise HTTPException(status_code=501, detail="Token management not available")
    tokens = await engine.store.list_tokens()
    return [{"token": t.token, "email": t.email, "name": t.name, "created_at": t.created_at}
            for t in tokens]


@app.delete("/services/v1/tokens/{token}")
async def revoke_token(token: str, request: Request) -> dict[str, Any]:
    """Revoke a user token. Admin only."""
    auth = await _resolve_auth(request.headers.get("authorization"))
    _require_admin(auth)
    engine = _get_engine()
    if not hasattr(engine.store, "revoke_token"):
        raise HTTPException(status_code=501, detail="Token management not available")
    deleted = await engine.store.revoke_token(token)
    if not deleted:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"revoked": True}


# ── Email decision links — simple gate ────────────────────────────────────────

_DECISION_PAGE = """<!doctype html>
<html><body style="font-family:sans-serif;max-width:480px;margin:80px auto;text-align:center">
<div style="font-size:64px">{icon}</div>
<h1 style="color:{color}">{heading}</h1>
<p style="color:#555">{message}</p>
</body></html>"""


@app.get("/decide/{gate_id}/{decision}", response_class=HTMLResponse)
async def decide_gate(
    gate_id: str,
    decision: str,
    token: str = Query(...),
    comment: str = Query(default=""),
) -> HTMLResponse:
    """Handle approve/reject click from a simple gate email link."""
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")

    gate, err = await _get_engine().decide(
        gate_id, token, decision, comment or None, decided_by=None
    )
    if err:
        return HTMLResponse(
            _DECISION_PAGE.format(icon="⚠️", color="#b45309",
                                  heading="Could not record decision", message=err),
            status_code=400,
        )
    if decision == "approve":
        return HTMLResponse(_DECISION_PAGE.format(
            icon="✅", color="#16a34a", heading="Approved",
            message="Your response has been recorded. You can close this page.",
        ))
    return HTMLResponse(_DECISION_PAGE.format(
        icon="❌", color="#dc2626", heading="Rejected",
        message="Your response has been recorded. You can close this page.",
    ))


# ── Email decision links — workflow step ──────────────────────────────────────

@app.get("/workflow-step/{step_id}/{decision}", response_class=HTMLResponse)
async def decide_workflow_step(
    step_id: str,
    decision: str,
    token: str = Query(...),
    comment: str = Query(default=""),
) -> HTMLResponse:
    """Handle approve/reject click from a workflow step email link."""
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")

    engine = _get_workflow_engine()
    result, err = await engine.decide_workflow_step(
        step_id, token, decision, comment or None
    )
    if err:
        return HTMLResponse(
            _DECISION_PAGE.format(icon="⚠️", color="#b45309",
                                  heading="Could not record decision", message=err),
            status_code=400,
        )
    if decision == "approve":
        return HTMLResponse(_DECISION_PAGE.format(
            icon="✅", color="#16a34a", heading="Approved",
            message="Your response has been recorded. The workflow has been advanced.",
        ))
    return HTMLResponse(_DECISION_PAGE.format(
        icon="❌", color="#dc2626", heading="Rejected",
        message="Your response has been recorded. The workflow has been advanced.",
    ))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Startup helpers ────────────────────────────────────────────────────────────

_workflows_dir_at_startup: Optional[str] = None
_tokens_to_seed: list[tuple[str, str, Optional[str]]] = []  # [(token, email, name)]


async def _seed_tokens(engine: ApprovalEngine) -> None:
    """Insert pre-configured tokens from APPROVALML_TOKENS env var if not already present."""
    import logging
    logger = logging.getLogger(__name__)
    if not hasattr(engine.store, "resolve_token"):
        return
    for token, email, name in _tokens_to_seed:
        existing = await engine.store.resolve_token(token)
        if existing is None:
            pool = engine.store._pool_or_raise()
            from datetime import datetime, timezone
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO api_tokens (token, email, name, created_at) VALUES ($1, $2, $3, $4)"
                    " ON CONFLICT (token) DO NOTHING",
                    token, email, name, datetime.now(timezone.utc),
                )
            logger.info("Seeded token for %s", email)


async def _load_workflows_from_dir(engine: WorkflowEngine, workflows_dir: str) -> None:
    """Scan a directory for *.yaml / *.yml files and register each as a workflow."""
    import logging
    from pathlib import Path
    logger = logging.getLogger(__name__)

    path = Path(workflows_dir)
    if not path.exists():
        logger.info("WORKFLOWS_DIR %s does not exist — skipping", workflows_dir)
        return

    yaml_files = sorted(list(path.glob("*.yaml")) + list(path.glob("*.yml")))
    if not yaml_files:
        logger.info("No YAML files found in %s", workflows_dir)
        return

    logger.info("Loading %d workflow file(s) from %s", len(yaml_files), workflows_dir)
    loaded, skipped = 0, 0
    for yaml_path in yaml_files:
        try:
            yaml_content = yaml_path.read_text(encoding="utf-8")
            await engine.register_workflow(yaml_path.stem, yaml_content)
            logger.info("  Loaded: %s", yaml_path.stem)
            loaded += 1
        except Exception as exc:
            logger.warning("  Skipped %s: %s", yaml_path.name, exc)
            skipped += 1

    logger.info("Workflow loader complete: %d loaded, %d skipped", loaded, skipped)


def _parse_tokens_env(raw: str) -> list[tuple[str, str, Optional[str]]]:
    """Parse APPROVALML_TOKENS=token1:email1,token2:email2:Name Two into a list."""
    result = []
    for entry in raw.split(","):
        parts = entry.strip().split(":", 2)
        if len(parts) >= 2:
            token, email = parts[0].strip(), parts[1].strip()
            name = parts[2].strip() if len(parts) == 3 else None
            if token and "@" in email:
                result.append((token, email, name))
    return result


# ── Entry point ────────────────────────────────────────────────────────────────

def start(
    port: int = 8765,
    db_url: Optional[str] = None,
    server_url: Optional[str] = None,
    api_token: Optional[str] = None,
    workflows_dir: Optional[str] = None,
) -> None:
    """Start the standalone runtime. Called by the CLI `approvalml serve` command."""
    import uvicorn
    from .postgres_store import PostgresWorkflowStore
    from .email_smtp import SmtpEmailSender

    global _engine, _workflows_dir_at_startup, _tokens_to_seed

    resolved_db_url = db_url or os.environ.get(
        "DATABASE_URL",
        "postgresql://approvalml:approvalml@localhost:5432/approvalml",
    )
    resolved_server_url = server_url or os.environ.get(
        "APPROVALML_SERVER_URL", f"http://localhost:{port}"
    )

    if api_token:
        os.environ["APPROVALML_API_TOKEN"] = api_token

    _engine = WorkflowEngine(
        store=PostgresWorkflowStore(dsn=resolved_db_url),
        email=SmtpEmailSender(),
        server_url=resolved_server_url,
    )

    _workflows_dir_at_startup = workflows_dir or os.environ.get("WORKFLOWS_DIR", "") or None

    tokens_raw = os.environ.get("APPROVALML_TOKENS", "")
    _tokens_to_seed = _parse_tokens_env(tokens_raw) if tokens_raw else []

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
