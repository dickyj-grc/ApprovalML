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
