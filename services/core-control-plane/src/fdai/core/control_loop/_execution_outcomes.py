"""Control-loop adapters for provider-neutral execution outcomes."""

from __future__ import annotations

from typing import Any

from fdai.core.executor import ExecutionResult
from fdai.core.executor.direct_api import DirectApiExecutionResult
from fdai.core.executor.tool_call import ToolCallExecutionResult
from fdai.shared.contracts.execution_outcomes import (
    execution_outcome_is_no_effect,
    execution_outcome_is_pending,
)

ExecutionResultType = ExecutionResult | DirectApiExecutionResult | ToolCallExecutionResult | Any


def is_execution_pending(result: ExecutionResultType) -> bool:
    """Return whether an attempted effect still needs authoritative closure."""

    return hasattr(result, "outcome") and execution_outcome_is_pending(result.outcome)


def is_execution_no_effect(result: ExecutionResultType) -> bool:
    """Return whether the current attempt provably reached no effect boundary."""

    return hasattr(result, "outcome") and execution_outcome_is_no_effect(result.outcome)


__all__ = ["is_execution_no_effect", "is_execution_pending"]
