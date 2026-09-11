"""Atomic post-release closure for one completed safeguard lifecycle.

The lock release, the terminal evidence record, and the release-pending fence
are bound into one durable closure record. A lifecycle that cannot prove all
three is quarantined rather than reported as a clean completion.
"""

from __future__ import annotations

from fdai.core.executor.post_release_closure import PostReleaseClosureOutcome
from fdai.core.executor.post_release_closure_plan import build_initial_post_release_closure
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStore
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
        release_receipt = held_lock.release_receipt
        evidence_record = lifecycle.evidence_record
        release_pending_fence = lifecycle.release_pending_fence
        if (
            release_receipt is None
            or evidence_record is None
            or release_pending_fence is None
            or evidence_record.dispatch_start_checkpoint is None
        ):
            return await self._denial.deny(action, "post-release safeguard evidence is unavailable")
        in_flight_reservation = (
            evidence_record.dispatch_start_checkpoint.in_flight_reservation_receipt.record
        )
        closed_at = max(
            self._denial.now(),
            release_receipt.recorded_at,
            evidence_record.state_changed_at,
            release_pending_fence.state_changed_at,
        )
        plan = build_initial_post_release_closure(
            pre_release_record=evidence_record,
            reservation_record=in_flight_reservation,
            release_pending_fence=release_pending_fence,
            release_receipt=release_receipt,
            closed_at=closed_at,
        )
        closure_receipt = await self._closure_store.write(plan)
        quarantined = (
            lifecycle.kind is LifecycleTerminalKind.QUARANTINED
            or closure_receipt.record.outcome is PostReleaseClosureOutcome.QUARANTINED
            or release_error is not None
        )
        return SafeguardCoordinatedDispatchResult(
            disposition=(
                SafeguardCoordinationDisposition.QUARANTINED
                if quarantined
                else SafeguardCoordinationDisposition.COMPLETED
            ),
            bundle_digest=lifecycle.bundle_digest,
            lifecycle=lifecycle,
            closure_receipt=closure_receipt,
            dispatch_performed=True,
            reason=(
                f"lock release was not proven: {type(release_error).__name__}"
                if release_error is not None
                else None
            ),
        )


__all__ = ["SafeguardClosureFinalizer"]
