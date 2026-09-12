"""Atomic post-release closure for one completed safeguard lifecycle.

The lock release, the terminal evidence record, and the release-pending fence
are bound into one durable closure record. A lifecycle that cannot prove all
three is quarantined rather than reported as a clean completion.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable

from fdai.core.executor.post_release_closure import (
    PostReleaseClosureOutcome,
    PostReleaseClosurePhase,
    PostReleaseClosureRecord,
)
from fdai.core.executor.post_release_closure_plan import (
    PostReleaseClosurePlan,
    build_initial_post_release_closure,
)
from fdai.core.executor.post_release_closure_store import (
    PostReleaseClosureStore,
    PostReleaseClosureStoreReceipt,
)
from fdai.core.executor.safeguard_evidence_lifecycle import (
    LifecycleTerminalKind,
    SafeguardEvidenceLifecycleResult,
)
from fdai.core.executor.safeguard_lifecycle_denial import SafeguardDenialJournal
from fdai.core.executor.safeguard_lifecycle_models import (
    SafeguardCoordinatedDispatchResult,
    SafeguardCoordinationDisposition,
)
from fdai.shared.contracts.models import Action
from fdai.shared.providers.resource_lock import HeldResourceLock

_LOGGER = logging.getLogger(__name__)


class SafeguardClosureFinalizer:
    """Close one released lifecycle into a single durable closure receipt."""

    __slots__ = ("_closure_store", "_denial")

    def __init__(
        self,
        *,
        closure_store: PostReleaseClosureStore,
        denial: SafeguardDenialJournal,
    ) -> None:
        self._closure_store = closure_store
        self._denial = denial

    async def finalize(
        self,
        *,
        action: Action,
        held_lock: HeldResourceLock,
        lifecycle: SafeguardEvidenceLifecycleResult,
        release_error: BaseException | None,
    ) -> SafeguardCoordinatedDispatchResult:
        """Bind release, terminal evidence, and fence into one closure record."""

        if lifecycle.kind not in {
            LifecycleTerminalKind.RESOLVED,
            LifecycleTerminalKind.QUARANTINED,
        }:
            return SafeguardCoordinatedDispatchResult(
                disposition=SafeguardCoordinationDisposition.BLOCKED,
                bundle_digest=lifecycle.bundle_digest,
                lifecycle=lifecycle,
                closure_receipt=None,
                dispatch_performed=False,
                reason=lifecycle.kind.value,
            )
        bundle_digest = lifecycle.bundle_digest
        if bundle_digest is None:
            return await self._denial.deny(
                action,
                "post-release safeguard bundle digest is unavailable",
            )
        release_receipt = held_lock.release_receipt
        evidence_record = lifecycle.evidence_record
        release_pending_fence = lifecycle.release_pending_fence
        release_pending_receipt = lifecycle.release_pending_receipt
        if (
            release_receipt is None
            or evidence_record is None
            or release_pending_fence is None
            or release_pending_receipt is None
            or evidence_record.dispatch_start_checkpoint is None
        ):
            return await self._denial.quarantine(
                action,
                reason="post-release safeguard evidence is unavailable",
                bundle_digest=bundle_digest,
                lifecycle=lifecycle,
                dispatch_performed=lifecycle.dispatch_performed,
            )
        in_flight_reservation = (
            evidence_record.dispatch_start_checkpoint.in_flight_reservation_receipt.record
        )
        closed_at = max(
            self._denial.now(),
            release_receipt.recorded_at,
            evidence_record.state_changed_at,
            release_pending_fence.state_changed_at,
            release_pending_receipt.recorded_at,
        )
        plan = build_initial_post_release_closure(
            pre_release_record=evidence_record,
            reservation_record=in_flight_reservation,
            release_pending_fence=release_pending_fence,
            release_receipt=release_receipt,
            closed_at=closed_at,
            force_quarantine=(
                release_error is not None
                or (lifecycle.cancellation_requested and lifecycle.dispatch_performed)
            ),
        )
        try:
            closure_receipt = await self._closure_store.write(plan)
        except asyncio.CancelledError:
            await _await_cancellation_safe(
                self._recover_cancelled_write(
                    action=action,
                    plan=plan,
                    bundle_digest=bundle_digest,
                    dispatch_performed=lifecycle.dispatch_performed,
                )
            )
            raise
        except Exception as exc:
            failure_reason = f"post-release safeguard closure failed: {type(exc).__name__}"
            recovered_receipt = await self._recover_failed_write(
                action=action,
                plan=plan,
                bundle_digest=bundle_digest,
                dispatch_performed=lifecycle.dispatch_performed,
                failure_reason=failure_reason,
            )
            if recovered_receipt is None:
                return SafeguardCoordinatedDispatchResult(
                    disposition=(
                        SafeguardCoordinationDisposition.QUARANTINED
                        if lifecycle.dispatch_performed
                        else SafeguardCoordinationDisposition.BLOCKED
                    ),
                    bundle_digest=bundle_digest,
                    lifecycle=lifecycle,
                    closure_receipt=None,
                    dispatch_performed=lifecycle.dispatch_performed,
                    reason=failure_reason,
                )
            closure_receipt = recovered_receipt
        quarantined = (
            lifecycle.kind is LifecycleTerminalKind.QUARANTINED
            or closure_receipt.record.outcome is PostReleaseClosureOutcome.QUARANTINED
            or release_error is not None
        )
        result_reason = (
            lifecycle.reason
            if lifecycle.reason is not None
            else f"lock release was not proven: {type(release_error).__name__}"
            if release_error is not None
            else None
        )
        if quarantined and result_reason is not None:
            try:
                await self._denial.record_quarantine(
                    action,
                    reason=result_reason,
                    bundle_digest=bundle_digest,
                    dispatch_performed=lifecycle.dispatch_performed,
                )
            except Exception:
                _LOGGER.exception(
                    "safeguard_terminal_quarantine_audit_failed",
                    extra={"action_id": str(action.action_id)},
                )
        return SafeguardCoordinatedDispatchResult(
            disposition=(
                SafeguardCoordinationDisposition.BLOCKED
                if not lifecycle.dispatch_performed
                else SafeguardCoordinationDisposition.QUARANTINED
                if quarantined
                else SafeguardCoordinationDisposition.COMPLETED
            ),
            bundle_digest=bundle_digest,
            lifecycle=lifecycle,
            closure_receipt=closure_receipt,
            dispatch_performed=lifecycle.dispatch_performed,
            reason=result_reason,
        )

    async def _recover_cancelled_write(
        self,
        *,
        action: Action,
        plan: PostReleaseClosurePlan,
        bundle_digest: str,
        dispatch_performed: bool,
    ) -> None:
        """Finish an idempotent closure retry or retain explicit quarantine evidence."""

        quarantine_reason: str | None = None
        try:
            receipt = await self._closure_store.read_receipt(plan.record.identity.closure_key)
            if receipt is None:
                await self._closure_store.write(plan)
                return
            if _matches_attempted_or_reconciled_closure(
                attempted=plan.record,
                observed=receipt.record,
            ):
                return
            quarantine_reason = "post-release closure cancellation readback conflicted"
        except asyncio.CancelledError:
            quarantine_reason = "post-release closure cancellation recovery was cancelled"
        except Exception as exc:
            quarantine_reason = (
                f"post-release closure cancellation recovery failed: {type(exc).__name__}"
            )
        try:
            await self._denial.record_quarantine(
                action,
                reason=quarantine_reason,
                bundle_digest=bundle_digest,
                dispatch_performed=dispatch_performed,
            )
        except Exception:
            _LOGGER.exception(
                "safeguard_post_release_cancellation_audit_failed",
                extra={"action_id": str(action.action_id)},
            )

    async def _recover_failed_write(
        self,
        *,
        action: Action,
        plan: PostReleaseClosurePlan,
        bundle_digest: str,
        dispatch_performed: bool,
        failure_reason: str,
    ) -> PostReleaseClosureStoreReceipt | None:
        """Read back or retry an ambiguous non-cancellation closure failure."""

        quarantine_reason = failure_reason
        try:
            receipt = await self._closure_store.read_receipt(plan.record.identity.closure_key)
            if receipt is not None:
                if not _matches_attempted_or_reconciled_closure(
                    attempted=plan.record,
                    observed=receipt.record,
                ):
                    quarantine_reason = "post-release closure failure readback conflicted"
                else:
                    return receipt
            else:
                return await self._closure_store.write(plan)
        except asyncio.CancelledError:
            await _await_cancellation_safe(
                self._recover_cancelled_write(
                    action=action,
                    plan=plan,
                    bundle_digest=bundle_digest,
                    dispatch_performed=dispatch_performed,
                )
            )
            raise
        except Exception as exc:
            quarantine_reason = (
                f"post-release closure failure recovery failed: {type(exc).__name__}"
            )
        try:
            await self._denial.record_quarantine(
                action,
                reason=quarantine_reason,
                bundle_digest=bundle_digest,
                dispatch_performed=dispatch_performed,
            )
        except Exception:
            _LOGGER.exception(
                "safeguard_post_release_failure_audit_failed",
                extra={"action_id": str(action.action_id)},
            )
        return None


def _matches_attempted_or_reconciled_closure(
    *,
    attempted: PostReleaseClosureRecord,
    observed: PostReleaseClosureRecord,
) -> bool:
    """Accept the exact closure or its one valid reconciled successor."""

    return observed == attempted or (
        observed.identity == attempted.identity
        and attempted.phase is PostReleaseClosurePhase.INITIAL
        and observed.phase is PostReleaseClosurePhase.RECONCILIATION
        and observed.revision == attempted.revision + 1
        and observed.prior_record_digest == attempted.record_digest
    )


async def _await_cancellation_safe[T](awaitable: Awaitable[T]) -> T:
    """Keep a bounded closure recovery alive through repeated cancellation."""

    operation = asyncio.ensure_future(awaitable)
    while True:
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            if operation.cancelled():
                raise


__all__ = ["SafeguardClosureFinalizer"]
