"""Read-only dispatch boundary for isolated task workers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from fdai.core.task_worker.models import (
    AttenuatedCapabilities,
    TaskWorkerBudget,
    TaskWorkerToolResult,
    TaskWorkerUsage,
)


class TaskWorkerTool(Protocol):
    name: str
    side_effect_class: str

    async def call(self, arguments: Mapping[str, str]) -> TaskWorkerToolResult: ...


class TaskWorkerToolDeniedError(PermissionError):
    """A worker attempted a tool outside its attenuated read-only profile."""


class TaskWorkerBudgetExhaustedError(RuntimeError):
    """A worker attempted to exceed a fixed usage budget."""


class TaskWorkerToolGateway:
    def __init__(
        self,
        *,
        tools: tuple[TaskWorkerTool, ...],
        capabilities: AttenuatedCapabilities,
        budget: TaskWorkerBudget,
    ) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._capabilities = capabilities
        self._budget = budget
        self._tool_calls = 0
        self._evidence_refs: list[str] = []

    @property
    def usage(self) -> TaskWorkerUsage:
        return TaskWorkerUsage(tool_calls=self._tool_calls)

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self._evidence_refs))

    async def invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, str],
    ) -> TaskWorkerToolResult:
        tool = self._tools.get(tool_name)
        if (
            tool_name not in self._capabilities.allowed_tools
            or tool is None
            or tool.side_effect_class != "read"
        ):
            raise TaskWorkerToolDeniedError(f"worker tool {tool_name!r} is not allowed")
        if self._tool_calls >= self._budget.max_tool_calls:
            raise TaskWorkerBudgetExhaustedError("worker tool-call budget exhausted")
        self._tool_calls += 1
        result = await tool.call(arguments)
        self._evidence_refs.extend(result.evidence_refs)
        return result


__all__ = [
    "TaskWorkerBudgetExhaustedError",
    "TaskWorkerTool",
    "TaskWorkerToolDeniedError",
    "TaskWorkerToolGateway",
]
