# ApprovalML

YAML-based approval workflow parser and validator.

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
| `ffat_…` (user token) | Own submissions only | No |

#### Method 1 — API (recommended for runtime management)

Create a token for a user with the master token:

```bash
curl -X POST http://localhost:8765/services/v1/tokens \
  -H "Authorization: Bearer $APPROVALML_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "name": "Alice"}'

# {"token": "ffat_abc123...", "email": "alice@example.com", "name": "Alice"}
```

List all tokens:

```bash
curl http://localhost:8765/services/v1/tokens \
  -H "Authorization: Bearer $APPROVALML_API_TOKEN"
```

Revoke a token:

```bash
curl -X DELETE http://localhost:8765/services/v1/tokens/ffat_abc123... \
  -H "Authorization: Bearer $APPROVALML_API_TOKEN"
```

#### Method 2 — Environment variable (seed at startup)

Set `APPROVALML_TOKENS` in your `.env` file before starting Docker:

```bash
# .env
APPROVALML_TOKENS=ffat_abc123:alice@example.com:Alice,ffat_xyz789:bob@example.com:Bob
```

Format: `token:email` or `token:email:display name`, comma-separated. Tokens that already exist in the database are skipped (idempotent).

#### Method 3 — Pre-generated tokens in `.env` (simple teams)

Generate tokens yourself and seed them:

```bash
# Generate a token
python -c "import secrets; print('ffat_' + secrets.token_urlsafe(32))"
# ffat_T3n...

# Add to .env
echo "APPROVALML_TOKENS=ffat_T3n...:alice@example.com" >> .env
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
        "APPROVALML_API_TOKEN": "ffat_abc123..."
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
| `WORKFLOWS_DIR` | _(empty)_ | Directory of `*.yaml` files loaded into DB on startup |
| `SMTP_HOST` | _(empty)_ | SMTP server. Leave blank to print emails to stdout. |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | _(empty)_ | SMTP username |
| `SMTP_PASSWORD` | _(empty)_ | SMTP password |
| `EMAIL_FROM` | `approvalml@localhost` | Sender address |

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

workflow:
  manager_approval:
    name: "manager_approval"
    type: "decision"
    approver: "${requestor.manager}"
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
