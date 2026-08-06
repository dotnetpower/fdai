"""Injected boundary for Thor-owned execution inside the Core process.

Responsibility: expose the existing PR-native, direct-API, and tool-call
execution surfaces as one composition input.
Boundary: this module defines no transport and performs no routing or effects;
callers continue to use the existing executor contracts and result types.
Authority and state: Thor remains the sole execution owner. The bound executors
retain Saga audit persistence, Vidar recovery, shadow, lock, and idempotency
behavior without sharing mutable state through this port.
Dependencies: only the Core executor surfaces are accepted.
Deployment: ``InProcessThorExecutionPort`` is the rollback-compatible Core
binding and does not create a network or process boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fdai.core.executor.direct_api import (
    DirectApiExecutionResult,
    DirectApiShadowExecutor,
)
from fdai.core.executor.executor import ExecutionResult, ShadowExecutor
from fdai.core.executor.tool_call import (
    ToolCallExecutionResult,
    ToolCallShadowExecutor,
)
from fdai.shared.contracts.models import Action, Rule


class _PrNativeExecutionPort(Protocol):
    async def execute(self, *, action: Action, rule: Rule) -> ExecutionResult: ...


class _DirectApiExecutionPort(Protocol):
    async def execute(self, *, action: Action) -> DirectApiExecutionResult: ...


class _ToolCallExecutionPort(Protocol):
    async def execute(self, *, action: Action) -> ToolCallExecutionResult: ...


@runtime_checkable
class ThorExecutionPort(Protocol):
    """Composition contract for Thor's three existing execution paths.

    The port owns no authority or state. Implementations supply the same
    executor instances to every in-process consumer so HIL resume and normal
    dispatch share audit, recovery, lock, and idempotency behavior.
    """

    @property
    def pr_native(self) -> _PrNativeExecutionPort:
        """Return the required PR-native execution surface."""
        ...

    @property
    def direct_api(self) -> _DirectApiExecutionPort | None:
        """Return the optional direct-API execution surface."""
        ...

    @property
    def tool_call(self) -> _ToolCallExecutionPort | None:
        """Return the optional tool-call execution surface."""
        ...


@dataclass(frozen=True, slots=True)
class InProcessThorExecutionPort:
    """Bind the existing Thor executors without adding transport or authority."""

    pr_native: ShadowExecutor
    direct_api: DirectApiShadowExecutor | None = None
    tool_call: ToolCallShadowExecutor | None = None


__all__ = ["InProcessThorExecutionPort", "ThorExecutionPort"]
