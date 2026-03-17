# ApprovalML

YAML-based approval workflow parser and validator.

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
