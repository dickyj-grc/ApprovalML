"""
Validates all example YAML files against the ApprovalML parser.

Run with: pytest tests/test_examples.py
"""

import glob
import pytest
import yaml
from approvalml import parse_approvalml_file


def get_all_examples():
    return glob.glob("examples/**/*.yaml", recursive=True)


@pytest.mark.parametrize("path", get_all_examples())
def test_example_parses_successfully(path):
    """Every file in examples/ must parse without errors."""
    workflow, summary = parse_approvalml_file(path)
    errors = summary.get("errors", [])
    assert workflow is not None, f"{path} failed to parse:\n" + "\n".join(f"  • {e}" for e in errors)


@pytest.mark.parametrize("path", get_all_examples())
def test_example_has_name(path):
    """Every example must have a workflow name."""
    workflow, _ = parse_approvalml_file(path)
    if workflow:
        assert workflow.name, f"{path}: workflow is missing a 'name' field"


@pytest.mark.parametrize("path", get_all_examples())
def test_example_has_workflow_steps(path):
    """Every example must define at least one workflow step."""
    workflow, _ = parse_approvalml_file(path)
    if workflow:
        steps = workflow.workflow or {}
        assert len(steps) > 0, f"{path}: workflow has no steps defined"
