"""Production coordinator for the complete safeguard evidence lifecycle.

This module owns the order of the safeguard phases around one real dispatch.
Each phase lives in a focused sibling module and is re-exported here so the
public import surface is unchanged:

* :mod:`fdai.core.executor.safeguard_lifecycle_models` - result, disposition,
  and configuration records.
* :mod:`fdai.core.executor.safeguard_lifecycle_denial` - durable denial
  journal and the single aware lifecycle clock.
* :mod:`fdai.core.executor.safeguard_lifecycle_preparation` - provider-owned
  preparation inside the held logical-target lock.
* :mod:`fdai.core.executor.safeguard_hold_fenced_port` - hold fencing applied
  immediately before the provider is invoked.
* :mod:`fdai.core.executor.safeguard_lifecycle_closure` - atomic post-release
  closure.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from fdai.core.executor.audit_intent import AuditIntentStore
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationStore,
    ReservationEvidenceKind,
    ReservationState,
)
from fdai.core.executor.lock_continuity import EffectSinkContinuityPolicy
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStore
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
)
from fdai.core.executor.safeguard_dispatch_store import SafeguardDispatchEvidenceStore
from fdai.core.executor.safeguard_evidence_lifecycle import (
    DispatchBoundaryGuard,
    DispatchPort,
    SafeguardEvidenceLifecycleResult,
)
from fdai.core.executor.safeguard_lifecycle_closure import SafeguardClosureFinalizer
from fdai.core.executor.safeguard_lifecycle_denial import SafeguardDenialJournal
from fdai.core.executor.safeguard_lifecycle_models import (
    ProductionSafeguardStore,
    SafeguardCoordinatedDispatchResult,
    SafeguardCoordinationDisposition,
    SafeguardCoordinationError,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.core.executor.safeguard_lifecycle_preparation import (
    SafeguardLifecyclePreparer,
    SafeguardRecoveryReacquisitionError,
)
from fdai.core.executor.safeguard_pre_bundle import (
    SafeguardPreBundleCommitment,
    SafeguardPreBundleCommitmentStore,
)
from fdai.core.executor.safeguards import SafeguardReceipt
from fdai.core.executor.target_dispatch_fence_store import TargetDispatchFenceStore
from fdai.shared.contracts.models import Action, ExecutionPath
from fdai.shared.providers.automation_hold_state import (
    AutomationHoldStateReader,
    HoldReleaseAuthorizationReader,
)
from fdai.shared.providers.resource_lock import (
    EvidenceResourceLock,
    HeldResourceLock,
    ResourceLockAcquisitionRequest,
    ResourceLockReleaseState,
    require_evidence_resource_lock,
)
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)


class _DispatchAttemptPort:
    """Remember when the provider boundary may already have observed a call."""

    __slots__ = ("_inner", "bundle_digest", "started")

    def __init__(self, inner: DispatchPort) -> None:
        self._inner = inner
        self.bundle_digest: str | None = None
        self.started = False

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
        pre_invoke_guard: DispatchBoundaryGuard,
    ) -> tuple[
        DispatchTransportState,
        AuthoritativeSinkState,
        str | None,
        str | None,
    ]:
        async def tracked_guard() -> datetime:
            provider_call_at = await pre_invoke_guard()
            self.started = True
            self.bundle_digest = evidence_record.bundle.bundle_digest
            return provider_call_at

        return await self._inner.dispatch(
            evidence_record=evidence_record,
            started_at=started_at,
            pre_invoke_guard=tracked_guard,
        )


class SafeguardLifecycleCoordinator:
    """Order every provider-owned safeguard phase around one real dispatch."""

    def __init__(
        self,
        *,
        resource_lock: EvidenceResourceLock,
        reservation_store: IdempotencyReservationStore,
        audit_intent_store: AuditIntentStore,
        fence_store: TargetDispatchFenceStore,
        evidence_store: SafeguardDispatchEvidenceStore,
        closure_store: PostReleaseClosureStore,
        denial_audit_store: StateStore,
        continuity_policy: EffectSinkContinuityPolicy,
        config: SafeguardLifecycleCoordinatorConfig,
        commitment_store: SafeguardPreBundleCommitmentStore | None = None,
        hold_state_reader: AutomationHoldStateReader | None = None,
        hold_release_authorizations: HoldReleaseAuthorizationReader | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._resource_lock = require_evidence_resource_lock(
            resource_lock,
            production=config.production,
        )
        self._reservation_store = reservation_store
        self._config = config
        self._commitment_store = commitment_store
        self._denial = SafeguardDenialJournal(
            config=config,
            denial_audit_store=denial_audit_store,
            clock=clock or (lambda: datetime.now(UTC)),
        )
        self._preparer = SafeguardLifecyclePreparer(
            reservation_store=reservation_store,
            audit_intent_store=audit_intent_store,
            fence_store=fence_store,
            evidence_store=evidence_store,
            closure_store=closure_store,
            denial_audit_store=denial_audit_store,
            continuity_policy=continuity_policy,
            config=config,
            denial=self._denial,
            hold_state_reader=hold_state_reader,
            hold_release_authorizations=hold_release_authorizations,
        )
        self._closure = SafeguardClosureFinalizer(
            closure_store=closure_store,
            denial=self._denial,
        )
        if config.production:
            stores = (
                reservation_store,
                audit_intent_store,
                fence_store,
                evidence_store,
                closure_store,
            )
            if any(
                not isinstance(store, ProductionSafeguardStore)
                or store.production_eligible is not True
                for store in stores
            ):
                raise RuntimeError("production safeguard lifecycle stores are unavailable")

    @property
    def production_ready(self) -> bool:
        """Return whether this coordinator was composed for production."""

        return self._config.production

    @property
    def source_revision(self) -> str:
        """Return the exact source revision bound to every lifecycle."""

        return self._config.source_revision

    async def prepare_pre_bundle_commitment(
        self,
        *,
        action: Action,
        execution_path: ExecutionPath,
        correlation_id: str,
    ) -> SafeguardPreBundleCommitment:
        """Persist a workflow commitment before target locking or reuse it exactly."""

        lineage = action.workflow_action
        if lineage is None:
            return SafeguardPreBundleCommitment.create(
                action=action,
                execution_path=execution_path,
                source_revision=self.source_revision,
                committed_at=self._now(),
            )
        store = self._commitment_store
        if store is None:
            raise SafeguardCoordinationError(
                "workflow safeguard pre-bundle commitment store is unavailable"
            )
        existing = await store.read(
            process_id=lineage.process_id,
            step_id=lineage.step_id,
            attempt=lineage.attempt,
        )
        if existing is not None:
            existing.require_matches(
                action=action,
                execution_path=execution_path,
                source_revision=self.source_revision,
            )
            return existing
        commitment = SafeguardPreBundleCommitment.create(
            action=action,
            execution_path=execution_path,
            source_revision=self.source_revision,
            committed_at=self._now(),
        )
        bound = await store.bind(
            process_id=lineage.process_id,
            step_id=lineage.step_id,
            attempt=lineage.attempt,
            correlation_id=correlation_id or lineage.proposal_ref,
            commitment=commitment,
        )
        bound.require_matches(
            action=action,
            execution_path=execution_path,
            source_revision=self.source_revision,
        )
        return bound

    async def dispatch(
        self,
        *,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
        dispatch_port: DispatchPort,
        correlation_id: str,
        attempt: int = 1,
    ) -> SafeguardCoordinatedDispatchResult:
        """Run the lifecycle, reacquiring once if durable recovery postdates the lock."""

        if type(safeguard_receipt) is not SafeguardReceipt:
            return await self._denial.deny(action, "safeguard receipt is missing or invalid")
        execution_path = safeguard_receipt.execution_path
        try:
            commitment = await self.prepare_pre_bundle_commitment(
                action=action,
                execution_path=execution_path,
                correlation_id=correlation_id,
            )
            commitment.require_matches(
                action=action,
                execution_path=execution_path,
                source_revision=self.source_revision,
            )
        except (ValueError, SafeguardCoordinationError) as exc:
            return await self._denial.deny(action, str(exc))
        if attempt < 1:
            return await self._denial.deny(action, "safeguard lifecycle attempt MUST be positive")

        try:
            prior_reservation = await self._reservation_store.read(action.idempotency_key)
        except Exception as exc:
            return await self._denial.deny(
                action,
                f"idempotency reservation read failed: {type(exc).__name__}",
            )
        effective_attempt = attempt
        if prior_reservation is not None and (
            prior_reservation.state
            in {
                ReservationState.RESERVED,
                ReservationState.IN_FLIGHT,
                ReservationState.ABANDONED,
            }
            or (
                prior_reservation.state is ReservationState.TERMINAL
                and prior_reservation.evidence_kind
                is ReservationEvidenceKind.IRREVOCABLE_NON_ACCEPTANCE
            )
        ):
            effective_attempt = max(
                attempt,
                prior_reservation.identity.acquisition_receipt.attempt + 1,
            )
        acquisition_request = ResourceLockAcquisitionRequest.create(
            target_ref=action.target_resource_ref,
            action_digest=safeguard_receipt.action_digest,
            attempt=effective_attempt,
            producer_id=self._config.producer_id,
            producer_version=self._config.producer_version,
            source_revision=self.source_revision,
        )
        held_lock: HeldResourceLock | None = None
        lifecycle: SafeguardEvidenceLifecycleResult | None = None
        release_error: BaseException | None = None
        release_cancelled = False
        tracked_dispatch = _DispatchAttemptPort(dispatch_port)
        try:
            for recovery_pass in range(2):
                try:
                    async with self._resource_lock.acquire_evidenced(
                        acquisition_request
                    ) as active_lock:
                        held_lock = active_lock
                        lifecycle_or_result = await self._preparer.dispatch_while_held(
                            action=action,
                            safeguard_receipt=safeguard_receipt,
                            commitment=commitment,
                            held_lock=active_lock,
                            dispatch_port=tracked_dispatch,
                            correlation_id=correlation_id,
                        )
                        if isinstance(lifecycle_or_result, SafeguardCoordinatedDispatchResult):
                            return lifecycle_or_result
                        lifecycle = lifecycle_or_result
                    break
                except SafeguardRecoveryReacquisitionError:
                    if recovery_pass:
                        return await self._denial.deny(
                            action, "safeguard recovery requires a later evidenced acquisition"
                        )
                    release = held_lock.release_receipt if held_lock is not None else None
                    if (
                        held_lock is None
                        or release is None
                        or release.state is not ResourceLockReleaseState.RELEASED
                        or release.acquisition_receipt != held_lock.acquisition_receipt
                    ):
                        return await self._denial.deny(
                            action, "safeguard recovery lock release is unproven"
                        )
                    held_lock = None
        except asyncio.CancelledError:
            if held_lock is not None and lifecycle is not None:
                release_error = asyncio.CancelledError()
                release_cancelled = True
            else:
                if tracked_dispatch.started and tracked_dispatch.bundle_digest is not None:
                    try:
                        await self._denial.record_quarantine(
                            action,
                            reason="safeguard lifecycle cancelled after dispatch started",
                            bundle_digest=tracked_dispatch.bundle_digest,
                        )
                    except Exception:
                        _LOGGER.exception(
                            "safeguard_post_dispatch_cancellation_audit_failed",
                            extra={"action_id": str(action.action_id)},
                        )
                raise
        except Exception as exc:
            if lifecycle is None:
                if tracked_dispatch.started and tracked_dispatch.bundle_digest is not None:
                    return await self._denial.quarantine(
                        action,
                        reason=(
                            "safeguard lifecycle failed after dispatch started: "
                            f"{type(exc).__name__}"
                        ),
                        bundle_digest=tracked_dispatch.bundle_digest,
                    )
                return await self._denial.deny(
                    action,
                    f"safeguard lifecycle failed before terminal evidence: {type(exc).__name__}",
                )
            release_error = exc

        if held_lock is None or lifecycle is None:
            return await self._denial.deny(action, "safeguard lifecycle lost its held-lock result")
        result = await self._closure.finalize(
            action=action,
            held_lock=held_lock,
            lifecycle=lifecycle,
            release_error=release_error,
        )
        if lifecycle.cancellation_requested or release_cancelled:
            raise asyncio.CancelledError
        return result

    def _now(self) -> datetime:
        """Return the single aware clock reading the lifecycle is bound to."""

        return self._denial.now()


__all__ = [
    "ProductionSafeguardStore",
    "SafeguardCoordinatedDispatchResult",
    "SafeguardCoordinationDisposition",
    "SafeguardCoordinationError",
    "SafeguardLifecycleCoordinator",
    "SafeguardLifecycleCoordinatorConfig",
]
