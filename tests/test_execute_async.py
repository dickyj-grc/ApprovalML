import pytest
from pydantic import ValidationError

from approvalml.parser import WorkflowStep, StepType


def test_execute_async_with_data_processor_is_valid():
    # @lat: [[workflow-engine#Live feedback for async automatic steps#execute_async is accepted alongside data_processor]]
    """execute_async: true is meaningful when there's a data_processor fetch to dispatch."""
    step = WorkflowStep(
        name="Fetch",
        type=StepType.AUTOMATIC,
        data_processor={"source_id": "1", "save_to": "result"},
        execute_async=True,
    )
    assert step.execute_async is True


def test_execute_async_without_data_processor_is_rejected():
    # @lat: [[workflow-engine#Live feedback for async automatic steps#execute_async without a data fetch is rejected]]
    """execute_async: true with no data_processor has nothing to dispatch — a currently-silent
    footgun the validator now catches at parse time instead."""
    with pytest.raises(ValidationError, match="execute_async"):
        WorkflowStep(
            name="Map",
            type=StepType.AUTOMATIC,
            field_mapping={"a": "$.a"},
            execute_async=True,
        )


def test_execute_async_omitted_is_valid():
    # @lat: [[workflow-engine#Live feedback for async automatic steps#execute_async defaults to None/falsy without requiring data_processor]]
    """Omitting execute_async entirely must not trip the new guard for any automatic step shape."""
    step = WorkflowStep(name="Map", type=StepType.AUTOMATIC, field_mapping={"a": "$.a"})
    assert not step.execute_async
