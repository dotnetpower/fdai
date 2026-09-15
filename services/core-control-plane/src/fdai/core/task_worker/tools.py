"""Read-only dispatch boundary for isolated task workers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
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


class TaskWorkerPlanningBudgetError(TaskWorkerBudgetExhaustedError):
    """A prepared model request cannot fit the immutable worker budget."""


class TaskWorkerToolGateway:
    def __init__(
        self,
        *,
        tools: tuple[TaskWorkerTool, ...],
        capabilities: AttenuatedCapabilities,
        budget: TaskWorkerBudget,
        usage_checkpoint: Callable[[TaskWorkerUsage], Awaitable[None]] | None = None,
    ) -> None:
        if len({tool.name for tool in tools}) != len(tools):
            raise ValueError("worker tool names MUST be unique")
        self._tools = {tool.name: tool for tool in tools}
        self._capabilities = capabilities
        self._budget = budget
        self._tool_calls = 0
        self._evidence_refs: list[str] = []
        self._planning_usage = TaskWorkerUsage()
        self._planning_reserved = False
        self._usage_checkpoint = usage_checkpoint
        self._usage_lock = asyncio.Lock()

    @property
    def usage(self) -> TaskWorkerUsage:
        return replace(self._planning_usage, tool_calls=self._tool_calls)

    @property
    def has_usage_checkpoint(self) -> bool:
        return self._usage_checkpoint is not None

    async def reserve_planning(self, *, tokens: int, cost_microusd: int) -> None:
        """Persist one unresolved allowance before the provider may dispatch."""
        async with self._usage_lock:
            reservation = TaskWorkerUsage(
                reserved_tokens=tokens,
                reserved_cost_microusd=cost_microusd,
                complete=False,
                tool_calls=self._tool_calls,
            )
            if self._planning_reserved or not reservation.within(self._budget):
                raise TaskWorkerPlanningBudgetError("worker planning allowance is unavailable")
            self._planning_reserved = True
            self._planning_usage = reservation
            await self._checkpoint()

    async def record_planning_usage(self, *, tokens: int, cost_microusd: int) -> None:
        """Replace a reservation only with explicit measured provider usage."""
        async with self._usage_lock:
            self._planning_usage = TaskWorkerUsage(tokens=tokens, cost_microusd=cost_microusd)
            await self._checkpoint()

    async def checkpoint_usage(self) -> None:
        """Serialize heartbeat writes with reservations so stale usage cannot erase them."""
        async with self._usage_lock:
            await self._checkpoint()

    async def _checkpoint(self) -> None:
        if self._usage_checkpoint is not None:
            await self._usage_checkpoint(self.usage)

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
        await self.checkpoint_usage()
        result = await tool.call(arguments)
        self._evidence_refs.extend(result.evidence_refs)
        return result


__all__ = [
    "TaskWorkerBudgetExhaustedError",
    "TaskWorkerPlanningBudgetError",
    "TaskWorkerTool",
    "TaskWorkerToolDeniedError",
    "TaskWorkerToolGateway",
]
