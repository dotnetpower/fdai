"""Control-loop adapters for provider-neutral execution outcomes."""

from __future__ import annotations

from typing import Any

from fdai.core.executor import ExecutionResult, ExecutorOutcome
from fdai.core.executor.direct_api import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
)
from fdai.core.executor.tool_call import (
    ToolCallExecutionOutcome,
    ToolCallExecutionResult,
)
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


def is_execution_success(result: ExecutionResultType) -> bool:
    """Return whether dispatch has independent durable effect verification."""

    if not hasattr(result, "outcome"):
        return False
    dispatched = result.outcome in (
        ExecutorOutcome.PUBLISHED,
        ExecutorOutcome.ALREADY_EXISTED,
        DirectApiExecutionOutcome.DISPATCHED,
        DirectApiExecutionOutcome.ALREADY_APPLIED,
        ToolCallExecutionOutcome.DISPATCHED,
        ToolCallExecutionOutcome.ALREADY_APPLIED,
    )
    if not dispatched:
        return False
    return result.audit_context.get("effect_verified") is True


__all__ = ["is_execution_no_effect", "is_execution_pending", "is_execution_success"]
