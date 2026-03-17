"""
ApprovalML CLI - Validate and inspect ApprovalML workflow YAML files.

Usage:
    approvalml validate <file>
    approvalml validate <file> --verbose
    approvalml info <file>
"""

import sys
import argparse
from approvalml import parse_approvalml_file


def cmd_validate(args):
    """Validate an ApprovalML YAML file."""
    workflow, summary = parse_approvalml_file(args.file)

    if workflow:
        print(f"✓ Valid: {workflow.name}")
        if args.verbose:
            steps = list(workflow.workflow.keys()) if workflow.workflow else []
            fields = list(workflow.form.keys()) if workflow.form else []
            print(f"  Description : {workflow.description or '—'}")
            print(f"  Steps       : {len(steps)} — {', '.join(steps)}")
            print(f"  Form fields : {len(fields)} — {', '.join(fields)}")
            if summary.get("warnings"):
                print(f"  Warnings    : {len(summary['warnings'])}")
                for w in summary["warnings"]:
                    print(f"    ⚠ {w}")
        return 0
    else:
        print(f"✗ Invalid: {args.file}", file=sys.stderr)
        for error in summary.get("errors", []):
            print(f"  • {error}", file=sys.stderr)
        return 1


def cmd_info(args):
    """Print a summary of a workflow file."""
    workflow, summary = parse_approvalml_file(args.file)

    if not workflow:
        print(f"✗ Could not parse: {args.file}", file=sys.stderr)
        for error in summary.get("errors", []):
            print(f"  • {error}", file=sys.stderr)
        return 1

    steps = workflow.workflow or {}
    fields = workflow.form or {}

    print(f"\n{workflow.name}")
    print(f"{'─' * len(workflow.name)}")
    if workflow.description:
        print(f"{workflow.description}\n")

    print(f"Form fields ({len(fields)}):")
    for field_name, field in fields.items():
        required = "required" if field.required else "optional"
        print(f"  {field_name:<25} {field.type:<15} {required}")

    print(f"\nWorkflow steps ({len(steps)}):")
    for name, step in steps.items():
        print(f"  {name:<25} {step.type}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="ApprovalML workflow validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate command
    p_validate = subparsers.add_parser("validate", help="Validate a workflow YAML file")
    p_validate.add_argument("file", help="Path to the YAML workflow file")
    p_validate.add_argument("-v", "--verbose", action="store_true", help="Show step and field details")
    p_validate.set_defaults(func=cmd_validate)

    # info command
    p_info = subparsers.add_parser("info", help="Print a summary of a workflow file")
    p_info.add_argument("file", help="Path to the YAML workflow file")
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
