"""Durable production recovery after failed workflow compensation.

Replace the legacy ``release_verified`` close-out with one auditable path that
creates a distinct recovery attempt (#652), binds separate human approval and a
finalized safeguard bundle, claims the attempt exactly once under the logical
target fence (#640), keeps an unresolved provider dispatch in doubt, records an
independent authoritative post-effect observation with current and superseded
completion claims (#656), consumes exactly one current successful claim through
the approval-guarded hold release (#630), and terminalizes the Process and Saga
audit through a replay-healable completion outbox (#658).

This module owns the end-to-end order of that path. Each stage lives in a
focused sibling module and is re-exported here so the public import surface
is unchanged:

* :mod:`fdai.core.workflow.recovery_coordinator_models` - records, protocols,
  and configuration.
* :mod:`fdai.core.workflow.recovery_coordinator_records` - durable key
  namespace and strict record codecs.
* :mod:`fdai.core.workflow.recovery_coordinator_support` - shared evidence
  journal and admission gate.
* :mod:`fdai.core.workflow.recovery_coordinator_binding` - attempt identity,
  approval, and safeguard-bundle binding.
* :mod:`fdai.core.workflow.recovery_coordinator_dispatch` - exactly-once claim
  and exclusive in-flight dispatch.
* :mod:`fdai.core.workflow.recovery_coordinator_effect` - independent
  post-effect observation and completion claims.
* :mod:`fdai.core.workflow.recovery_coordinator_release` - approval-guarded
  hold release and its durable lookup.
* :mod:`fdai.core.workflow.recovery_coordinator_terminalization` - terminal
  Process and Saga commit through a replayable outbox.

Every record persisted here is evidence. None of it grants execution,
approval, or effect-verification authority.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from fdai.core.workflow.automation_hold import StateStoreAutomationHoldLedger
from fdai.core.workflow.recovery_attempt import (
    RecoveryApprovalEvidence,
    RecoveryAttemptIdentity,
    RecoveryAttemptRejectionReason,
    RecoveryDispatchOutcome,
    recovery_attempt_step_id,
)
from fdai.core.workflow.recovery_coordinator_binding import RecoveryAttemptBinder
from fdai.core.workflow.recovery_coordinator_dispatch import RecoveryDispatchCoordinator
from fdai.core.workflow.recovery_coordinator_effect import RecoveryEffectCoordinator
from fdai.core.workflow.recovery_coordinator_models import (
    RecoveryApprovalReader,
    RecoveryApprovalRequester,
    RecoveryClaimDispatchState,
    RecoveryCoordinationResult,
    RecoveryCoordinatorConfig,
    RecoveryDispatchPort,
    RecoveryDisposition,
    RecoveryEffectObservation,
    RecoveryEffectObservationIntake,
    RecoveryEffectObserver,
    RecoverySafeguardBundleReader,
)
from fdai.core.workflow.recovery_coordinator_records import (
    ATTEMPT_PREFIX,
    active_hold_revision,
    admission_reason,
    approval_digest,
    approver_identity,
    attempt_from_record,
    read_recovery_attempt,
)
from fdai.core.workflow.recovery_coordinator_release import RecoveryReleaseLedger
from fdai.core.workflow.recovery_coordinator_support import (
    RecoveryAdmissionGate,
    RecoveryEvidenceJournal,
)
from fdai.core.workflow.recovery_coordinator_terminalization import RecoveryTerminalizer
from fdai.core.workflow.recovery_effect_claim import EffectEvidenceClass, is_current_success
from fdai.core.workflow.recovery_terminalization import TerminalTransitionRejection
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.process_runtime import ProcessRuntimeStore, ProcessSnapshot
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)


class WorkflowRecoveryCoordinator:
    """Run the complete production recovery path for one held Process."""

    __slots__ = (
        "_admission",
        "_audit_store",
        "_binder",
        "_config",
        "_dispatch",
        "_effect",
        "_holds",
        "_journal",
        "_release",
        "_terminalizer",
    )

    def __init__(
        self,
        *,
        process_store: ProcessRuntimeStore,
        audit_store: StateStore,
        holds: StateStoreAutomationHoldLedger,
        config: RecoveryCoordinatorConfig,
        dispatcher: RecoveryDispatchPort | None = None,
        effect_observer: RecoveryEffectObserver | None = None,
        effect_observations: RecoveryEffectObservationIntake | None = None,
        approval_reader: RecoveryApprovalReader | None = None,
        approval_requester: RecoveryApprovalRequester | None = None,
        admission_provider: DecisionEvidenceAdmissionProvider | None = None,
        bundle_reader: RecoverySafeguardBundleReader | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._audit_store = audit_store
        self._holds = holds
        self._config = config
        self._journal = RecoveryEvidenceJournal(
            audit_store=audit_store,
            clock=clock or (lambda: datetime.now(tz=UTC)),
        )
        self._admission = RecoveryAdmissionGate(
            admission_provider=admission_provider,
            config=config,
            journal=self._journal,
        )
        self._binder = RecoveryAttemptBinder(
            audit_store=audit_store,
            config=config,
            journal=self._journal,
            approval_reader=approval_reader,
            approval_requester=approval_requester,
            bundle_reader=bundle_reader,
        )
        self._dispatch = RecoveryDispatchCoordinator(
            audit_store=audit_store,
            config=config,
            journal=self._journal,
            dispatcher=dispatcher,
        )
        self._effect = RecoveryEffectCoordinator(
            admission=self._admission,
            audit_store=audit_store,
            config=config,
            journal=self._journal,
            effect_observer=effect_observer,
            effect_observations=effect_observations,
        )
        self._release = RecoveryReleaseLedger(
            admission=self._admission,
            audit_store=audit_store,
            config=config,
            holds=holds,
            journal=self._journal,
        )
        self._terminalizer = RecoveryTerminalizer(
            audit_store=audit_store,
            effect=self._effect,
            journal=self._journal,
            process_store=process_store,
            release_ledger=self._release,
        )

    async def recover(
        self,
        *,
        snapshot: ProcessSnapshot,
        failed_compensation_proposal_digest: str,
        recovery_action_type: str,
        recovery_params: Mapping[str, object],
        compensation_receipt_digests: tuple[str, ...],
    ) -> RecoveryCoordinationResult:
        """Advance one held Process through the complete recovery path."""

        hold = await self._holds.read_hold_record(target_ref=snapshot.target_resource_id)
        hold_revision = active_hold_revision(hold, process_id=snapshot.process_id)
        if hold_revision is None:
            return RecoveryCoordinationResult(disposition=RecoveryDisposition.NOT_REQUIRED)

        try:
            attempt = await self._binder.build_attempt(
                snapshot=snapshot,
                failed_compensation_proposal_digest=failed_compensation_proposal_digest,
                recovery_action_type=recovery_action_type,
                recovery_params=recovery_params,
                hold_revision=hold_revision,
            )
        except ValueError as exc:
            return await self._journal.reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.IDENTITY_INVALID,
                detail=str(exc)[:256],
            )
        if attempt.failed_compensation_proposal_digest == attempt.recovery_payload_digest:
            return await self._journal.reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.PROPOSAL_REUSE,
                attempt=attempt,
            )

        healed = await self._terminalizer.heal_committed(snapshot=snapshot, attempt=attempt)
        if healed is not None:
            return healed

        approval = await self._binder.resolve_approval(snapshot=snapshot, attempt=attempt)
        if approval is None:
            await self._binder.request_approval(snapshot=snapshot, attempt=attempt)
            return await self._journal.reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.APPROVAL_MISSING,
                attempt=attempt,
            )
        admitted = await self._admission.assess(
            snapshot=snapshot,
            approval=approval,
            hold_revision=hold_revision,
            compensation_receipt_digests=compensation_receipt_digests,
        )
        if not admitted.eligible or admitted.admission is None:
            return await self._journal.reject(
                snapshot,
                reason=admission_reason(admitted),
                detail=",".join(reason.value for reason in admitted.rejection_reasons)[:256],
                attempt=attempt,
            )
        approval_evidence = RecoveryApprovalEvidence.create(
            attempt_identity_digest=attempt.identity_digest,
            approval_digest=approval_digest(approval),
            approved_at=approval.requested_at,
            approver_identity=approver_identity(approval),
        )
        await self._binder.persist_attempt(
            attempt=attempt,
            approval_evidence=approval_evidence,
            process_id=snapshot.process_id,
        )

        claim = await self._dispatch.claim_once(attempt=attempt, hold_revision=hold_revision)
        if claim is None:
            return await self._journal.reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.CLAIM_CONFLICT,
                attempt=attempt,
            )
        fenced_hold = await self._holds.read_hold_record(target_ref=snapshot.target_resource_id)
        if active_hold_revision(fenced_hold, process_id=snapshot.process_id) != hold_revision:
            return await self._journal.reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.STALE_HOLD,
                attempt=attempt,
            )
        if not await self._holds.authorize_hold_scoped_dispatch(
            target_ref=snapshot.target_resource_id,
            process_id=snapshot.process_id,
            step_id=recovery_attempt_step_id(attempt),
            hold_revision=hold_revision,
        ):
            return await self._journal.reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.STALE_HOLD,
                attempt=attempt,
                claim=claim,
            )

        dispatch = await self._dispatch.dispatch_once(
            snapshot=snapshot,
            attempt=attempt,
            claim=claim,
            safeguard_bundle_digest=(
                await self._binder.resolve_bundle(snapshot=snapshot, attempt=attempt) or ""
            ),
            recovery_params=recovery_params,
        )
        if dispatch.outcome != RecoveryDispatchOutcome.DISPATCHED:
            return await self._journal.reject(
                snapshot,
                reason=(
                    RecoveryAttemptRejectionReason.IN_DOUBT
                    if dispatch.outcome == RecoveryDispatchOutcome.IN_DOUBT
                    else RecoveryAttemptRejectionReason.NOT_INVOKED
                ),
                attempt=attempt,
                claim=claim,
                disposition=(
                    RecoveryDisposition.IN_DOUBT
                    if dispatch.outcome == RecoveryDispatchOutcome.IN_DOUBT
                    else RecoveryDisposition.REJECTED
                ),
            )
        provider_receipt_digest = dispatch.provider_receipt_digest
        if provider_receipt_digest is None:
            return await self._journal.reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.PROVIDER_RECEIPT_MISSING,
                attempt=attempt,
                claim=claim,
            )

        bundle_digest = await self._binder.bind_safeguard_evidence(
            snapshot=snapshot, attempt=attempt
        )
        if bundle_digest is None:
            return await self._journal.reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.SAFEGUARD_DENIED,
                attempt=attempt,
                claim=claim,
            )

        effect = await self._effect.claim_effect(
            snapshot=snapshot,
            attempt=attempt,
            hold_revision=hold_revision,
            safeguard_bundle_digest=bundle_digest,
            provider_receipt_digest=provider_receipt_digest,
            approval=approval,
            compensation_receipt_digests=compensation_receipt_digests,
        )
        effect_claim = effect.claim
        if effect_claim is None or not is_current_success(effect_claim, now=self._journal.now()):
            return await self._journal.reject(
                snapshot,
                reason=effect.reason,
                attempt=attempt,
                claim=claim,
                disposition=effect.disposition,
            )

        return await self._terminalizer.terminalize(
            snapshot=snapshot,
            attempt=attempt,
            claim=claim,
            effect_claim=effect_claim,
            approval=approval,
            hold_revision=hold_revision,
            compensation_receipt_digests=compensation_receipt_digests,
        )

    async def record_independent_observation(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        target_resource_id: str,
        provider_receipt_digest: str,
        observation: RecoveryEffectObservation,
    ) -> bool:
        """Persist one observation an independent authority reported.

        This records evidence only. The recovery path still re-verifies
        identity separation, finality, and admission before any claim, so
        persisting an observation never verifies an effect, and an unbound
        intake stays a visible fail-closed state.
        """

        return await self._effect.record_independent_observation(
            attempt=attempt,
            target_resource_id=target_resource_id,
            provider_receipt_digest=provider_receipt_digest,
            observation=observation,
        )

    async def heal(self, *, snapshot: ProcessSnapshot) -> RecoveryCoordinationResult | None:
        """Repair a crash between hold release, Process CAS, and Saga delivery.

        A durable release lookup proves the approval-guarded release already
        consumed one exact completion claim, so healing terminalizes from that
        consumed binding even after the claim's own validity window closed. A
        lineage that no longer matches the durable release, or a claim that was
        superseded, still fails closed (#658).
        """

        record = await self._audit_store.find_state(
            ATTEMPT_PREFIX,
            field="process_id",
            value=snapshot.process_id,
        )
        if record is None:
            return None
        attempt = attempt_from_record(record)
        if attempt is None:
            return None
        healed = await self._terminalizer.heal_committed(snapshot=snapshot, attempt=attempt)
        if healed is not None:
            return healed
        lookup = await self._release.read_release_lookup_for(attempt)
        if lookup is None:
            return None
        effect_claim = await self._effect.read_current_claim(attempt)
        if effect_claim is None or effect_claim.claim_digest != lookup.effect_claim_digest:
            return None
        consumed_at = await self._release.consumed_release_instant(
            snapshot=snapshot,
            lookup=lookup,
            effect_claim=effect_claim,
        )
        if consumed_at is None:
            return await self._journal.reject(
                snapshot,
                reason=TerminalTransitionRejection.RELEASE_RECEIPT_MISSING.value,
                attempt=attempt,
                disposition=RecoveryDisposition.EFFECT_UNVERIFIED,
            )
        return await self._terminalizer.commit_terminal(
            snapshot=snapshot,
            attempt=attempt,
            effect_claim=effect_claim,
            release_receipt_digest=lookup.release_receipt_digest,
            hold_revision=lookup.hold_revision,
            evaluated_at=consumed_at,
        )


__all__ = [
    "EffectEvidenceClass",
    "RecoveryApprovalReader",
    "RecoveryApprovalRequester",
    "RecoveryClaimDispatchState",
    "RecoveryCoordinationResult",
    "RecoveryCoordinatorConfig",
    "RecoveryDispatchPort",
    "RecoveryDisposition",
    "RecoveryEffectObservation",
    "RecoveryEffectObservationIntake",
    "RecoveryEffectObserver",
    "RecoverySafeguardBundleReader",
    "WorkflowRecoveryCoordinator",
    "read_recovery_attempt",
]
