# ApprovalML

Multi-party approval workflows for AI agent tool calls. Define maker-checker chains in YAML, get a tamper-evident record of every decision.

**ApprovalML** is a headless approval workflow engine for AI agents. When an agent calls a tool that moves money, touches production, or grants access, a single "approve" click isn't a control — it's a formality. ApprovalML lets you declare real authorization chains in YAML — serial (supervisor → finance → director), parallel (any-one, majority, all), conditional on the call's payload — expose each one as an MCP tool an agent can call directly, and put safe recurring work on a governed cron schedule instead of an agent's own loop. Every decision is identity-bound and written to a hash-chained, tamper-evident audit trail: not just *that* the call was approved, but *who* authorized it, and in what order.

No LLM in the enforcement path. AI proposes the action; the approval chain is deterministic YAML, executed exactly as written. Humans are named in `.env`, workflows are portable, and the whole thing runs from the command line with docker compose — no UI required.

- **Multi-party chains, not single gates** — serial steps, parallel strategies (all / any-one / majority), conditional routing on tool-call data
- **MCP-native** — point `--workflows-dir` at a folder of workflow YAML and every file becomes a `submit_<name>` tool with a real JSON-schema input generated from the form fields — see [Expose a Workflow Directory as MCP](#expose-a-workflow-directory-as-mcp)
- **Governed scheduling** — cron triggers ship disabled; an agent can arm or observe a schedule through MCP tools, but the runtime's own scheduler ticks it — never the agent's loop — see [Scheduled Workflows](#scheduled-workflows)
- **Tamper-evident audit trail** — every action (creation, decision, auto-skip, scheduler run) is hash-chained with actor identity and timestamp — see [Audit Trail](#audit-trail)
- **Deterministic runtime** — the YAML is compiled policy; no model decides who approves what
- **Roles via environment** — `approver: finance_manager` resolves through `APPROVALML_ROLE_FINANCE_MANAGER` in `.env`, so workflow templates are shareable without a company directory
- **Headless by design** — CLI + `approvalml validate`, config in git, alerts to the tools you already have

> **New to ApprovalML?** Use [`PROMPT.md`](./PROMPT.md) with any AI assistant to generate workflows from plain English — no need to learn the syntax first.

## Install

```bash
pip install approvalml
```

Or for local development:

```bash
git clone https://github.com/yourorg/approvalml
pip install -e ./approvalml
```

## CLI

```bash
# Validate a workflow file
approvalml validate my-workflow.yaml

# Validate with step/field details
approvalml validate my-workflow.yaml --verbose

# Print a readable summary
approvalml info my-workflow.yaml
```

## MCP Server (Claude Desktop)

Gate any AI action behind a human approval step. The MCP server connects Claude to the ApprovalML runtime, giving you `request_approval`, `check_approval_status`, and `list_pending_approvals` as native tools.

```bash
pip install "approvalml[mcp]"
export APPROVALML_API_URL=http://localhost:8765
export APPROVALML_API_TOKEN=<your-token>
approvalml mcp-server
```

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "approvalml": {
      "command": "approvalml",
      "args": ["mcp-server"],
      "env": {
        "APPROVALML_API_URL": "http://localhost:8765",
        "APPROVALML_API_TOKEN": "your-token-here"
      }
    }
  }
}
```

The MCP server is stateless — it calls the runtime REST API. It works with the [standalone runtime](#standalone-runtime) below or with a hosted ApprovalML instance.

## Expose a Workflow Directory as MCP

Point the MCP server at a directory of workflow YAML files and every one of them becomes a callable tool — no per-server wrapping, no upstream process to spawn, no classification heuristics. `approvalml` parses each file, registers it with the runtime, and exposes `submit_<name>` with an `inputSchema` generated straight from that workflow's `form.fields`:

```bash
export APPROVALML_API_URL=http://localhost:8765
export APPROVALML_API_TOKEN=<your-token>
export APPROVALML_WORKFLOWS_DIR=./workflows
approvalml mcp-server
```

Or via Claude Desktop config:

```json
{
  "mcpServers": {
    "approvalml": {
      "command": "approvalml",
      "args": ["mcp-server"],
      "env": {
        "APPROVALML_API_URL": "http://localhost:8765",
        "APPROVALML_API_TOKEN": "your-token-here",
        "APPROVALML_WORKFLOWS_DIR": "/absolute/path/to/workflows"
      }
    }
  }
}
```

`./workflows/purchase-request.yaml` becomes the tool `submit_purchase_request`, with required/optional fields, `select`/`multiselect` enums, and types all derived from the YAML — the agent never sees a bare, untyped JSON blob. Calling it validates required fields and submits exactly like the REST API; the agent gets back an `instance_id` to poll with `check_approval_status`, same as `request_approval`. Field types not meant for programmatic input (`calculated`, `readonly`, `jsonata`, `hidden`, `label`, `image`) are excluded from the schema automatically.

## Scheduled Workflows

A workflow's own `triggers:` block (the same syntax used on Aptiwise SaaS) can declare a cron schedule — but registering it never starts the clock. Every trigger ships **disabled**; arming one is a separate, governed, audited act:

```yaml
name: "Daily CVE Risk Scan"

triggers:
  - type: cron
    schedule: "0 2 * * *"
    preset_form_data:
      manifest_path: "requirements.txt"
      severity_threshold: "critical"

form:
  fields:
    - name: manifest_path
      type: text
    - name: severity_threshold
      type: select
      options: [critical, high, medium]

workflow:
  # ...
```

`preset_form_data` is the standing input a scheduled run submits with — `form.fields` stays the schema used to validate it (and to drive an ad-hoc manual run of the same workflow). The runtime's own `WorkflowScheduler` — not the agent — owns every tick: it polls for due triggers, submits the run, records success/failure to the audit log, and auto-disables a trigger after 5 consecutive failures rather than looping on a broken schedule forever.

MCP tools for the schedule's management plane — configure and observe, never fire a tick directly:

| Tool | What it does |
|---|---|
| `register_workflow` | Register/replace a workflow YAML by name. New triggers land disabled. |
| `list_workflows` | List every registered workflow with a trigger summary. |
| `get_schedule_status` | Per-trigger enabled/next_run/last_status/consecutive_failures. |
| `set_schedule_enabled` | Arm or disarm one trigger. Requires the admin token; always pass a `reason` — it's written to the audit log with the calling identity. |
| `run_now` | Submit a workflow immediately as an explicit, recorded manual override — distinct from a scheduler tick, doesn't touch the cron schedule. |

There is deliberately no "fire this trigger" tool. If an agent had to call something on a cadence to keep a scheduled workflow running, every failure mode that cadence is supposed to protect against — a crashed process, an expired token, an agent that reasons itself out of the loop — comes back, with no recorded miss. The agent may arm the control and watch it run; the ticking stays inside the runtime.

## External Data Fetches (`automatic` steps)

An `automatic` step's `data_processor.source_name` can resolve against a workflow's own top-level `sources:` registry instead of a database — the standalone runtime's stand-in for Aptiwise SaaS's `data_connectors`/`data_sources` tables:

```yaml
sources:
  vendor_po:
    connector:
      type: rest_api
      base_url: "${env.VENDOR_BASE_URL}"
      auth: { type: bearer, token: "${env.VENDOR_TOKEN}" }
    source:
      endpoint: "/pos/{po_id}"
      method: GET

workflow:
  match_po:
    name: match_po
    type: automatic
    data_processor:
      source_name: vendor_po
      save_to: po
      params:
        - name: po_id
          from_field: field.po_number
    on_complete:
      continue_to: manager_review
    on_failure:
      continue_to: manual_review
```

Credentials are environment references (`${env.VENDOR_TOKEN}`) — the standalone runtime's equivalent of a reusable, named connector credential. Promoting a workflow to Aptiwise SaaS is a literal copy: the `connector:` object becomes a `data_connectors` row, `source:` becomes a `data_sources` row, and the `sources:` block is deleted — the `workflow:` section itself never changes. `source_id` (a DB-managed data source) and `api:` connector actions both require SaaS-only infrastructure and are rejected with a clear error, same as before this feature existed.

---

## Standalone Runtime

A self-contained approval server backed by PostgreSQL and SMTP. No SaaS account needed.

### Quick start (Docker)

```bash
cd packages/approvalml    # or wherever you cloned the repo
cp .env.example .env      # edit APPROVALML_API_TOKEN and APPROVALML_SERVER_URL
docker compose up -d
```

The runtime starts on `http://localhost:8765`. Drop `*.yaml` workflow files into `./workflows/` and they are loaded into the database on startup.

### Multi-user token provisioning

Each user or AI agent gets their own token. The server records `submitter_email` on every gate and workflow instance automatically — no need to pass an email in the request.

**User tokens vs. the master token:**

| Token | Sees | Can register workflows |
|---|---|---|
| `APPROVALML_API_TOKEN` (master) | All gates and instances | Yes |
| `awat_…` (user token) | Own submissions only | No |

#### Method 1 — API (recommended for runtime management)

Create a token for a user with the master token:

```bash
curl -X POST http://localhost:8765/services/v1/tokens \
  -H "Authorization: Bearer $APPROVALML_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "name": "Alice"}'

# {"token": "awat_abc123...", "email": "alice@example.com", "name": "Alice"}
```

List all tokens:

```bash
curl http://localhost:8765/services/v1/tokens \
  -H "Authorization: Bearer $APPROVALML_API_TOKEN"
```

Revoke a token:

```bash
curl -X DELETE http://localhost:8765/services/v1/tokens/awat_abc123... \
  -H "Authorization: Bearer $APPROVALML_API_TOKEN"
```

#### Method 2 — Environment variable (seed at startup)

Set `APPROVALML_TOKENS` in your `.env` file before starting Docker:

```bash
# .env
APPROVALML_TOKENS=awat_abc123:alice@example.com:Alice,awat_xyz789:bob@example.com:Bob
```

Format: `token:email` or `token:email:display name`, comma-separated. Tokens that already exist in the database are skipped (idempotent).

#### Method 3 — Pre-generated tokens in `.env` (simple teams)

Generate tokens yourself and seed them:

```bash
# Generate a token
python -c "import secrets; print('awat_' + secrets.token_urlsafe(32))"
# awat_T3n...

# Add to .env
echo "APPROVALML_TOKENS=awat_T3n...:alice@example.com" >> .env
docker compose restart runtime
```

### Configuring each AI agent

Each person running Claude Desktop gets their own token in their MCP config:

```json
{
  "mcpServers": {
    "approvalml": {
      "command": "approvalml",
      "args": ["mcp-server"],
      "env": {
        "APPROVALML_API_URL": "http://your-server:8765",
        "APPROVALML_API_TOKEN": "awat_abc123..."
      }
    }
  }
}
```

Alice's agent submits with `alice@example.com` as the submitter. `list_pending_approvals` returns only Alice's pending gates — not Bob's.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `APPROVALML_API_TOKEN` | _(empty)_ | Master/admin token. Unset = open access (dev only). |
| `APPROVALML_TOKENS` | _(empty)_ | Seed user tokens at startup: `token:email,token:email:Name` |
| `DATABASE_URL` | `postgresql://approvalml:approvalml@localhost:5432/approvalml` | PostgreSQL DSN |
| `APPROVALML_SERVER_URL` | `http://localhost:8765` | Public URL embedded in email approve/reject links |
| `WORKFLOWS_DIR` | _(empty)_ | Directory of `*.yaml` files loaded into DB on startup (server-side) |
| `APPROVALML_WORKFLOWS_DIR` | _(empty)_ | Directory of `*.yaml` files exposed as `submit_<name>` MCP tools (mcp-server-side) — see [Expose a Workflow Directory as MCP](#expose-a-workflow-directory-as-mcp) |
| `APPROVALML_SCHEDULER_POLL_INTERVAL` | `30` | Seconds between WorkflowScheduler ticks |
| `APPROVALML_SCHEDULER_MAX_FAILURES` | `5` | Consecutive failed runs before a trigger is auto-disabled |
| `SMTP_HOST` | _(empty)_ | SMTP server. Leave blank to print emails to stdout. |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | _(empty)_ | SMTP username |
| `SMTP_PASSWORD` | _(empty)_ | SMTP password |
| `EMAIL_FROM` | `approvalml@localhost` | Sender address |
| `APPROVALML_ROLE_<NAME>` | _(empty)_ | Comma-separated approver emails for role `<NAME>` in workflow YAML — see [Approver Roles](#approver-roles) |

### Approver Roles

A bare role name in `approver:` (e.g. `approver: finance_manager`) or in the `approvers:` list form (e.g. `- role: finance_manager`) resolves through an environment variable: `APPROVALML_ROLE_FINANCE_MANAGER=alice@example.com,bob@example.com`. The name is uppercased and non-alphanumeric characters become underscores (`finance manager` → `APPROVALML_ROLE_FINANCE_MANAGER`); the value is a comma-separated list of approver emails.

This is a static, opt-in substitute for Aptiwise's organization-based role resolution — no org hierarchy, no per-department scoping, just a fixed name-to-emails mapping. A role with no matching environment variable raises a clear validation error rather than silently creating a step with zero approvers.

### Audit Trail

Every approval action — gate/instance/step creation, decisions, and parallel-step auto-skips — is written to a single `audit_log` table as a SHA-256 hash-chained entry, not just the plain `decided_by`/`decided_at` fields already on each row.

The chain is **global**, not scoped per gate or instance: each entry's `prev_hash` is the hash of whatever entry was written immediately before it, across the whole deployment. Tampering with any row — anywhere, from any point in the deployment's history — breaks verification for every entry after it.

Verify the chain:

```bash
approvalml verify-audit --db-url postgresql://approvalml:approvalml@localhost:5432/approvalml
```

Or over HTTP:

```bash
curl -H "Authorization: Bearer $APPROVALML_API_TOKEN" \
  http://localhost:8765/services/v1/audit/verify

curl -H "Authorization: Bearer $APPROVALML_API_TOKEN" \
  http://localhost:8765/services/v1/approvals/<gate-or-instance-id>/audit-log
```

---

## Python API

```python
from approvalml import parse_approvalml_file, parse_approvalml

# From a file
workflow, summary = parse_approvalml_file("leave-request.yaml")
if workflow:
    print(workflow.name)          # "Employee Leave Request"
    print(workflow.workflow.keys()) # step names
else:
    print(summary["errors"])

# From a YAML string
yaml_text = open("my-workflow.yaml").read()
workflow, summary = parse_approvalml(yaml_text)
```

## Example Workflow

> [!NOTE]
> The open-source standalone runtime has no company directory, so requestor-based hierarchy resolution (e.g., `${requestor.manager}`) isn't supported.
>
> Assign step approvers using direct email strings (e.g., `approver: manager@example.com`), a form field email template (e.g., `approver: "${form.manager_email}"`), or a role name (e.g., `approver: finance_manager`) resolved via `APPROVALML_ROLE_FINANCE_MANAGER=email1,email2` in your environment — see [Approver Roles](#approver-roles) below.

```yaml
name: "Leave Request"
description: "Simple leave approval"

form:
  fields:
    - name: "leave_type"
      type: "select"
      label: "Type of Leave"
      required: true
      options:
        - value: "vacation"
          label: "Vacation"
        - value: "sick"
          label: "Sick Leave"

    - name: "total_days"
      type: "number"
      label: "Total Days"
      required: true

    - name: "manager_email"
      type: "text"
      label: "Manager Email"
      required: true

workflow:
  manager_approval:
    name: "manager_approval"
    type: "decision"
    approver: "${form.manager_email}"
    on_approve:
      continue_to: "done"
    on_reject:
      end_workflow: true

  done:
    name: "done"
    type: "end"
    notify_requestor: "Leave request approved"
```

## Generate Workflows with AI

The fastest way to create a workflow is to describe it in plain English using any AI assistant.

### Quick start (any AI)

1. Open [`PROMPT.md`](./PROMPT.md) and copy the full contents
2. Paste it at the start of a new ChatGPT, Claude, or Gemini conversation
3. Describe your workflow:

> *"Create a 3-level purchase approval workflow. Amounts under $1,000 go to the department manager only. Amounts over $1,000 require the department manager then finance director. Include fields for item description, amount, supplier, and justification."*

4. Copy the generated YAML, save it, and validate:

```bash
approvalml validate my-workflow.yaml
```

### Custom AI assistants

For a persistent assistant that always knows the ApprovalML syntax without pasting:

| Platform | How |
|----------|-----|
| **ChatGPT Custom GPT** | Instructions → paste system prompt from `PROMPT.md` · Knowledge → upload `PROMPT.md` |
| **Gemini Gem** | Instructions → paste system prompt from `PROMPT.md` · upload `PROMPT.md` as context |
| **Claude Project** | Add `PROMPT.md` to Project Knowledge — available in every conversation |

---

## Example Templates

Browse ready-to-use workflow templates in the [`examples/`](./examples) folder:

| Category | Template |
|----------|----------|
| HR | [Leave Request](examples/hr/leave-request.yaml) |
| HR | [Pre-screening Interview](examples/hr/pre-screening-interview.yaml) |
| Finance | [Purchase Request](examples/finance/purchase-request.yaml) |
| Finance | [Expense Approval](examples/finance/expense-approval.yaml) |
| Finance | [Invoice Processing](examples/finance/invoice-processing.yaml) |
| IT | [Equipment Request](examples/it/equipment-request.yaml) |
| Procurement | [Vendor Purchase Order](examples/procurement/vendor-purchase-order.yaml) |
| Procurement | [Purchase Order with Signature](examples/procurement/purchase-order-with-signature.yaml) |

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
