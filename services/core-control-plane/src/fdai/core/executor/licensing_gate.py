"""License availability ceiling for Thor's shared execution ports.

The gate checks only whether the catalog's generic mutation capability is
currently available. It cannot promote an ActionType, grant a role, satisfy a
risk or approval decision, or bypass any executor safeguard. Normal dispatch
and HIL resume receive the same wrapped port, so neither path can escape the
check. Entitlement is resolved immediately before every delegate call to make
token expiration effective without a process restart.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol

from fdai.core.executor.direct_api import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
)
from fdai.core.executor.executor import ExecutionResult, ExecutorOutcome
from fdai.core.executor.port import DirectApiExecutionPort, ThorExecutionPort
from fdai.core.executor.tool_call import (
    ToolCallExecutionOutcome,
    ToolCallExecutionResult,
)
from fdai.core.licensing import Entitlement, LicenseEntitlementAuthority
from fdai.shared.contracts.models import Action, ExecutionPath, Rule
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)

MUTATION_CAPABILITY_ID: Final = "operations.typed-mutation"
"""Catalog capability required before any Thor execution path may run."""

_REJECTION_REASON: Final = "acting capabilities are unavailable under the current license"


class _PrNativeExecutionPort(Protocol):
    async def execute(
        self,
        *,
        action: Action,
        rule: Rule,
        execution_path: ExecutionPath = ExecutionPath.PR_NATIVE,
    ) -> ExecutionResult: ...


class _ToolCallExecutionPort(Protocol):
    async def execute(self, *, action: Action) -> ToolCallExecutionResult: ...


@dataclass(frozen=True, slots=True)
class _LicenseGate:
    authority: LicenseEntitlementAuthority
    audit_store: StateStore
    clock: Callable[[], datetime]

    async def rejection_context(
        self,
        *,
        action: Action,
        execution_path: ExecutionPath,
    ) -> dict[str, object] | None:
        """Return and audit a rejection, or return ``None`` when available."""

        checked_at = self.clock()
        entitlement = self.authority.resolve(now=checked_at)
        if MUTATION_CAPABILITY_ID in entitlement.available_capability_ids:
            return None
        context = _audit_context(entitlement, execution_path=execution_path)
        try:
            await self.audit_store.append_audit_entry(
                {
                    "event_id": str(action.event_id),
                    "correlation_id": str(action.event_id),
                    "idempotency_key": action.idempotency_key,
                    "actor": "fdai.licensing",
                    "producer_principal": "Thor",
                    "action_kind": "license.execution_denied",
                    "action_id": str(action.action_id),
                    "action_type_id": action.action_type,
                    "mode": action.mode.value,
                    "decision": "deny",
                    "outcome": "rejected_capability_unavailable",
                    **context,
                    "recorded_at": checked_at.isoformat(),
                }
            )
        except Exception:  # noqa: BLE001 - audit failure cannot weaken or obscure denial
            _LOGGER.error(
                "license_execution_denial_audit_failed",
                extra={
                    "event_id": str(action.event_id),
                    "action_id": str(action.action_id),
                    "action_type_id": action.action_type,
                    "execution_path": execution_path.value,
                },
            )
            return {**context, "audit_persisted": False}
        return {**context, "audit_persisted": True}


def _audit_context(
    entitlement: Entitlement,
    *,
    execution_path: ExecutionPath,
) -> dict[str, object]:
    return {
        "license_status": entitlement.status.value,
        "license_id": entitlement.license_id,
        "license_not_after": (
            entitlement.not_after.isoformat() if entitlement.not_after is not None else None
        ),
        "required_capability_id": MUTATION_CAPABILITY_ID,
        "execution_path": execution_path.value,
    }


@dataclass(frozen=True, slots=True)
class _LicenseGatedPrNativeExecutionPort:
    delegate: _PrNativeExecutionPort
    gate: _LicenseGate

    async def execute(
        self,
        *,
        action: Action,
        rule: Rule,
        execution_path: ExecutionPath = ExecutionPath.PR_NATIVE,
    ) -> ExecutionResult:
        context = await self.gate.rejection_context(
            action=action,
            execution_path=execution_path,
        )
        if context is None:
            return await self.delegate.execute(
                action=action,
                rule=rule,
                execution_path=execution_path,
            )
        return ExecutionResult(
            action_id=str(action.action_id),
            outcome=ExecutorOutcome.REJECTED_CAPABILITY_UNAVAILABLE,
            mode=action.mode,
            reason=_REJECTION_REASON,
            audit_context=context,
        )


@dataclass(frozen=True, slots=True)
class _LicenseGatedDirectApiExecutionPort:
    delegate: DirectApiExecutionPort
    gate: _LicenseGate

    async def execute(self, *, action: Action) -> DirectApiExecutionResult:
        context = await self.gate.rejection_context(
            action=action,
            execution_path=ExecutionPath.DIRECT_API,
        )
        if context is None:
            return await self.delegate.execute(action=action)
        return DirectApiExecutionResult(
            action_id=str(action.action_id),
            outcome=DirectApiExecutionOutcome.REJECTED_CAPABILITY_UNAVAILABLE,
            mode=action.mode,
            reason=_REJECTION_REASON,
            audit_context=context,
        )


@dataclass(frozen=True, slots=True)
class _LicenseGatedToolCallExecutionPort:
    delegate: _ToolCallExecutionPort
    gate: _LicenseGate

    async def execute(self, *, action: Action) -> ToolCallExecutionResult:
        context = await self.gate.rejection_context(
            action=action,
            execution_path=ExecutionPath.TOOL_CALL,
        )
        if context is None:
            return await self.delegate.execute(action=action)
        return ToolCallExecutionResult(
            action_id=str(action.action_id),
            outcome=ToolCallExecutionOutcome.REJECTED_CAPABILITY_UNAVAILABLE,
            mode=action.mode,
            reason=_REJECTION_REASON,
            audit_context=context,
        )


class LicenseGatedThorExecutionPort:
    """Wrap every Thor path with one shared dynamic entitlement check."""

    __slots__ = (
        "_direct_api",
        "_pr_native",
        "_safeguard_lifecycle_ready",
        "_tool_call",
    )

    def __init__(
        self,
        *,
        delegate: ThorExecutionPort,
        authority: LicenseEntitlementAuthority,
        audit_store: StateStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        gate = _LicenseGate(
            authority=authority,
            audit_store=audit_store,
            clock=clock or (lambda: datetime.now(tz=UTC)),
        )
        self._pr_native = _LicenseGatedPrNativeExecutionPort(
            delegate=delegate.pr_native,
            gate=gate,
        )
        self._direct_api = (
            _LicenseGatedDirectApiExecutionPort(delegate=delegate.direct_api, gate=gate)
            if delegate.direct_api is not None
            else None
        )
        self._tool_call = (
            _LicenseGatedToolCallExecutionPort(delegate=delegate.tool_call, gate=gate)
            if delegate.tool_call is not None
            else None
        )
        self._safeguard_lifecycle_ready = delegate.safeguard_lifecycle_ready

    @property
    def safeguard_lifecycle_ready(self) -> bool:
        """Preserve the delegate's immutable safeguard readiness."""

        return self._safeguard_lifecycle_ready

    @property
    def pr_native(self) -> _PrNativeExecutionPort:
        """Return the license-gated PR execution surface."""

        return self._pr_native

    @property
    def direct_api(self) -> DirectApiExecutionPort | None:
        """Return the optional license-gated direct-API surface."""

        return self._direct_api

    @property
    def tool_call(self) -> _ToolCallExecutionPort | None:
        """Return the optional license-gated tool-call surface."""

        return self._tool_call


__all__ = ["MUTATION_CAPABILITY_ID", "LicenseGatedThorExecutionPort"]
