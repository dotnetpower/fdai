"""Injected boundary for Thor-owned execution inside the Core process.

Responsibility: expose the existing PR-native, direct-API, and tool-call
execution surfaces as one composition input.
Boundary: this module defines no transport and performs no routing or effects;
callers continue to use the existing executor contracts and result types.
Safety readiness is immutable composition evidence, not an audit or recovery
callback.
Authority and state: Thor remains the sole execution owner. The bound executors
retain Saga audit persistence, Vidar recovery, shadow, lock, and idempotency
behavior without sharing mutable state through this port.
Dependencies: only Core executor surfaces and primitive readiness facts are
accepted; agent implementations are not imported.
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


@dataclass(frozen=True, slots=True)
class MutationDependencyReadiness:
    """Record whether Thor's existing Saga and Vidar bindings permit mutation."""

    saga_audit_durable: bool
    vidar_recovery_contracts: frozenset[str]

    @property
    def mutation_ready(self) -> bool:
        """Return true only when durable audit and recovery are both bound."""
        return self.saga_audit_durable and bool(self.vidar_recovery_contracts)

    def require_for_mode(self, *, enforce: bool) -> None:
        """Reject mutation when either hard dependency is unavailable.

        Shadow composition remains valid without either binding because it
        performs no mutation.
        """
        if not enforce or self.mutation_ready:
            return
        missing: list[str] = []
        if not self.saga_audit_durable:
            missing.append("durable_saga")
        if not self.vidar_recovery_contracts:
            missing.append("rollback_executors")
        raise ValueError(
            "Thor mutation requires explicit durable safety bindings: " + ", ".join(missing)
        )


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


ThorSafetyDependencyReadiness = MutationDependencyReadiness


__all__ = [
    "InProcessThorExecutionPort",
    "MutationDependencyReadiness",
    "ThorExecutionPort",
    "ThorSafetyDependencyReadiness",
]
