"""Carry a turn's resource ceiling through synchronous planners into async providers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol

from .model_call_progress import model_call_ended, model_call_started
from .model_observation import ConversationModelObservation
from .turn_reservations import StageReservation, fail_call, reconcile_call, reserve_call


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

    budget: ModelCallBudget | None
    amount: int
    turn: StageReservation | None = None

    def record(self, observation: ConversationModelObservation) -> None:
        """Preserve measured usage and reject an over-budget result."""
        reconcile_call(self.turn, observation.usage)
        if self.budget is not None:
            self.budget.observe(self.amount, observation)


class _CallScope:
    def __init__(self, budget: ModelCallBudget | None, reserved_calls: int) -> None:
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


@asynccontextmanager
async def bind_model_call_scope() -> AsyncIterator[None]:
    """Track cancellable provider work without changing ordinary retry policy."""
    parent = _SCOPE.get()
    scope = _CallScope(
        parent.budget if parent is not None else None,
        parent.reserved_calls if parent is not None else 0,
    )
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
    stage: str | None = None,
    model: str | None = None,
) -> tuple[Result, ModelCallReservation | None]:
    """Reserve each physical request; any failed request ends this read's retry scope.

    ``stage`` is the adapter's reviewed call label. Under a bound turn ledger the call
    first reserves its stage's worst case, and a stage that can't reserve raises the
    typed hold before anything is sent. ``model`` names the deployment for the content-free
    progress report an invocation may observe.
    """
    scope = _SCOPE.get()
    if scope is not None:
        scope.check()
    budget = scope.budget if scope is not None else None
    size = (
        len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode())
        if budget is not None or stage
        else 0
    )
    turn = reserve_call(stage, input_bytes=size, output_tokens=output_tokens) if stage else None
    if scope is None or budget is None:
        progress = model_call_started(stage, model)
        try:
            result = await operation()
        except BaseException:
            model_call_ended(progress, failed=True)
            fail_call(turn)
            raise
        model_call_ended(progress, failed=False)
        return result, ModelCallReservation(None, 0, turn) if turn is not None else None
    try:
        amount = budget.reserve(size, output_tokens, scope.reserved_calls)
    except BaseException:
        fail_call(turn)
        raise
    reservation = ModelCallReservation(budget, amount, turn)
    completed = False
    progress = model_call_started(stage, model)
    try:
        result = await operation()
        completed = True
        return result, reservation
    finally:
        model_call_ended(progress, failed=not completed)
        if not completed:
            fail_call(turn)
            scope.closed = True


def stop_scoped_provider_retry() -> bool:
    """Suppress legacy provider failover only inside a bounded adaptive read."""
    scope = _SCOPE.get()
    if scope is None or scope.budget is None:
        return False
    scope.closed = True
    return True
