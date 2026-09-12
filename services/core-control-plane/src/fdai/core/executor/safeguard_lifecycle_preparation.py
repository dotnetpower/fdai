"""Provider-owned safeguard preparation inside one held logical-target lock.

Reservation, pre-effect audit intent, target dispatch fence, and the
finalized proof bundle are all prepared here before the shared evidence
lifecycle performs the single real dispatch. Any phase that cannot be proven
denies the dispatch and resolves the fence without invoking the provider.
"""

from __future__ import annotations

import asyncio
import logging

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.audit_intent import (
    AuditIntentAppendDecision,
    AuditIntentStore,
    PreEffectAuditIntent,
)
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationIdentity,
    IdempotencyReservationRecord,
    IdempotencyReservationStore,
    IdempotencyReservationTransitionReceipt,
    ReservationMatch,
    ReservationState,
)
from fdai.core.executor.idempotency_reservation_identity import same_operation
from fdai.core.executor.lock_continuity import EffectSinkContinuityPolicy
from fdai.core.executor.post_release_closure import (
    PostReleaseClosureOutcome,
    PostReleaseClosureRecord,
    ReconciliationOutcome,
)
from fdai.core.executor.post_release_closure_store import PostReleaseClosureStore
from fdai.core.executor.safeguard_bundle_context import SafeguardBundlePersistenceContext
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    SafeguardDispatchEvidenceRecord,
    SafeguardDispatchEvidenceState,
)
from fdai.core.executor.safeguard_dispatch_store import SafeguardDispatchEvidenceStore
from fdai.core.executor.safeguard_evidence_lifecycle import (
    DispatchPort,
    SafeguardEvidenceLifecycleResult,
    cancel_before_dispatch,
    run_safeguard_evidence_lifecycle,
)
from fdai.core.executor.safeguard_hold_fenced_port import HoldFencedDispatchPort
from fdai.core.executor.safeguard_lifecycle_denial import SafeguardDenialJournal
from fdai.core.executor.safeguard_lifecycle_models import (
    SafeguardCoordinatedDispatchResult,
    SafeguardCoordinationDisposition,
    SafeguardLifecycleCoordinatorConfig,
)
from fdai.core.executor.safeguard_lifecycle_recovery import (
    SafeguardLifecycleRecovery,
)
from fdai.core.executor.safeguard_lifecycle_recovery import (
    SafeguardRecoveryReacquisitionError as SafeguardRecoveryReacquisitionError,
)
from fdai.core.executor.safeguard_pre_bundle import SafeguardPreBundleCommitment
from fdai.core.executor.safeguard_proofs import (
    AuditIntentProof,
    IdempotencyReservationProof,
    LogicalTargetLockProof,
    finalize_safeguard_proof_bundle,
)
from fdai.core.executor.safeguards import SafeguardReceipt
from fdai.core.executor.target_dispatch_fence import (
    TargetDispatchFenceIdentity,
    TargetDispatchFenceRecord,
    TargetDispatchFenceState,
)
from fdai.core.executor.target_dispatch_fence_store import (
    TargetDispatchFenceAcquireDecision,
    TargetDispatchFenceStore,
)
from fdai.shared.contracts.models import Action
from fdai.shared.providers.automation_hold_state import (
    AutomationHoldStateReader,
    HoldReleaseAuthorizationReader,
)
from fdai.shared.providers.resource_lock import HeldResourceLock
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)


class SafeguardLifecyclePreparer:
    """Prepare and run every safeguard phase inside one held target lock."""

    __slots__ = (
        "_audit_intent_store",
        "_config",
        "_continuity_policy",
        "_denial",
        "_denial_audit_store",
        "_evidence_store",
        "_fence_store",
        "_hold_release_authorizations",
        "_hold_state_reader",
        "_closure_store",
        "_reservation_store",
        "_recovery",
    )

    def __init__(
        self,
        *,
        reservation_store: IdempotencyReservationStore,
        audit_intent_store: AuditIntentStore,
        fence_store: TargetDispatchFenceStore,
        evidence_store: SafeguardDispatchEvidenceStore,
        closure_store: PostReleaseClosureStore,
        denial_audit_store: StateStore,
        continuity_policy: EffectSinkContinuityPolicy,
        config: SafeguardLifecycleCoordinatorConfig,
        denial: SafeguardDenialJournal,
        hold_state_reader: AutomationHoldStateReader | None = None,
        hold_release_authorizations: HoldReleaseAuthorizationReader | None = None,
    ) -> None:
        self._reservation_store = reservation_store
        self._audit_intent_store = audit_intent_store
        self._fence_store = fence_store
        self._evidence_store = evidence_store
        self._closure_store = closure_store
        self._denial_audit_store = denial_audit_store
        self._continuity_policy = continuity_policy
        self._config = config
        self._denial = denial
        self._hold_state_reader = hold_state_reader
        self._hold_release_authorizations = hold_release_authorizations
        self._recovery = SafeguardLifecycleRecovery(
            reservation_store=reservation_store,
            fence_store=fence_store,
            evidence_store=evidence_store,
            closure_store=closure_store,
            config=config,
            denial=denial,
        )

    @property
    def source_revision(self) -> str:
        """Return the exact source revision bound to every lifecycle."""

        return self._config.source_revision

    async def dispatch_while_held(
        self,
        *,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
        commitment: SafeguardPreBundleCommitment,
        held_lock: HeldResourceLock,
        dispatch_port: DispatchPort,
        correlation_id: str,
    ) -> SafeguardEvidenceLifecycleResult | SafeguardCoordinatedDispatchResult:
        acquisition = held_lock.acquisition_receipt
        reserved_at = max(self._denial.now(), acquisition.acquired_at)
        reservation_identity = IdempotencyReservationIdentity.create(
            idempotency_key=action.idempotency_key,
            action_digest=safeguard_receipt.action_digest,
            execution_path=safeguard_receipt.execution_path,
            execution_fingerprint=safeguard_receipt.execution_fingerprint,
            source_revision=self.source_revision,
            acquisition_receipt=acquisition,
        )
        reserved = IdempotencyReservationRecord.create_reserved(
            identity=reservation_identity,
            reserved_at=reserved_at,
            lease_expires_at=reserved_at + self._config.reservation_lease,
        )
        reservation_result = await self._reservation_store.reserve(reserved)
        reservation_receipt: IdempotencyReservationTransitionReceipt | None = None
        if reservation_result.match is ReservationMatch.CONFLICT:
            if same_operation(
                reservation_result.observed_record.identity,
                reservation_identity,
            ):
                if reservation_result.observed_record.state is ReservationState.TERMINAL:
                    reopened = await self._recovery._reopen_safe_reservation(
                        observed=reservation_result.observed_record,
                        candidate=reserved,
                    )
                    if reopened is not None:
                        reservation_receipt = reopened
                    else:
                        return await self._terminal_replay_result(
                            action=action,
                            safeguard_receipt=safeguard_receipt,
                            reservation=reservation_result.observed_record,
                        )
                else:
                    reopened = await self._recovery._recover_pre_dispatch_reservation(
                        action=action,
                        safeguard_receipt=safeguard_receipt,
                        observed=reservation_result.observed_record,
                        candidate=reserved,
                    )
                    if reopened is not None:
                        reservation_receipt = reopened
                    else:
                        recovered = await self._recovery._recover_release_pending_replay(
                            action=action,
                            safeguard_receipt=safeguard_receipt,
                            reservation=reservation_result.observed_record,
                        )
                        if recovered is not None:
                            return recovered
                        quarantined = await self._quarantined_replay_result(
                            action=action,
                            safeguard_receipt=safeguard_receipt,
                            reservation=reservation_result.observed_record,
                        )
                        if quarantined is not None:
                            return quarantined
                        return SafeguardCoordinatedDispatchResult(
                            disposition=SafeguardCoordinationDisposition.BLOCKED,
                            bundle_digest=await self._existing_bundle_digest(
                                action=action,
                                safeguard_receipt=safeguard_receipt,
                            ),
                            lifecycle=None,
                            closure_receipt=None,
                            dispatch_performed=False,
                            reason=(
                                "idempotency reservation already exists and has not reached "
                                "a committed terminal outcome"
                            ),
                        )
            else:
                return await self._denial.deny(
                    action,
                    "idempotency reservation conflicts with a different action",
                )
        elif reservation_result.match is ReservationMatch.DUPLICATE_SAME:
            if reservation_result.observed_record.state is ReservationState.TERMINAL:
                reopened = await self._recovery._reopen_safe_reservation(
                    observed=reservation_result.observed_record,
                    candidate=reserved,
                )
                if reopened is not None:
                    reservation_receipt = reopened
                else:
                    return await self._terminal_replay_result(
                        action=action,
                        safeguard_receipt=safeguard_receipt,
                        reservation=reservation_result.observed_record,
                    )
            else:
                reopened = await self._recovery._recover_pre_dispatch_reservation(
                    action=action,
                    safeguard_receipt=safeguard_receipt,
                    observed=reservation_result.observed_record,
                    candidate=reserved,
                )
                if reopened is not None:
                    reservation_receipt = reopened
                else:
                    recovered = await self._recovery._recover_release_pending_replay(
                        action=action,
                        safeguard_receipt=safeguard_receipt,
                        reservation=reservation_result.observed_record,
                    )
                    if recovered is not None:
                        return recovered
                    quarantined = await self._quarantined_replay_result(
                        action=action,
                        safeguard_receipt=safeguard_receipt,
                        reservation=reservation_result.observed_record,
                    )
                    if quarantined is not None:
                        return quarantined
                    return SafeguardCoordinatedDispatchResult(
                        disposition=SafeguardCoordinationDisposition.BLOCKED,
                        bundle_digest=await self._existing_bundle_digest(
                            action=action,
                            safeguard_receipt=safeguard_receipt,
                        ),
                        lifecycle=None,
                        closure_receipt=None,
                        dispatch_performed=False,
                        reason=(
                            "idempotency reservation already exists and has not reached "
                            "a committed terminal outcome"
                        ),
                    )
        else:
            reservation_receipt = reservation_result.transition_receipt
        if reservation_receipt is None:
            return await self._denial.deny(action, "idempotency reservation receipt is unavailable")

        intent = PreEffectAuditIntent.create(
            reservation_receipt=reservation_receipt,
            actor=self._config.actor,
            created_at=max(self._denial.now(), reservation_receipt.recorded_at),
        )
        append_result = await self._audit_intent_store.append_and_readback(intent)
        if append_result.decision is AuditIntentAppendDecision.CONFLICT:
            return await self._denial.deny(
                action, "pre-effect audit intent conflicts with durable state"
            )
        audit_receipt = append_result.receipt
        if audit_receipt is None:
            return await self._denial.deny(
                action, "pre-effect audit intent readback is unavailable"
            )

        prior_fence = await self._fence_store.read(acquisition.target_digest)
        if prior_fence is not None and prior_fence.state is not TargetDispatchFenceState.RESOLVED:
            return SafeguardCoordinatedDispatchResult(
                disposition=SafeguardCoordinationDisposition.BLOCKED,
                bundle_digest=await self._bundle_for_fence(
                    action=action,
                    safeguard_receipt=safeguard_receipt,
                    fence=prior_fence,
                ),
                lifecycle=None,
                closure_receipt=None,
                dispatch_performed=False,
                reason="target dispatch fence is unresolved",
            )
        generation = 1 if prior_fence is None else prior_fence.identity.generation + 1
        fence_identity = TargetDispatchFenceIdentity.create(
            target_digest=acquisition.target_digest,
            reservation_identity=reservation_identity,
            continuity_policy=self._continuity_policy,
            generation=generation,
            client_correlation_id=correlation_id or str(action.event_id),
            sink_idempotency_key=action.idempotency_key,
        )
        preparing_fence = TargetDispatchFenceRecord.create_preparing(
            identity=fence_identity,
            changed_at=max(self._denial.now(), audit_receipt.read_back_at),
            prior_resolved_record=prior_fence,
        )
        fence_result = await self._fence_store.acquire_generation(preparing_fence)
        if fence_result.decision is not TargetDispatchFenceAcquireDecision.ACQUIRED:
            return SafeguardCoordinatedDispatchResult(
                disposition=SafeguardCoordinationDisposition.BLOCKED,
                bundle_digest=await self._bundle_for_fence(
                    action=action,
                    safeguard_receipt=safeguard_receipt,
                    fence=fence_result.observed_record,
                ),
                lifecycle=None,
                closure_receipt=None,
                dispatch_performed=False,
                reason=f"target dispatch fence {fence_result.decision.value}",
            )
        fence_receipt = fence_result.transition_receipt
        if fence_receipt is None:
            return await self._denial.deny(
                action,
                "target dispatch fence acquisition receipt is unavailable",
            )

        try:
            assessment = await held_lock.assess_ownership()
            proof_time = assessment.evaluated_at
            lock_proof = LogicalTargetLockProof.create(
                action_digest=safeguard_receipt.action_digest,
                execution_path=safeguard_receipt.execution_path,
                execution_fingerprint=safeguard_receipt.execution_fingerprint,
                lock_key=safeguard_receipt.resource_lock_key,
                source_revision=self.source_revision,
                completed_at=proof_time,
                operation_receipt_digest=acquisition.receipt_digest,
            )
            idempotency_proof = IdempotencyReservationProof.create(
                action_digest=safeguard_receipt.action_digest,
                execution_path=safeguard_receipt.execution_path,
                execution_fingerprint=safeguard_receipt.execution_fingerprint,
                idempotency_key=action.idempotency_key,
                reservation_outcome="reserved",
                source_revision=self.source_revision,
                completed_at=reservation_receipt.recorded_at,
                store_receipt_digest=reservation_receipt.receipt_digest,
            )
            audit_proof = AuditIntentProof.create(
                action_digest=safeguard_receipt.action_digest,
                execution_path=safeguard_receipt.execution_path,
                execution_fingerprint=safeguard_receipt.execution_fingerprint,
                audit_entry_digest=intent.intent_digest,
                source_revision=self.source_revision,
                completed_at=audit_receipt.read_back_at,
                append_receipt_digest=audit_receipt.receipt_digest,
            )
            bundle_time = max(
                self._denial.now(),
                proof_time,
                audit_receipt.read_back_at,
                preparing_fence.state_changed_at,
                fence_receipt.recorded_at,
            )
            bundle = finalize_safeguard_proof_bundle(
                action,
                receipt=safeguard_receipt,
                source_revision=self.source_revision,
                recorded_at=bundle_time,
                lock_proof=lock_proof,
                lock_assessment=assessment,
                expected_lock_verifier_id=self._config.expected_lock_verifier_id,
                expected_lock_verifier_version=self._config.expected_lock_verifier_version,
                expected_lock_trust_anchor_id=self._config.expected_lock_trust_anchor_id,
                idempotency_proof=idempotency_proof,
                audit_intent_proof=audit_proof,
            )
            context = SafeguardBundlePersistenceContext(
                action=action,
                pre_bundle_commitment=commitment,
                safeguard_receipt=safeguard_receipt,
                reservation_receipt=reservation_receipt,
                audit_append_receipt=audit_receipt,
                lock_assessment=assessment,
                lock_proof=lock_proof,
                idempotency_proof=idempotency_proof,
                audit_intent_proof=audit_proof,
            )
            bundle_record = SafeguardDispatchEvidenceRecord.create_bundle_persisted(
                preparing_fence=preparing_fence,
                persistence_context=context,
                bundle=bundle,
                persisted_at=bundle_time,
            )
            return await run_safeguard_evidence_lifecycle(
                held_lock=held_lock,
                reservation_receipt=reservation_receipt,
                audit_append_receipt=audit_receipt,
                bundle_record=bundle_record,
                preparing_fence=preparing_fence,
                reservation_store=self._reservation_store,
                fence_store=self._fence_store,
                evidence_store=self._evidence_store,
                dispatch_port=HoldFencedDispatchPort(
                    inner=dispatch_port,
                    hold_state_reader=self._hold_state_reader,
                    lineage_reader=self._hold_release_authorizations,
                    workflow_lineage=(
                        (action.workflow_action.process_id, action.workflow_action.step_id)
                        if action.workflow_action is not None
                        else None
                    ),
                    target_ref=action.target_resource_ref,
                    target_digest=acquisition.target_digest,
                    lock_ownership_token=acquisition.receipt_digest,
                    denial_audit_store=self._denial_audit_store,
                    actor=self._config.actor,
                    action_id=str(action.action_id),
                    clock=self._denial.now,
                ),
                now=bundle_time,
                clock=self._denial.now,
            )
        except (Exception, asyncio.CancelledError):
            no_dispatch_digest = content_digest(
                {
                    "domain": "safeguard-lifecycle-no-dispatch",
                    "action_digest": safeguard_receipt.action_digest,
                    "commitment_digest": commitment.commitment_digest,
                    "fence_record_digest": preparing_fence.record_digest,
                }
            )
            try:
                await cancel_before_dispatch(
                    held_lock=held_lock,
                    preparing_fence=preparing_fence,
                    no_dispatch_evidence_digest=no_dispatch_digest,
                    fence_store=self._fence_store,
                    now=max(
                        self._denial.now(),
                        preparing_fence.state_changed_at,
                        fence_receipt.recorded_at,
                    ),
                )
            except Exception:
                _LOGGER.exception(
                    "safeguard_no_dispatch_fence_resolution_failed",
                    extra={"action_id": str(action.action_id)},
                )
            raise

    async def _existing_bundle_digest(
        self,
        *,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
    ) -> str | None:
        fence = await self._fence_store.read(
            content_digest({"target_resource_ref": action.target_resource_ref})
        )
        if fence is None:
            return None
        evidence = await self._evidence_for_fence(
            action=action,
            safeguard_receipt=safeguard_receipt,
            fence=fence,
        )
        return evidence.bundle.bundle_digest if evidence is not None else None

    async def _terminal_replay_result(
        self,
        *,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
        reservation: IdempotencyReservationRecord,
    ) -> SafeguardCoordinatedDispatchResult:
        closure_key = content_digest(
            {
                "domain": "post-release-closure-key",
                "reservation_identity_digest": reservation.identity.identity_digest,
                "reservation_attempt": reservation.identity.acquisition_receipt.attempt,
            }
        )
        closure = await self._closure_store.read(closure_key)
        evidence = None
        if closure is not None:
            evidence = await self._evidence_store.read(
                closure.identity.target_digest,
                closure.identity.target_fence_generation,
            )
            if (
                evidence is None
                or evidence.identity.reservation_identity_digest
                != reservation.identity.identity_digest
                or not self._recovery._evidence_matches_action(
                    evidence=evidence,
                    action=action,
                    safeguard_receipt=safeguard_receipt,
                )
                or closure.identity.evidence_identity_digest != evidence.identity.identity_digest
                or closure.pre_release_record_digest != evidence.record_digest
            ):
                evidence = None
        bundle_digest = evidence.bundle.bundle_digest if evidence is not None else None
        applied = False
        if (
            evidence is not None
            and evidence.state is SafeguardDispatchEvidenceState.PRE_RELEASE
            and closure is not None
        ):
            applied = _closure_proves_applied(closure=closure, evidence=evidence)
        return SafeguardCoordinatedDispatchResult(
            disposition=(
                SafeguardCoordinationDisposition.DUPLICATE
                if applied
                else SafeguardCoordinationDisposition.BLOCKED
            ),
            bundle_digest=bundle_digest,
            lifecycle=None,
            closure_receipt=None,
            dispatch_performed=False,
            reason=(
                "idempotent operation already reached a committed terminal state"
                if applied
                else "idempotent operation previously closed without a committed effect"
            ),
        )

    async def _quarantined_replay_result(
        self,
        *,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
        reservation: IdempotencyReservationRecord,
    ) -> SafeguardCoordinatedDispatchResult | None:
        if reservation.state is not ReservationState.OUTCOME_UNKNOWN:
            return None
        closure_key = content_digest(
            {
                "domain": "post-release-closure-key",
                "reservation_identity_digest": reservation.identity.identity_digest,
                "reservation_attempt": reservation.identity.acquisition_receipt.attempt,
            }
        )
        closure = await self._closure_store.read(closure_key)
        if closure is None or closure.outcome is not PostReleaseClosureOutcome.QUARANTINED:
            return None
        evidence = await self._evidence_store.read(
            closure.identity.target_digest,
            closure.identity.target_fence_generation,
        )
        if evidence is None or not self._recovery._evidence_matches_action(
            evidence=evidence,
            action=action,
            safeguard_receipt=safeguard_receipt,
        ):
            return None
        return SafeguardCoordinatedDispatchResult(
            disposition=SafeguardCoordinationDisposition.QUARANTINED,
            bundle_digest=evidence.bundle.bundle_digest,
            lifecycle=None,
            closure_receipt=None,
            dispatch_performed=False,
            reason="prior dispatch outcome remains quarantined",
        )

    async def _evidence_for_fence(
        self,
        *,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
        fence: TargetDispatchFenceRecord,
    ) -> SafeguardDispatchEvidenceRecord | None:
        evidence = await self._evidence_store.read(
            fence.identity.target_digest,
            fence.identity.generation,
        )
        if evidence is None or not self._recovery._evidence_matches_action(
            evidence=evidence,
            action=action,
            safeguard_receipt=safeguard_receipt,
        ):
            return None
        return evidence

    async def _bundle_for_fence(
        self,
        *,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
        fence: TargetDispatchFenceRecord,
    ) -> str | None:
        evidence = await self._evidence_for_fence(
            action=action,
            safeguard_receipt=safeguard_receipt,
            fence=fence,
        )
        return evidence.bundle.bundle_digest if evidence is not None else None


def _closure_proves_applied(
    *,
    closure: PostReleaseClosureRecord,
    evidence: SafeguardDispatchEvidenceRecord,
) -> bool:
    """Use final reconciliation, or initial sink evidence, to prove an effect."""

    if closure.outcome is not PostReleaseClosureOutcome.RESOLVED:
        return False
    reconciliation = closure.reconciliation_evidence
    if reconciliation is not None:
        return reconciliation.outcome in {
            ReconciliationOutcome.SINK_COMMITTED,
            ReconciliationOutcome.EFFECT_VERIFIED,
        }
    observation = evidence.dispatch_observation
    return observation is not None and observation.sink_state is AuthoritativeSinkState.COMMITTED


__all__ = ["SafeguardLifecyclePreparer"]
