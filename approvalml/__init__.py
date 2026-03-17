"""
ApprovalML - YAML-based approval workflow parser and validator.

Quick start:
    from approvalml import parse_approvalml, parse_approvalml_file

    workflow, summary = parse_approvalml_file("my-workflow.yaml")
    if workflow:
        print(f"Valid: {workflow.name}")
    else:
        print("Errors:", summary["errors"])
"""

from .parser import (
    ApprovalMLParser,
    ApprovalProcess,
    parse_approvalml,
    parse_approvalml_file,
)

__version__ = "0.1.0"

__all__ = [
    "ApprovalMLParser",
    "ApprovalProcess",
    "parse_approvalml",
    "parse_approvalml_file",
]
