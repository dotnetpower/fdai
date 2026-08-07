"""Implementation-free contracts for the isolated Executor service boundary."""

from __future__ import annotations

from typing import Protocol

EXECUTOR_COMMAND_TOPIC = "object.executor-command"
EXECUTOR_RECEIPT_TOPIC = "object.executor-receipt"
EXECUTOR_CONSUMER_GROUP = "fdai-isolated-executor-shadow"
CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP = "fdai-isolated-executor-client-core"


class ExecutionOutcomeValue(Protocol):
    """Expose one stable terminal outcome value without owning its enum."""

    @property
    def value(self) -> str:
        """Return the serialized terminal outcome."""

        ...


class DirectApiExecutionResultLike(Protocol):
    """Result shape accepted from a guarded direct-API effect executor."""

    @property
    def action_id(self) -> str: ...

    @property
    def outcome(self) -> ExecutionOutcomeValue: ...

    @property
    def receipt_ref(self) -> str | None: ...

    @property
    def rollback_succeeded(self) -> bool | None: ...

    @property
    def reason(self) -> str | None: ...


__all__ = [
    "CORE_EXECUTOR_RECEIPT_CONSUMER_GROUP",
    "DirectApiExecutionResultLike",
    "EXECUTOR_COMMAND_TOPIC",
    "EXECUTOR_CONSUMER_GROUP",
    "EXECUTOR_RECEIPT_TOPIC",
    "ExecutionOutcomeValue",
]
