"""Recover durable safeguard attempts without acquiring a target lock or dispatching.

The preparer composes this helper with its existing stores and invokes it while
the coordinator owns the current lock. Recovery may require a later acquisition;
only the coordinator releases and reacquires that lock.
"""

from __future__ import annotations

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationRecord,
    IdempotencyReservationStore,
    IdempotencyReservationTransitionReceipt,
    ReservationEvidenceKind,
    ReservationState,
    abandon_reservation_before_dispatch,
    complete_reservation,
    reopen_reservation,
)
from fdai.core.executor.post_release_closure_plan import build_initial_post_release_closure
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStore
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    ContinuityUnprovenReason,
    DispatchTransportState,
    PreReleaseOwnershipCheckpoint,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
    SafeguardDispatchObservation,
    record_dispatch_observation,
    record_pre_release_checkpoint,
)
from fdai.core.executor.safeguard_dispatch_store import SafeguardDispatchEvidenceStore
from fdai.core.executor.safeguard_lifecycle_denial import SafeguardDenialJournal
from fdai.core.executor.safeguard_lifecycle_models import (
    SafeguardCoordinatedDispatchResult,
    SafeguardCoordinationDisposition,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.core.executor.safeguards import SafeguardReceipt
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceState,
    mark_target_fence_release_pending,
    resolve_target_fence_without_dispatch,
)
from fdai.core.executor.target_dispatch_fence_store import TargetDispatchFenceStore
from fdai.shared.contracts.models import Action
from fdai.shared.providers.resource_lock import (
    ResourceLockReleaseReceipt,
    ResourceLockReleaseState,
)


class SafeguardRecoveryReacquisitionError(Exception):
    """Require a new lock after durable no-dispatch recovery, without dispatching."""


class SafeguardLifecycleRecovery:
    """Recover exact reservation, fence, and evidence records under the caller's lock."""

    __slots__ = (
        "_closure_store",
        "_config",
        "_denial",
        "_evidence_store",
        "_fence_store",
        "_reservation_store",
    )

    def __init__(
        self,
        *,
        reservation_store: IdempotencyReservationStore,
        fence_store: TargetDispatchFenceStore,
        evidence_store: SafeguardDispatchEvidenceStore,
        closure_store: PostReleaseClosureStore,
        config: SafeguardLifecycleCoordinatorConfig,
        denial: SafeguardDenialJournal,
    ) -> None:
        """Reuse the preparer's collaborators without creating lock or dispatch authority."""

        self._reservation_store = reservation_store
        self._fence_store = fence_store
        self._evidence_store = evidence_store
        self._closure_store = closure_store
        self._config = config
        self._denial = denial

    @property
    def source_revision(self) -> str:
        """Return the exact source revision bound to every lifecycle."""

        return self._config.source_revision

    async def _reopen_safe_reservation(
        self,
        *,
        observed: IdempotencyReservationRecord,
        candidate: IdempotencyReservationRecord,
    ) -> IdempotencyReservationTransitionReceipt | None:
        if not (
            observed.state is ReservationState.ABANDONED
            or (
                observed.state is ReservationState.TERMINAL
                and observed.evidence_kind is ReservationEvidenceKind.IRREVOCABLE_NON_ACCEPTANCE
            )
        ):
            return None
        if (
            candidate.identity.acquisition_receipt.attempt
            <= observed.identity.acquisition_receipt.attempt
        ):
            return None
        current_fence = await self._fence_store.read(
            observed.identity.acquisition_receipt.target_digest
        )
        if (
            current_fence is not None
            and current_fence.state is not TargetDispatchFenceState.RESOLVED
        ):
            return None
        acquired_at = candidate.identity.acquisition_receipt.acquired_at
        if acquired_at < observed.state_changed_at or (
            current_fence is not None and acquired_at < current_fence.state_changed_at
        ):
            raise SafeguardRecoveryReacquisitionError
        if current_fence is not None and acquired_at == current_fence.state_changed_at:
            return None
        reopened_at = max(
            self._denial.now(),
            observed.state_changed_at,
            candidate.identity.acquisition_receipt.acquired_at,
        )
        reopened = reopen_reservation(
            observed,
            candidate_identity=candidate.identity,
            reserved_at=reopened_at,
            lease_expires_at=reopened_at + self._config.reservation_lease,
        )
        return await self._reservation_store.compare_and_transition(
            prior_record_digest=observed.record_digest,
            expected_prior_revision=observed.revision,
            record=reopened,
        )

    async def _recover_pre_dispatch_reservation(
        self,
        *,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
        observed: IdempotencyReservationRecord,
        candidate: IdempotencyReservationRecord,
    ) -> IdempotencyReservationTransitionReceipt | None:
        """Close a proven no-dispatch attempt and reopen it under the current lock."""

        if observed.state not in {
            ReservationState.RESERVED,
            ReservationState.IN_FLIGHT,
        }:
            return await self._reopen_safe_reservation(
                observed=observed,
                candidate=candidate,
            )
        fence_readback = await self._fence_store.read_with_timestamp(
            observed.identity.acquisition_receipt.target_digest
        )
        fence = None
        evidence_readback = None
        if fence_readback is not None:
            fence = fence_readback.record
            if fence.identity.reservation_identity_digest != observed.identity.identity_digest:
                if observed.state is not ReservationState.RESERVED:
                    return None
                recovered_at = max(
                    self._denial.now(),
                    observed.state_changed_at,
                    fence.state_changed_at,
                    fence_readback.recorded_at,
                )
                no_dispatch_digest = content_digest(
                    {
                        "domain": "safeguard-restart-no-dispatch",
                        "reservation_record_digest": observed.record_digest,
                        "foreign_fence_record_digest": fence.record_digest,
                    }
                )
                abandoned = abandon_reservation_before_dispatch(
                    observed,
                    at=recovered_at,
                    dispatch_never_began_digest=no_dispatch_digest,
                )
                abandoned_receipt = await self._reservation_store.compare_and_transition(
                    prior_record_digest=observed.record_digest,
                    expected_prior_revision=observed.revision,
                    record=abandoned,
                )
                return await self._reopen_safe_reservation(
                    observed=abandoned_receipt.record,
                    candidate=candidate,
                )
            evidence_readback = await self._evidence_store.read_with_timestamp(
                fence.identity.target_digest,
                fence.identity.generation,
            )
            if fence.state is TargetDispatchFenceState.IN_FLIGHT and (
                evidence_readback is None
                or evidence_readback.record.state
                is not SafeguardDispatchEvidenceState.BUNDLE_PERSISTED
            ):
                return None
            if fence.state not in {
                TargetDispatchFenceState.PREPARING,
                TargetDispatchFenceState.PREPARED,
                TargetDispatchFenceState.IN_FLIGHT,
                TargetDispatchFenceState.RESOLVED,
            }:
                return None
        elif observed.state is ReservationState.IN_FLIGHT:
            return None
        recovered_at = max(
            self._denial.now(),
            observed.state_changed_at,
            fence_readback.recorded_at if fence_readback is not None else observed.state_changed_at,
            (
                evidence_readback.recorded_at
                if evidence_readback is not None
                else observed.state_changed_at
            ),
        )
        no_dispatch_digest = content_digest(
            {
                "domain": "safeguard-restart-no-dispatch",
                "reservation_record_digest": observed.record_digest,
                "fence_record_digest": fence.record_digest if fence is not None else None,
                "evidence_record_digest": (
                    evidence_readback.record.record_digest
                    if evidence_readback is not None
                    else None
                ),
            }
        )
        if fence is not None and fence.state is not TargetDispatchFenceState.RESOLVED:
            resolved_fence = resolve_target_fence_without_dispatch(
                fence,
                no_dispatch_evidence_digest=no_dispatch_digest,
                changed_at=recovered_at,
            )
            fence_receipt = await self._fence_store.compare_and_transition(
                prior_record_digest=fence.record_digest,
                expected_revision=fence.revision,
                record=resolved_fence,
            )
            recovered_at = max(recovered_at, fence_receipt.recorded_at)
        if observed.state is ReservationState.RESERVED:
            closed = abandon_reservation_before_dispatch(
                observed,
                at=recovered_at,
                dispatch_never_began_digest=no_dispatch_digest,
            )
        else:
            closed = complete_reservation(
                observed,
                at=recovered_at,
                terminal_outcome_digest=no_dispatch_digest,
                authoritative_status_digest=no_dispatch_digest,
                irrevocable_non_acceptance=True,
            )
        closed_receipt = await self._reservation_store.compare_and_transition(
            prior_record_digest=observed.record_digest,
            expected_prior_revision=observed.revision,
            record=closed,
        )
        return await self._reopen_safe_reservation(
            observed=closed_receipt.record,
            candidate=candidate,
        )

    async def _recover_release_pending_replay(
        self,
        *,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
        reservation: IdempotencyReservationRecord,
    ) -> SafeguardCoordinatedDispatchResult | None:
        """Quarantine an interrupted post-release closure without redispatch."""

        if reservation.state is not ReservationState.IN_FLIGHT:
            return None
        recovery_started_at = self._denial.now()
        if recovery_started_at < reservation.lease_expires_at:
            return None
        fence_readback = await self._fence_store.read_with_timestamp(
            reservation.identity.acquisition_receipt.target_digest
        )
        if fence_readback is None:
            return None
        fence = fence_readback.record
        if fence is None or fence.state not in {
            TargetDispatchFenceState.IN_FLIGHT,
            TargetDispatchFenceState.RELEASE_PENDING,
        }:
            return None
        if fence.identity.reservation_identity_digest != reservation.identity.identity_digest:
            return None
        evidence_readback = await self._evidence_store.read_with_timestamp(
            fence.identity.target_digest,
            fence.identity.generation,
        )
        if evidence_readback is None:
            return None
        evidence = evidence_readback.record
        if evidence.dispatch_start_checkpoint is None:
            return None
        if not self._evidence_matches_action(
            evidence=evidence,
            action=action,
            safeguard_receipt=safeguard_receipt,
        ):
            return None
        recovered_at = max(
            recovery_started_at,
            reservation.state_changed_at,
            evidence.state_changed_at,
            fence.state_changed_at,
            fence_readback.recorded_at,
            evidence_readback.recorded_at,
        )
        if evidence.state is SafeguardDispatchEvidenceState.DISPATCH_STARTED:
            observation = SafeguardDispatchObservation.create(
                dispatch_start_record=evidence,
                transport_state=DispatchTransportState.UNKNOWN,
                sink_state=AuthoritativeSinkState.UNKNOWN,
                sink_operation_reference_digest=None,
                authoritative_status_digest=None,
                observed_at=recovered_at,
            )
            observed = record_dispatch_observation(
                evidence,
                observation=observation,
                changed_at=recovered_at,
            )
            observation_receipt = await self._evidence_store.compare_and_transition(
                prior_record_digest=evidence.record_digest,
                expected_revision=evidence.revision,
                record=observed,
            )
            evidence = observed
            recovered_at = max(recovered_at, observation_receipt.recorded_at)
        if evidence.state is SafeguardDispatchEvidenceState.DISPATCH_OBSERVED:
            checkpoint = PreReleaseOwnershipCheckpoint.unproven(
                evidence_identity=evidence.identity,
                reason=ContinuityUnprovenReason.MISSING,
                observed_at=recovered_at,
            )
            pre_release = record_pre_release_checkpoint(
                evidence,
                checkpoint=checkpoint,
                current_lock_assessment=None,
                changed_at=recovered_at,
            )
            pre_release_receipt = await self._evidence_store.compare_and_transition(
                prior_record_digest=evidence.record_digest,
                expected_revision=evidence.revision,
                record=pre_release,
                current_lock_assessment=None,
            )
            evidence = pre_release
            recovered_at = max(recovered_at, pre_release_receipt.recorded_at)
        if evidence.state is not SafeguardDispatchEvidenceState.PRE_RELEASE:
            return None
        if fence.state is TargetDispatchFenceState.IN_FLIGHT:
            release_pending = mark_target_fence_release_pending(
                fence,
                changed_at=recovered_at,
            )
            release_pending_receipt = await self._fence_store.compare_and_transition(
                prior_record_digest=fence.record_digest,
                expected_revision=fence.revision,
                record=release_pending,
            )
            fence = release_pending
            recovered_at = max(recovered_at, release_pending_receipt.recorded_at)
        release_receipt = ResourceLockReleaseReceipt.create(
            acquisition_receipt=reservation.identity.acquisition_receipt,
            state=ResourceLockReleaseState.UNKNOWN,
            provider_attestation_digest=content_digest(
                {
                    "domain": "safeguard-restart-release-unknown",
                    "reservation_record_digest": reservation.record_digest,
                    "fence_record_digest": fence.record_digest,
                    "evidence_record_digest": evidence.record_digest,
                }
            ),
            observed_at=None,
            recorded_at=recovered_at,
        )
        plan = build_initial_post_release_closure(
            pre_release_record=evidence,
            reservation_record=reservation,
            release_pending_fence=fence,
            release_receipt=release_receipt,
            closed_at=recovered_at,
            force_quarantine=True,
        )
        closure_receipt = await self._closure_store.write(plan)
        return SafeguardCoordinatedDispatchResult(
            disposition=SafeguardCoordinationDisposition.QUARANTINED,
            bundle_digest=evidence.bundle.bundle_digest,
            lifecycle=None,
            closure_receipt=closure_receipt,
            dispatch_performed=False,
            reason="prior release-pending lifecycle recovered into quarantine",
        )

    def _evidence_matches_action(
        self,
        *,
        evidence: SafeguardDispatchEvidenceRecord,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
    ) -> bool:
        identity = evidence.identity
        if (
            identity.action_id != str(action.action_id)
            or identity.execution_path != safeguard_receipt.execution_path.value
            or identity.execution_fingerprint != f"sha256:{safeguard_receipt.execution_fingerprint}"
            or identity.source_revision != self.source_revision
        ):
            return False
        return True
