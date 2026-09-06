"""Carry a turn's resource ceiling through synchronous planners into async providers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol

from .model_observation import ConversationModelObservation


class AdaptiveBudgetExceededError(RuntimeError):
    """Stop provider work without granting a retry or execution authority."""


class ModelCallBudget(Protocol):
    """Account for provider attempts against one owning conversation budget."""

    def reserve(self, input_bytes: int, output_tokens: int, reserved_calls: int) -> int:
        """Charge a conservative reservation before a provider request."""
        ...

    def observe(self, reservation: int, observation: ConversationModelObservation) -> None:
        """Reconcile charged usage without discarding failed-attempt reservations."""
        ...


@dataclass(frozen=True, slots=True)
class ModelCallReservation:
    """An already-charged attempt, completed with content-free measured usage."""

    budget: ModelCallBudget
    amount: int

    def record(self, observation: ConversationModelObservation) -> None:
        """Preserve measured usage and reject an over-budget result."""
        self.budget.observe(self.amount, observation)


class _CallScope:
    def __init__(self, budget: ModelCallBudget, reserved_calls: int) -> None:
        self.budget = budget
        self.reserved_calls = reserved_calls
        self.closed = False
        self.tasks: set[asyncio.Future[Any]] = set()

    def check(self) -> None:
        if self.closed:
            raise AdaptiveBudgetExceededError("adaptive provider scope has ended")

    async def run[Result](self, operation: Callable[[], Awaitable[Result]]) -> Result:
        self.check()
        task = asyncio.ensure_future(operation())
        self.tasks.add(task)
        try:
            return await task
        finally:
            self.tasks.discard(task)

    async def close(self) -> None:
        self.closed = True
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


_SCOPE: ContextVar[_CallScope | None] = ContextVar("adaptive_model_call_scope", default=None)


@asynccontextmanager
async def bind_adaptive_model_budget(
    budget: ModelCallBudget,
    *,
    reserved_calls: int = 0,
) -> AsyncIterator[None]:
    """Bind one read's budget and drain its provider work on completion or cancellation."""
    scope = _CallScope(budget, reserved_calls)
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        _SCOPE.reset(token)
        await scope.close()


async def run_scoped_model[Result](operation: Callable[[], Awaitable[Result]]) -> Result:
    """Track real async provider work even when a synchronous planner initiated it."""
    scope = _SCOPE.get()
    if scope is None:
        return await operation()
    return await scope.run(operation)


async def call_scoped_provider[Result](
    operation: Callable[[], Awaitable[Result]],
    *,
    request: Mapping[str, object],
    output_tokens: int,
) -> tuple[Result, ModelCallReservation | None]:
    """Reserve each physical request; any failed request ends this read's retry scope."""
    scope = _SCOPE.get()
    if scope is None:
        return await operation(), None
    scope.check()
    size = len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode())
    amount = scope.budget.reserve(size, output_tokens, scope.reserved_calls)
    reservation = ModelCallReservation(scope.budget, amount)
    completed = False
    try:
        result = await operation()
        completed = True
        return result, reservation
    finally:
        if not completed:
            scope.closed = True


def stop_scoped_provider_retry() -> bool:
    """Suppress legacy provider failover only inside a bounded adaptive read."""
    scope = _SCOPE.get()
    if scope is None:
        return False
    scope.closed = True
    return True
