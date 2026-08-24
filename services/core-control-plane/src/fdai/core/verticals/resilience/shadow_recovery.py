"""Pure shadow orchestration for provider-neutral regional recovery actions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from fdai.core.verticals.resilience.recovery_plan import RecoveryPlan, RecoveryState
from fdai.shared.providers.control_plane_recovery import (
    RegionalRecoveryAction,
    RegionalRecoveryActionProvider,
    RegionalRecoveryShadowReceipt,
    RegionalRecoveryShadowRequest,
)

_FAILOVER_ACTIONS: Final[tuple[RegionalRecoveryAction, ...]] = (
    RegionalRecoveryAction.PROVISION_RECOVERY_REGION,
    RegionalRecoveryAction.FENCE_PRIMARY,
    RegionalRecoveryAction.REPLAY_EVENTS,
    RegionalRecoveryAction.SHIFT_TRAFFIC,
)
_EXPECTED_WRITERS: Final[Mapping[RegionalRecoveryAction, tuple[bool, bool]]] = {
    RegionalRecoveryAction.PROVISION_RECOVERY_REGION: (True, False),
    RegionalRecoveryAction.FENCE_PRIMARY: (False, False),
    RegionalRecoveryAction.REPLAY_EVENTS: (False, False),
    RegionalRecoveryAction.SHIFT_TRAFFIC: (False, True),
    RegionalRecoveryAction.FAILBACK: (True, False),
}


class ShadowRecoveryOutcome(StrEnum):
    """Terminal outcome of one shadow recovery evaluation."""

    COMPLETED = "completed"
    HALTED = "halted"


class ShadowRecoveryError(ValueError):
    """Raised when a shadow request is stale or lacks safe prerequisites."""


@dataclass(frozen=True, slots=True)
class ShadowRecoveryResult:
    """Immutable receipts and terminal outcome from a shadow evaluation."""

    outcome: ShadowRecoveryOutcome
    receipts: tuple[RegionalRecoveryShadowReceipt, ...]
    halted_action: RegionalRecoveryAction | None = None
    halt_reason: str | None = None


class ShadowRecoveryOrchestrator:
    """Evaluate a recovery sequence without persistence or provider mutation."""

    def __init__(self, provider: RegionalRecoveryActionProvider) -> None:
        self._provider = provider

    async def evaluate_failover(
        self,
        plan: RecoveryPlan,
        *,
        expected_recovery_epoch: int,
        replay_start: datetime,
        replay_end: datetime,
    ) -> ShadowRecoveryResult:
        """Evaluate ordered failover actions for one activating plan snapshot."""
        self._validate_request(
            plan=plan,
            required_state=RecoveryState.ACTIVATING,
            expected_recovery_epoch=expected_recovery_epoch,
            replay_start=replay_start,
            replay_end=replay_end,
        )
        return await self._evaluate_actions(
            plan=plan,
            actions=_FAILOVER_ACTIONS,
            replay_start=replay_start,
            replay_end=replay_end,
        )

    async def evaluate_failback(
        self,
        plan: RecoveryPlan,
        *,
        expected_recovery_epoch: int,
        previous_recovery_epoch: int,
        replay_start: datetime,
        replay_end: datetime,
        primary_ready: bool,
        state_reconciled: bool,
        primary_writer_active: bool,
        recovery_writer_active: bool,
    ) -> ShadowRecoveryResult:
        """Evaluate failback only after approval, reconciliation, and writer checks."""
        self._validate_request(
            plan=plan,
            required_state=RecoveryState.FAILING_BACK,
            expected_recovery_epoch=expected_recovery_epoch,
            replay_start=replay_start,
            replay_end=replay_end,
        )
        if plan.recovery_epoch <= previous_recovery_epoch:
            raise ShadowRecoveryError("failback requires a new recovery epoch")
        if not primary_ready:
            raise ShadowRecoveryError("failback requires a verified primary target")
        if not state_reconciled:
            raise ShadowRecoveryError("failback requires reconciled state")
        if primary_writer_active or not recovery_writer_active:
            raise ShadowRecoveryError(
                "failback requires the recovery region to be the sole active writer"
            )
        return await self._evaluate_actions(
            plan=plan,
            actions=(RegionalRecoveryAction.FAILBACK,),
            replay_start=replay_start,
            replay_end=replay_end,
        )

    async def _evaluate_actions(
        self,
        *,
        plan: RecoveryPlan,
        actions: tuple[RegionalRecoveryAction, ...],
        replay_start: datetime,
        replay_end: datetime,
    ) -> ShadowRecoveryResult:
        receipts: list[RegionalRecoveryShadowReceipt] = []
        for action in actions:
            request = RegionalRecoveryShadowRequest(
                action=action,
                plan_id=plan.plan_id,
                plan_revision=plan.revision,
                recovery_epoch=plan.recovery_epoch,
                primary_region=plan.primary_region,
                recovery_region=plan.recovery_region,
                scope=plan.scope,
                replay_start=replay_start,
                replay_end=replay_end,
            )
            try:
                receipt = await self._provider.evaluate_shadow(request)
            except Exception:  # noqa: BLE001 - provider boundary fails closed
                return ShadowRecoveryResult(
                    outcome=ShadowRecoveryOutcome.HALTED,
                    receipts=tuple(receipts),
                    halted_action=action,
                    halt_reason="provider_error",
                )
            receipts.append(receipt)
            halt_reason = self._receipt_halt_reason(request=request, receipt=receipt)
            if halt_reason is not None:
                return ShadowRecoveryResult(
                    outcome=ShadowRecoveryOutcome.HALTED,
                    receipts=tuple(receipts),
                    halted_action=action,
                    halt_reason=halt_reason,
                )
        return ShadowRecoveryResult(
            outcome=ShadowRecoveryOutcome.COMPLETED,
            receipts=tuple(receipts),
        )

    @staticmethod
    def _validate_request(
        *,
        plan: RecoveryPlan,
        required_state: RecoveryState,
        expected_recovery_epoch: int,
        replay_start: datetime,
        replay_end: datetime,
    ) -> None:
        if plan.state is not required_state:
            raise ShadowRecoveryError(
                f"shadow recovery requires plan state {required_state.value!r}"
            )
        if expected_recovery_epoch != plan.recovery_epoch:
            raise ShadowRecoveryError("stale recovery epoch")
        if replay_start.tzinfo is None or replay_start.utcoffset() is None:
            raise ShadowRecoveryError("replay_start MUST be timezone-aware")
        if replay_end.tzinfo is None or replay_end.utcoffset() is None:
            raise ShadowRecoveryError("replay_end MUST be timezone-aware")
        if replay_end < replay_start:
            raise ShadowRecoveryError("replay_end MUST be >= replay_start")

    @staticmethod
    def _receipt_halt_reason(
        *,
        request: RegionalRecoveryShadowRequest,
        receipt: RegionalRecoveryShadowReceipt,
    ) -> str | None:
        if receipt.action is not request.action:
            return "receipt_action_mismatch"
        if receipt.observed_epoch != request.recovery_epoch:
            return "receipt_epoch_mismatch"
        if not receipt.evidence_refs or len(set(receipt.evidence_refs)) != len(
            receipt.evidence_refs
        ):
            return "receipt_evidence_invalid"
        if any(not ref or ref != ref.strip() for ref in receipt.evidence_refs):
            return "receipt_evidence_invalid"
        if receipt.primary_writer_active and receipt.recovery_writer_active:
            return "second_writer_active"
        if not receipt.succeeded:
            return "provider_reported_failure"
        expected_primary, expected_recovery = _EXPECTED_WRITERS[request.action]
        if (
            receipt.primary_writer_active is not expected_primary
            or receipt.recovery_writer_active is not expected_recovery
        ):
            return "writer_state_unverified"
        return None


__all__ = [
    "ShadowRecoveryError",
    "ShadowRecoveryOrchestrator",
    "ShadowRecoveryOutcome",
    "ShadowRecoveryResult",
]
