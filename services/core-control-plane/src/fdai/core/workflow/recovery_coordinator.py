"""Durable production recovery after failed workflow compensation.

Replace the legacy ``release_verified`` close-out with one auditable path that
creates a distinct recovery attempt (#652), binds separate human approval and a
finalized safeguard bundle, claims the attempt exactly once under the logical
target fence (#640), keeps an unresolved provider dispatch in doubt, records an
independent authoritative post-effect observation with current and superseded
completion claims (#656), consumes exactly one current successful claim through
the approval-guarded hold release (#630), and terminalizes the Process and Saga
audit through a replay-healable completion outbox (#658).

Every record persisted here is evidence. None of it grants execution,
approval, or effect-verification authority.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.workflow.automation_hold import (
    AutomationHoldReleaseReceipt,
    StateStoreAutomationHoldLedger,
)
from fdai.core.workflow.recovery_admission import (
    WorkflowRecoveryAdmissionAssessment,
    WorkflowRecoveryAdmissionRejectionReason,
    assess_workflow_recovery_admission,
)
from fdai.core.workflow.recovery_attempt import (
    RecoveryApprovalEvidence,
    RecoveryAttemptIdentity,
    RecoveryAttemptRejectionReason,
    RecoveryDispatchOutcome,
    RecoveryDispatchResult,
    RecoveryPreDispatchClaim,
    RecoverySafeguardEvidence,
    recovery_attempt_idempotency_key,
    recovery_attempt_step_id,
)
from fdai.core.workflow.recovery_effect_claim import (
    CompletionClaimRejectionReason,
    EffectCompletionClaim,
    EffectEvidenceClass,
    EffectEvidenceRecord,
    FinalizedWatermark,
    is_current_success,
    supersede_claim,
    verify_effect_evidence,
)
from fdai.core.workflow.recovery_terminalization import (
    CompletionOutboxEntry,
    OutboxDeliveryState,
    RecoveryCompletionDigest,
    ReleaseReceiptLookup,
    TerminalTransitionRejection,
    check_replay_idempotent,
    validate_terminal_preconditions,
)
from fdai.core.workflow.workflow_runtime import WorkflowApprovalSnapshot, event_id
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.process_runtime import (
    ProcessEvent,
    ProcessEventKind,
    ProcessRevisionConflictError,
    ProcessRuntimeStore,
    ProcessSnapshot,
    ProcessStatus,
)
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)

_ACTOR = "fdai.core.workflow.recovery_coordinator"
_ATTEMPT_PREFIX = "workflow:recovery-attempt:"
_CLAIM_PREFIX = "workflow:recovery-claim:"
_EFFECT_PREFIX = "workflow:recovery-effect:"
_LOOKUP_PREFIX = "workflow:recovery-release-lookup:"
_OUTBOX_PREFIX = "workflow:recovery-outbox:"

_DEFAULT_CLAIM_VALIDITY = timedelta(minutes=30)
_DEFAULT_DISPATCH_LEASE = timedelta(minutes=5)
_PROCESS_EVENT_DELIVERY = "process_event"
_SAGA_AUDIT_DELIVERY = "saga_audit"


class RecoveryDisposition(StrEnum):
    """Caller-facing recovery outcome with no execution authority."""

    NOT_REQUIRED = "not_required"
    REJECTED = "rejected"
    IN_DOUBT = "in_doubt"
    OBSERVER_UNAVAILABLE = "observer_unavailable"
    EFFECT_UNVERIFIED = "effect_unverified"
    COMPLETED = "completed"
    REPLAYED = "replayed"


class RecoveryClaimDispatchState(StrEnum):
    """Exclusive ownership state of one pre-dispatch recovery claim."""

    UNCLAIMED = "unclaimed"
    IN_FLIGHT = "in_flight"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class _InFlightLease:
    """Proof that this caller owns the exclusive in-flight claim."""

    owner: str
    took_over: bool


@dataclass(frozen=True, slots=True)
class _EffectClaimOutcome:
    """One effect-claim attempt with the exact reason it did not complete.

    A missing observer or intake binding is a readiness fact, not an unverified
    effect, so the two never collapse into the same silent disposition.
    """

    claim: EffectCompletionClaim | None
    reason: str
    disposition: RecoveryDisposition


@dataclass(frozen=True, slots=True)
class RecoveryCoordinationResult:
    """Immutable recovery evidence returned to the compensation caller."""

    disposition: RecoveryDisposition
    reason: str | None = None
    attempt_identity_digest: str | None = None
    claim_digest: str | None = None
    effect_claim_digest: str | None = None
    release_receipt_digest: str | None = None
    completion_digest: str | None = None
    execution_authority: Literal[False] = False
    approval_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False or self.approval_authority is not False:
            raise ValueError("recovery coordination result MUST NOT grant authority")

    @property
    def recovery_incomplete(self) -> bool:
        """Whether the hold MUST stay in force after this attempt."""

        return self.disposition not in {
            RecoveryDisposition.COMPLETED,
            RecoveryDisposition.REPLAYED,
            RecoveryDisposition.NOT_REQUIRED,
        }


@dataclass(frozen=True, slots=True)
class RecoveryEffectObservation:
    """One independent authoritative post-effect observation and its envelope."""

    evidence: EffectEvidenceRecord
    observer_identity: str
    provider_identity: str
    expected_effect_digest: str
    approved_envelope_digest: str
    action_digest: str
    evidence_window_start: datetime
    evidence_window_end: datetime
    watermarks: tuple[FinalizedWatermark, ...]
    success: bool

    def __post_init__(self) -> None:
        if not self.watermarks:
            raise ValueError("recovery effect observation requires at least one watermark")
        if self.evidence_window_end <= self.evidence_window_start:
            raise ValueError("recovery effect evidence window MUST be positive")

    @property
    def watermark_set_digest(self) -> str:
        """Bind every authoritative finality watermark into one digest."""

        return content_digest(
            [
                {
                    "source_id": watermark.source_id,
                    "watermark": watermark.watermark.astimezone(UTC).isoformat(),
                    "final": watermark.final,
                    "watermark_digest": watermark.watermark_digest,
                }
                for watermark in sorted(self.watermarks, key=lambda item: item.source_id)
            ]
        )

    @property
    def finalized(self) -> bool:
        """Whether every authoritative source reported finality."""

        return all(watermark.final for watermark in self.watermarks)


@runtime_checkable
class RecoveryDispatchPort(Protocol):
    """Dispatch one claimed recovery attempt and reconcile an in-doubt result."""

    async def dispatch_recovery(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
        safeguard_bundle_digest: str,
        target_resource_id: str,
        params: Mapping[str, object],
        correlation_id: str,
    ) -> RecoveryDispatchResult: ...

    async def reconcile_recovery(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
    ) -> RecoveryDispatchResult | None: ...


@runtime_checkable
class RecoveryEffectObserver(Protocol):
    """Return one authoritative post-effect observation independent of dispatch."""

    async def observe_recovery_effect(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        target_resource_id: str,
        provider_receipt_digest: str,
        observed_at: datetime,
    ) -> RecoveryEffectObservation | None: ...


@runtime_checkable
class RecoveryEffectObservationIntake(Protocol):
    """Persist one independent authoritative post-effect observation.

    This is the explicit seam an observer that is independent of the executor
    and the provider writes through. An implementation persists evidence only;
    it never grants effect-verification authority and MUST refuse evidence the
    executor or provider owns.
    """

    async def record_observation(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        target_resource_id: str,
        provider_receipt_digest: str,
        observation: RecoveryEffectObservation,
    ) -> bool: ...


@runtime_checkable
class RecoverySafeguardBundleReader(Protocol):
    """Return the finalized safeguard bundle digest bound to one recovery attempt."""

    async def finalized_recovery_bundle_digest(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        target_resource_id: str,
    ) -> str | None: ...


@runtime_checkable
class RecoveryApprovalReader(Protocol):
    """Resolve the separate immutable human approval for one recovery attempt."""

    async def recovery_approval(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        process_id: str,
        target_resource_id: str,
    ) -> WorkflowApprovalSnapshot | None: ...


@runtime_checkable
class RecoveryApprovalRequester(Protocol):
    """Ask a separate human to decide one recovery attempt.

    Requesting is never granting: an implementation persists the pending ask
    in the human-decision journal and returns. Only a separate human decision
    recorded there can make the attempt admissible.
    """

    async def request_recovery_approval(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        process_id: str,
        target_resource_id: str,
        correlation_id: str,
    ) -> WorkflowApprovalSnapshot: ...


@dataclass(frozen=True, slots=True)
class RecoveryCoordinatorConfig:
    """Immutable identity and quorum configuration for the recovery path."""

    executor_identity: str
    source_revision: str
    quorum: int = 1
    no_self_approval: bool = True
    claim_validity: timedelta = _DEFAULT_CLAIM_VALIDITY
    dispatch_lease: timedelta = _DEFAULT_DISPATCH_LEASE

    def __post_init__(self) -> None:
        if not self.executor_identity.strip():
            raise ValueError("recovery coordinator requires an executor_identity")
        if not self.source_revision.strip() or len(self.source_revision) > 512:
            raise ValueError("recovery coordinator requires a bounded source_revision")
        if self.quorum < 1:
            raise ValueError("recovery coordinator quorum MUST be positive")
        if not self.no_self_approval:
            raise ValueError("recovery coordinator MUST keep no-self-approval enabled")
        if self.claim_validity <= timedelta(0):
            raise ValueError("recovery coordinator claim validity MUST be positive")
        if self.dispatch_lease <= timedelta(0):
            raise ValueError("recovery coordinator dispatch lease MUST be positive")


class WorkflowRecoveryCoordinator:
    """Run the complete production recovery path for one held Process."""

    __slots__ = (
        "_process_store",
        "_audit_store",
        "_holds",
        "_dispatcher",
        "_effect_observer",
        "_effect_observations",
        "_approval_reader",
        "_approval_requester",
        "_admission_provider",
        "_bundle_reader",
        "_config",
        "_clock",
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
        self._process_store = process_store
        self._audit_store = audit_store
        self._holds = holds
        self._dispatcher = dispatcher
        self._effect_observer = effect_observer
        self._effect_observations = effect_observations
        self._approval_reader = approval_reader
        self._approval_requester = approval_requester
        self._admission_provider = admission_provider
        self._bundle_reader = bundle_reader
        self._config = config
        self._clock = clock or (lambda: datetime.now(tz=UTC))

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
        hold_revision = _active_hold_revision(hold, process_id=snapshot.process_id)
        if hold_revision is None:
            return RecoveryCoordinationResult(disposition=RecoveryDisposition.NOT_REQUIRED)

        try:
            attempt = await self._build_attempt(
                snapshot=snapshot,
                failed_compensation_proposal_digest=failed_compensation_proposal_digest,
                recovery_action_type=recovery_action_type,
                recovery_params=recovery_params,
                hold_revision=hold_revision,
            )
        except ValueError as exc:
            return await self._reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.IDENTITY_INVALID,
                detail=str(exc)[:256],
            )
        if attempt.failed_compensation_proposal_digest == attempt.recovery_payload_digest:
            return await self._reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.PROPOSAL_REUSE,
                attempt=attempt,
            )

        healed = await self._heal_committed(snapshot=snapshot, attempt=attempt)
        if healed is not None:
            return healed

        approval = await self._resolve_approval(snapshot=snapshot, attempt=attempt)
        if approval is None:
            await self._request_approval(snapshot=snapshot, attempt=attempt)
            return await self._reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.APPROVAL_MISSING,
                attempt=attempt,
            )
        admitted = await self._assess_admission(
            snapshot=snapshot,
            approval=approval,
            hold_revision=hold_revision,
            compensation_receipt_digests=compensation_receipt_digests,
        )
        if not admitted.eligible or admitted.admission is None:
            return await self._reject(
                snapshot,
                reason=_admission_reason(admitted),
                detail=",".join(reason.value for reason in admitted.rejection_reasons)[:256],
                attempt=attempt,
            )
        approval_evidence = RecoveryApprovalEvidence.create(
            attempt_identity_digest=attempt.identity_digest,
            approval_digest=_approval_digest(approval),
            approved_at=approval.requested_at,
            approver_identity=_approver_identity(approval),
        )
        await self._persist_attempt(
            attempt=attempt,
            approval_evidence=approval_evidence,
            process_id=snapshot.process_id,
        )

        claim = await self._claim_once(attempt=attempt, hold_revision=hold_revision)
        if claim is None:
            return await self._reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.CLAIM_CONFLICT,
                attempt=attempt,
            )
        fenced_hold = await self._holds.read_hold_record(target_ref=snapshot.target_resource_id)
        if _active_hold_revision(fenced_hold, process_id=snapshot.process_id) != hold_revision:
            return await self._reject(
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
            return await self._reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.STALE_HOLD,
                attempt=attempt,
                claim=claim,
            )

        dispatch = await self._dispatch_once(
            snapshot=snapshot,
            attempt=attempt,
            claim=claim,
            safeguard_bundle_digest=(
                await self._resolve_bundle(snapshot=snapshot, attempt=attempt) or ""
            ),
            recovery_params=recovery_params,
        )
        if dispatch.outcome != RecoveryDispatchOutcome.DISPATCHED:
            return await self._reject(
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
            return await self._reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.PROVIDER_RECEIPT_MISSING,
                attempt=attempt,
                claim=claim,
            )

        bundle_digest = await self._bind_safeguard_evidence(snapshot=snapshot, attempt=attempt)
        if bundle_digest is None:
            return await self._reject(
                snapshot,
                reason=RecoveryAttemptRejectionReason.SAFEGUARD_DENIED,
                attempt=attempt,
                claim=claim,
            )

        effect = await self._claim_effect(
            snapshot=snapshot,
            attempt=attempt,
            hold_revision=hold_revision,
            safeguard_bundle_digest=bundle_digest,
            provider_receipt_digest=provider_receipt_digest,
            approval=approval,
            compensation_receipt_digests=compensation_receipt_digests,
        )
        effect_claim = effect.claim
        if effect_claim is None or not is_current_success(effect_claim, now=self._now()):
            return await self._reject(
                snapshot,
                reason=effect.reason,
                attempt=attempt,
                claim=claim,
                disposition=effect.disposition,
            )

        return await self._terminalize(
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

        intake = self._effect_observations
        if intake is None:
            _LOGGER.warning(
                "workflow_recovery_effect_observation_intake_unbound",
                extra={"process_id": attempt.process_id},
            )
            return False
        try:
            return await intake.record_observation(
                attempt=attempt,
                target_resource_id=target_resource_id,
                provider_receipt_digest=provider_receipt_digest,
                observation=observation,
            )
        except Exception:  # noqa: BLE001 - an unwritable observation stays unverified
            _LOGGER.exception(
                "workflow_recovery_effect_observation_write_failed",
                extra={"process_id": attempt.process_id},
            )
            return False

    async def heal(self, *, snapshot: ProcessSnapshot) -> RecoveryCoordinationResult | None:
        """Repair a crash between hold release, Process CAS, and Saga delivery.

        A durable release lookup proves the approval-guarded release already
        consumed one exact completion claim, so healing terminalizes from that
        consumed binding even after the claim's own validity window closed. A
        lineage that no longer matches the durable release, or a claim that was
        superseded, still fails closed (#658).
        """

        record = await self._audit_store.find_state(
            _ATTEMPT_PREFIX,
            field="process_id",
            value=snapshot.process_id,
        )
        if record is None:
            return None
        attempt = _attempt_from_record(record)
        if attempt is None:
            return None
        healed = await self._heal_committed(snapshot=snapshot, attempt=attempt)
        if healed is not None:
            return healed
        lookup = await self._read_release_lookup_for(attempt)
        if lookup is None:
            return None
        effect_claim = await self._read_current_claim(attempt)
        if effect_claim is None or effect_claim.claim_digest != lookup.effect_claim_digest:
            return None
        consumed_at = await self._consumed_release_instant(
            snapshot=snapshot,
            lookup=lookup,
            effect_claim=effect_claim,
        )
        if consumed_at is None:
            return await self._reject(
                snapshot,
                reason=TerminalTransitionRejection.RELEASE_RECEIPT_MISSING.value,
                attempt=attempt,
                disposition=RecoveryDisposition.EFFECT_UNVERIFIED,
            )
        return await self._commit_terminal(
            snapshot=snapshot,
            attempt=attempt,
            effect_claim=effect_claim,
            release_receipt_digest=lookup.release_receipt_digest,
            hold_revision=lookup.hold_revision,
            evaluated_at=consumed_at,
        )

    async def _consumed_release_instant(
        self,
        *,
        snapshot: ProcessSnapshot,
        lookup: ReleaseReceiptLookup,
        effect_claim: EffectCompletionClaim,
    ) -> datetime | None:
        """Return when the durable release consumed this exact claim.

        Returns ``None`` unless the persisted hold record still proves the same
        release receipt, released hold revision, fencing generation, Process,
        and consumed admission that this completion claim was bound to, and the
        hold was not reissued after that release.
        """

        record = await self._holds.read_hold_record(target_ref=snapshot.target_resource_id)
        if record is None or record.get("state") != "released":
            return None
        receipt = record.get("release_receipt")
        if not isinstance(receipt, Mapping):
            return None
        if (
            receipt.get("receipt_digest") != lookup.release_receipt_digest
            or receipt.get("released_hold_revision") != lookup.hold_revision
            or receipt.get("process_id") != snapshot.process_id
            or receipt.get("target_digest") != _target_evidence_digest(snapshot.target_resource_id)
            or record.get("fencing_generation") != lookup.hold_revision + 1
            or record.get("revision") != lookup.hold_revision + 1
        ):
            return None
        if record.get("consumed_recovery_admission_digest") != effect_claim.admission_digest:
            return None
        released_at = _aware_or_none(receipt.get("released_at"))
        if released_at is None or released_at < effect_claim.validity_start.astimezone(UTC):
            return None
        return released_at

    # -- attempt identity ---------------------------------------------------

    async def _build_attempt(
        self,
        *,
        snapshot: ProcessSnapshot,
        failed_compensation_proposal_digest: str,
        recovery_action_type: str,
        recovery_params: Mapping[str, object],
        hold_revision: int,
    ) -> RecoveryAttemptIdentity:
        existing, _ = await self._audit_store.read_state_page(
            _ATTEMPT_PREFIX,
            limit=64,
            field="process_id",
            value=snapshot.process_id,
        )
        attempt_number = 1 + sum(
            1
            for row in existing
            if isinstance(row.get("attempt_number"), int)
            and row.get("hold_revision") != hold_revision
        )
        return RecoveryAttemptIdentity.create(
            process_id=snapshot.process_id,
            failed_compensation_proposal_digest=failed_compensation_proposal_digest,
            hold_revision=hold_revision,
            recovery_action_type=recovery_action_type,
            recovery_payload_digest=content_digest(
                {
                    "action_type": recovery_action_type,
                    "params": dict(recovery_params),
                    "purpose": "workflow-recovery-payload",
                }
            ),
            target_digest=_target_evidence_digest(snapshot.target_resource_id),
            source_revision=self._config.source_revision,
            attempt_number=attempt_number,
        )

    async def _persist_attempt(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        approval_evidence: RecoveryApprovalEvidence,
        process_id: str,
    ) -> None:
        key = _attempt_key(attempt)
        record = {
            "process_id": process_id,
            "recovery_step_id": recovery_attempt_step_id(attempt),
            "attempt_identity_digest": attempt.identity_digest,
            "failed_compensation_proposal_digest": (attempt.failed_compensation_proposal_digest),
            "hold_revision": attempt.hold_revision,
            "recovery_action_type": attempt.recovery_action_type,
            "recovery_payload_digest": attempt.recovery_payload_digest,
            "target_digest": attempt.target_digest,
            "source_revision": attempt.source_revision,
            "attempt_number": attempt.attempt_number,
            "approval_evidence_digest": approval_evidence.evidence_digest,
            "approver_identity": approval_evidence.approver_identity,
            "safeguard_bundle_digest": None,
            "safeguard_evidence_digest": None,
            "execution_authority": False,
            "revision": 1,
        }
        created = await self._audit_store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "actor": _ACTOR,
                "action_kind": "workflow.recovery.attempt_bound",
                **record,
            },
        )
        if created:
            return
        stored = await self._audit_store.read_state(key)
        if stored is None or stored.get("attempt_identity_digest") != attempt.identity_digest:
            raise ValueError("recovery attempt identity conflicted with a stored attempt")
        if stored.get("approval_evidence_digest") != approval_evidence.evidence_digest:
            raise ValueError("recovery attempt approval evidence is not immutable")

    async def _bind_safeguard_evidence(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
    ) -> str | None:
        """Bind the finalized safeguard bundle this attempt dispatched under.

        The executor finalizes the bundle inside its own logical-target lock,
        so the workflow binds it once the production dispatch retained it. The
        binding is immutable: a different bundle for the same attempt fails
        closed and the hold stays in force.
        """

        key = _attempt_key(attempt)
        stored = await self._read_mapping(key)
        if stored is None:
            return None
        bundle_digest = await self._resolve_bundle(snapshot=snapshot, attempt=attempt)
        if bundle_digest is None:
            return None
        evidence = RecoverySafeguardEvidence.create(
            attempt_identity_digest=attempt.identity_digest,
            safeguard_bundle_digest=bundle_digest,
            completed_at=self._now(),
        )
        recorded = stored.get("safeguard_bundle_digest")
        if recorded is not None:
            return str(recorded) if recorded == bundle_digest else None
        revision = _int_or_none(stored.get("revision"))
        if revision is None:
            return None
        updated = {
            **stored,
            "safeguard_bundle_digest": evidence.safeguard_bundle_digest,
            "safeguard_evidence_digest": evidence.evidence_digest,
            "revision": revision + 1,
        }
        committed = await self._audit_store.compare_and_set_state_with_audit(
            key,
            updated,
            expected_revision=revision,
            audit_entry={
                "actor": _ACTOR,
                "action_kind": "workflow.recovery.safeguard_bundle_bound",
                "attempt_identity_digest": attempt.identity_digest,
                "safeguard_bundle_digest": evidence.safeguard_bundle_digest,
                "safeguard_evidence_digest": evidence.evidence_digest,
                "execution_authority": False,
            },
        )
        if committed:
            return bundle_digest
        current = await self._read_mapping(key)
        if current is None or current.get("safeguard_bundle_digest") != bundle_digest:
            return None
        return bundle_digest

    # -- approval and safeguard binding -------------------------------------

    async def _request_approval(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
    ) -> None:
        """Ask a separate human for this exact attempt, never grant it."""

        requester = self._approval_requester
        if requester is None:
            return
        try:
            await requester.request_recovery_approval(
                attempt=attempt,
                process_id=snapshot.process_id,
                target_resource_id=snapshot.target_resource_id,
                correlation_id=snapshot.correlation_id,
            )
        except Exception:  # noqa: BLE001 - an unrequestable approval keeps the hold
            _LOGGER.exception(
                "workflow_recovery_approval_request_failed",
                extra={"process_id": snapshot.process_id},
            )
            return
        await self._audit(
            snapshot,
            action_kind="workflow.recovery.approval_requested",
            payload={
                "attempt_identity_digest": attempt.identity_digest,
                "recovery_step_id": recovery_attempt_step_id(attempt),
                "approval_authority": False,
            },
        )

    async def _resolve_approval(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
    ) -> WorkflowApprovalSnapshot | None:
        """Return the approval bound to this exact attempt, without judging it.

        Eligibility belongs to ``assess_workflow_recovery_admission``; this seam
        only proves that a separate approval record exists for this Process.
        """

        if self._approval_reader is None:
            return None
        approval = await self._approval_reader.recovery_approval(
            attempt=attempt,
            process_id=snapshot.process_id,
            target_resource_id=snapshot.target_resource_id,
        )
        if approval is None or approval.process_id != snapshot.process_id:
            return None
        return approval

    async def _assess_admission(
        self,
        *,
        snapshot: ProcessSnapshot,
        approval: WorkflowApprovalSnapshot,
        hold_revision: int,
        compensation_receipt_digests: tuple[str, ...],
    ) -> WorkflowRecoveryAdmissionAssessment:
        """Assess current approval, quorum, identity separation, and admission."""

        return await assess_workflow_recovery_admission(
            self._admission_provider,
            snapshot=approval,
            quorum=self._config.quorum,
            no_self_approval=self._config.no_self_approval,
            hold_revision=hold_revision,
            target_digest=_target_evidence_digest(snapshot.target_resource_id),
            compensation_receipt_digests=compensation_receipt_digests,
            executor_identity=self._config.executor_identity,
            source_revision=self._config.source_revision,
            evaluated_at=self._now(),
        )

    async def _resolve_bundle(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
    ) -> str | None:
        if self._bundle_reader is None:
            return None
        digest = await self._bundle_reader.finalized_recovery_bundle_digest(
            attempt=attempt,
            target_resource_id=snapshot.target_resource_id,
        )
        if digest is None or _DIGEST_LENGTH != len(digest) or not digest.startswith("sha256:"):
            return None
        return digest

    # -- exactly-once claim under the target fence --------------------------

    async def _claim_once(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        hold_revision: int,
    ) -> RecoveryPreDispatchClaim | None:
        key = _claim_key(attempt, hold_revision)
        existing = await self._audit_store.read_state(key)
        if existing is not None:
            return _claim_from_record(existing, attempt=attempt, hold_revision=hold_revision)
        claim = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=attempt.identity_digest,
            hold_revision=hold_revision,
            claim_revision=1,
            idempotency_key=recovery_attempt_idempotency_key(attempt),
            claimed_at=self._now(),
        )
        record = {
            "process_id": attempt.process_id,
            "attempt_identity_digest": claim.attempt_identity_digest,
            "hold_revision": claim.hold_revision,
            "claim_revision": claim.claim_revision,
            "idempotency_key": claim.idempotency_key,
            "claimed_at": claim.claimed_at.astimezone(UTC).isoformat(),
            "claim_digest": claim.claim_digest,
            "dispatch_state": RecoveryClaimDispatchState.UNCLAIMED,
            "in_flight_owner": None,
            "in_flight_expires_at": None,
            "dispatch_outcome": RecoveryDispatchOutcome.NOT_INVOKED,
            "provider_receipt_digest": None,
            "execution_authority": False,
            "revision": 1,
        }
        created = await self._audit_store.write_state_with_audit_if_absent(
            key,
            record,
            {
                "actor": _ACTOR,
                "action_kind": "workflow.recovery.claim_acquired",
                **record,
            },
        )
        if created:
            return claim
        stored = await self._audit_store.read_state(key)
        if stored is None:
            return None
        return _claim_from_record(stored, attempt=attempt, hold_revision=hold_revision)

    async def _dispatch_once(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
        safeguard_bundle_digest: str,
        recovery_params: Mapping[str, object],
    ) -> RecoveryDispatchResult:
        key = _claim_key(attempt, claim.hold_revision)
        stored = await self._audit_store.read_state(key)
        recorded = _dispatch_from_record(stored, claim=claim)
        if recorded is not None and recorded.outcome == RecoveryDispatchOutcome.DISPATCHED:
            return recorded
        if self._dispatcher is None:
            return RecoveryDispatchResult.create(
                attempt_identity_digest=attempt.identity_digest,
                claim_digest=claim.claim_digest,
                outcome=RecoveryDispatchOutcome.NOT_INVOKED,
                provider_receipt_digest=None,
                recorded_at=self._now(),
            )
        lease = await self._acquire_in_flight(key=key, claim=claim, stored=stored)
        if lease is None:
            # Another caller owns the exclusive in-flight claim: this caller
            # never invokes the provider and stays in doubt until that owner
            # resolves or its lease expires.
            _LOGGER.info(
                "workflow_recovery_dispatch_claim_held",
                extra={"process_id": snapshot.process_id},
            )
            return RecoveryDispatchResult.create(
                attempt_identity_digest=attempt.identity_digest,
                claim_digest=claim.claim_digest,
                outcome=RecoveryDispatchOutcome.IN_DOUBT,
                provider_receipt_digest=None,
                recorded_at=self._now(),
            )
        unresolved = recorded is not None and recorded.outcome == RecoveryDispatchOutcome.IN_DOUBT
        if unresolved or lease.took_over:
            reconciled = await self._reconcile(attempt=attempt, claim=claim)
            result = (
                reconciled
                if reconciled is not None
                else (
                    recorded
                    if recorded is not None
                    else RecoveryDispatchResult.create(
                        attempt_identity_digest=attempt.identity_digest,
                        claim_digest=claim.claim_digest,
                        outcome=RecoveryDispatchOutcome.IN_DOUBT,
                        provider_receipt_digest=None,
                        recorded_at=self._now(),
                    )
                )
            )
        else:
            try:
                result = await self._dispatcher.dispatch_recovery(
                    attempt=attempt,
                    claim=claim,
                    safeguard_bundle_digest=safeguard_bundle_digest,
                    target_resource_id=snapshot.target_resource_id,
                    params=dict(recovery_params),
                    correlation_id=snapshot.correlation_id,
                )
            except Exception:  # noqa: BLE001 - an unresolved dispatch stays in doubt
                _LOGGER.exception(
                    "workflow_recovery_dispatch_in_doubt",
                    extra={"process_id": snapshot.process_id},
                )
                result = RecoveryDispatchResult.create(
                    attempt_identity_digest=attempt.identity_digest,
                    claim_digest=claim.claim_digest,
                    outcome=RecoveryDispatchOutcome.IN_DOUBT,
                    provider_receipt_digest=None,
                    recorded_at=self._now(),
                )
        await self._record_dispatch(key=key, claim=claim, result=result, lease=lease)
        return result

    async def _acquire_in_flight(
        self,
        *,
        key: str,
        claim: RecoveryPreDispatchClaim,
        stored: Mapping[str, Any] | None,
    ) -> _InFlightLease | None:
        """Own the claim exclusively, or return ``None`` and stay in doubt.

        Exactly one caller may hold the in-flight claim for one attempt and
        hold revision, so a concurrent recovery never invokes the provider a
        second time. A lease that expires is taken over only for
        reconciliation, never for a fresh provider invocation.
        """

        record = dict(stored) if stored is not None else None
        for _ in range(3):
            if record is None:
                return None
            revision = _int_or_none(record.get("revision"))
            if revision is None:
                return None
            if record.get("dispatch_outcome") == RecoveryDispatchOutcome.DISPATCHED:
                return None
            now = self._now()
            took_over = False
            if record.get("dispatch_state") == RecoveryClaimDispatchState.IN_FLIGHT:
                expires_at = _aware_or_none(record.get("in_flight_expires_at"))
                if expires_at is None or now < expires_at:
                    return None
                took_over = True
            owner = secrets.token_urlsafe(24)
            updated = {
                **record,
                "dispatch_state": RecoveryClaimDispatchState.IN_FLIGHT,
                "in_flight_owner": owner,
                "in_flight_claimed_at": now.isoformat(),
                "in_flight_expires_at": (now + self._config.dispatch_lease).isoformat(),
                "revision": revision + 1,
            }
            claimed = await self._audit_store.compare_and_set_state_with_audit(
                key,
                updated,
                expected_revision=revision,
                audit_entry={
                    "actor": _ACTOR,
                    "action_kind": "workflow.recovery.dispatch_claim_acquired",
                    "attempt_identity_digest": claim.attempt_identity_digest,
                    "claim_digest": claim.claim_digest,
                    "hold_revision": claim.hold_revision,
                    "took_over_expired_lease": took_over,
                    "execution_authority": False,
                },
            )
            if claimed:
                return _InFlightLease(owner=owner, took_over=took_over)
            record = await self._read_mapping(key)
        return None

    async def _reconcile(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
    ) -> RecoveryDispatchResult | None:
        if self._dispatcher is None:
            return None
        try:
            return await self._dispatcher.reconcile_recovery(attempt=attempt, claim=claim)
        except Exception:  # noqa: BLE001 - reconciliation outage keeps the doubt
            _LOGGER.exception(
                "workflow_recovery_reconciliation_failed",
                extra={"process_id": attempt.process_id},
            )
            return None

    async def _record_dispatch(
        self,
        *,
        key: str,
        claim: RecoveryPreDispatchClaim,
        result: RecoveryDispatchResult,
        lease: _InFlightLease,
    ) -> None:
        for _ in range(3):
            stored = await self._read_mapping(key)
            if stored is None:
                return
            revision = _int_or_none(stored.get("revision"))
            if revision is None:
                return
            if (
                stored.get("dispatch_outcome") == RecoveryDispatchOutcome.DISPATCHED
                and stored.get("in_flight_owner") != lease.owner
            ):
                return
            updated = {
                **stored,
                "dispatch_state": RecoveryClaimDispatchState.RESOLVED,
                "in_flight_owner": None,
                "in_flight_expires_at": None,
                "dispatch_outcome": result.outcome,
                "provider_receipt_digest": result.provider_receipt_digest,
                "dispatch_result_digest": result.result_digest,
                "dispatch_recorded_at": result.recorded_at.astimezone(UTC).isoformat(),
                "revision": revision + 1,
            }
            committed = await self._audit_store.compare_and_set_state_with_audit(
                key,
                updated,
                expected_revision=revision,
                audit_entry={
                    "actor": _ACTOR,
                    "action_kind": "workflow.recovery.dispatch_recorded",
                    "attempt_identity_digest": claim.attempt_identity_digest,
                    "claim_digest": claim.claim_digest,
                    "outcome": result.outcome,
                    "provider_receipt_digest": result.provider_receipt_digest,
                    "dispatch_result_digest": result.result_digest,
                },
            )
            if committed:
                return

    async def _read_mapping(self, key: str) -> dict[str, Any] | None:
        stored = await self._audit_store.read_state(key)
        return dict(stored) if stored is not None else None

    # -- authoritative effect verification ----------------------------------

    async def _claim_effect(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        hold_revision: int,
        safeguard_bundle_digest: str,
        provider_receipt_digest: str,
        approval: WorkflowApprovalSnapshot,
        compensation_receipt_digests: tuple[str, ...],
    ) -> _EffectClaimOutcome:
        if self._effect_observer is None:
            return _unavailable(RecoveryAttemptRejectionReason.EFFECT_OBSERVER_UNBOUND)
        observed_at = self._now()
        try:
            observation = await self._effect_observer.observe_recovery_effect(
                attempt=attempt,
                target_resource_id=snapshot.target_resource_id,
                provider_receipt_digest=provider_receipt_digest,
                observed_at=observed_at,
            )
        except Exception:  # noqa: BLE001 - an observation outage leaves the effect unverified
            _LOGGER.exception(
                "workflow_recovery_effect_observation_failed",
                extra={"process_id": snapshot.process_id},
            )
            return _unavailable(RecoveryAttemptRejectionReason.EFFECT_OBSERVATION_UNREADABLE)
        if observation is None:
            if self._effect_observations is None:
                # No independent observation was recorded and no intake is
                # bound, so none can ever arrive: that is a readiness fact
                # about this deployment, not an unverified effect.
                return _unavailable(
                    RecoveryAttemptRejectionReason.EFFECT_OBSERVATION_INTAKE_UNBOUND,
                )
            return _unverified(RecoveryAttemptRejectionReason.EFFECT_OBSERVATION_MISSING)
        eligible, reasons = verify_effect_evidence(
            evidence=observation.evidence,
            executor_identity=self._config.executor_identity,
            provider_identity=observation.provider_identity,
        )
        if not eligible or not observation.finalized:
            await self._audit(
                snapshot,
                action_kind="workflow.recovery.effect_rejected",
                payload={
                    "attempt_identity_digest": attempt.identity_digest,
                    "rejection_reasons": [str(reason) for reason in reasons],
                    "finalized": observation.finalized,
                },
            )
            return _unverified(CompletionClaimRejectionReason.EVIDENCE_INELIGIBLE.value)
        admission_digest = await self._admission_digest(
            snapshot=snapshot,
            approval=approval,
            hold_revision=hold_revision,
            compensation_receipt_digests=compensation_receipt_digests,
        )
        if admission_digest is None:
            return _unavailable(RecoveryAttemptRejectionReason.EFFECT_ADMISSION_UNAVAILABLE)
        generation = await self._next_generation(attempt)
        validity_start = observation.evidence_window_end
        claim = (
            EffectCompletionClaim.create_success
            if observation.success
            else EffectCompletionClaim.create_non_success
        )(
            attempt_identity_digest=attempt.identity_digest,
            action_digest=observation.action_digest,
            safeguard_bundle_digest=safeguard_bundle_digest,
            provider_receipt_digest=provider_receipt_digest,
            target_digest=attempt.target_digest,
            expected_effect_digest=observation.expected_effect_digest,
            approved_envelope_digest=observation.approved_envelope_digest,
            source_revision=attempt.source_revision,
            evidence_window_start=observation.evidence_window_start,
            evidence_window_end=observation.evidence_window_end,
            effect_evidence_digest=observation.evidence.evidence_digest,
            validity_start=validity_start,
            validity_end=validity_start + self._config.claim_validity,
            watermark_set_digest=observation.watermark_set_digest,
            hold_revision=hold_revision,
            admission_digest=admission_digest,
            generation=generation,
        )
        persisted = await self._persist_claim(
            attempt=attempt,
            claim=claim,
            observation=observation,
        )
        if persisted is None:
            return _unverified(CompletionClaimRejectionReason.DUPLICATE_CLAIM.value)
        return _EffectClaimOutcome(
            claim=persisted,
            reason=CompletionClaimRejectionReason.EVIDENCE_INELIGIBLE.value,
            disposition=RecoveryDisposition.EFFECT_UNVERIFIED,
        )

    async def _persist_claim(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        claim: EffectCompletionClaim,
        observation: RecoveryEffectObservation,
    ) -> EffectCompletionClaim | None:
        key = _effect_key(attempt)
        stored = await self._audit_store.read_state(key)
        observation_record = {
            "observer_identity": observation.observer_identity,
            "observer_authority_class": str(observation.evidence.observer_authority_class),
            "purpose_version": observation.evidence.purpose_version,
            "method_version": observation.evidence.method_version,
            "event_time": observation.evidence.event_time.astimezone(UTC).isoformat(),
            "recorded_time": observation.evidence.recorded_time.astimezone(UTC).isoformat(),
            "freshness_policy_seconds": observation.evidence.freshness_policy_seconds,
            "completeness": observation.evidence.completeness,
            "provenance": observation.evidence.provenance,
            "conflict_status": observation.evidence.conflict_status,
            "evidence_digest": observation.evidence.evidence_digest,
            "watermark_set_digest": observation.watermark_set_digest,
        }
        claim_record = _claim_record(claim)
        if stored is None:
            record = {
                "process_id": attempt.process_id,
                "attempt_identity_digest": attempt.identity_digest,
                "current_claim_digest": claim.claim_digest,
                "generation": claim.generation,
                "claims": [claim_record],
                "observations": [observation_record],
                "execution_authority": False,
                "revision": 1,
            }
            created = await self._audit_store.write_state_with_audit_if_absent(
                key,
                record,
                {
                    "actor": _ACTOR,
                    "action_kind": "workflow.recovery.effect_claimed",
                    "attempt_identity_digest": attempt.identity_digest,
                    "claim_digest": claim.claim_digest,
                    "generation": claim.generation,
                    "success": claim.success,
                    "effect_evidence_digest": claim.effect_evidence_digest,
                },
            )
            return claim if created else await self._read_current_claim(attempt)
        revision = _int_or_none(stored.get("revision"))
        if revision is None:
            return None
        prior_claims = _claim_records(stored)
        superseded: list[Mapping[str, Any]] = []
        for prior in prior_claims:
            restored = _claim_from_mapping(prior)
            if restored is None or restored.superseded_by is not None:
                superseded.append(prior)
                continue
            superseded.append(
                _claim_record(supersede_claim(restored, superseding_digest=claim.claim_digest))
            )
        updated = {
            **dict(stored),
            "current_claim_digest": claim.claim_digest,
            "generation": claim.generation,
            "claims": [*superseded, claim_record],
            "observations": [*_observation_records(stored), observation_record],
            "revision": revision + 1,
        }
        committed = await self._audit_store.compare_and_set_state_with_audit(
            key,
            updated,
            expected_revision=revision,
            audit_entry={
                "actor": _ACTOR,
                "action_kind": "workflow.recovery.effect_claim_superseded",
                "attempt_identity_digest": attempt.identity_digest,
                "claim_digest": claim.claim_digest,
                "generation": claim.generation,
                "success": claim.success,
            },
        )
        if not committed:
            return await self._read_current_claim(attempt)
        return claim

    async def _next_generation(self, attempt: RecoveryAttemptIdentity) -> int:
        stored = await self._audit_store.read_state(_effect_key(attempt))
        if stored is None:
            return 1
        generation = _int_or_none(stored.get("generation"))
        return 1 if generation is None else generation + 1

    async def _read_current_claim(
        self,
        attempt: RecoveryAttemptIdentity,
    ) -> EffectCompletionClaim | None:
        stored = await self._audit_store.read_state(_effect_key(attempt))
        if stored is None:
            return None
        current = stored.get("current_claim_digest")
        for raw in _claim_records(stored):
            if raw.get("claim_digest") == current:
                return _claim_from_mapping(raw)
        return None

    async def _admission_digest(
        self,
        *,
        snapshot: ProcessSnapshot,
        approval: WorkflowApprovalSnapshot,
        hold_revision: int,
        compensation_receipt_digests: tuple[str, ...],
    ) -> str | None:
        assessment = await self._assess_admission(
            snapshot=snapshot,
            approval=approval,
            hold_revision=hold_revision,
            compensation_receipt_digests=compensation_receipt_digests,
        )
        if not assessment.eligible or assessment.admission is None:
            return None
        return assessment.admission.receipt_digest

    # -- atomic release and terminalization ---------------------------------

    async def _terminalize(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        claim: RecoveryPreDispatchClaim,
        effect_claim: EffectCompletionClaim,
        approval: WorkflowApprovalSnapshot,
        hold_revision: int,
        compensation_receipt_digests: tuple[str, ...],
    ) -> RecoveryCoordinationResult:
        lookup = await self._read_release_lookup(
            attempt=attempt,
            effect_claim=effect_claim,
            hold_revision=hold_revision,
        )
        release_receipt_digest = lookup.release_receipt_digest if lookup is not None else None
        if release_receipt_digest is None:
            receipt = await self._release(
                snapshot=snapshot,
                attempt=attempt,
                effect_claim=effect_claim,
                approval=approval,
                hold_revision=hold_revision,
                compensation_receipt_digests=compensation_receipt_digests,
            )
            if receipt is None:
                return await self._reject(
                    snapshot,
                    reason=RecoveryAttemptRejectionReason.SAFEGUARD_DENIED,
                    attempt=attempt,
                    claim=claim,
                )
            release_receipt_digest = receipt.receipt_digest
            await self._store_release_lookup(
                attempt=attempt,
                effect_claim=effect_claim,
                hold_revision=hold_revision,
                release_receipt_digest=release_receipt_digest,
            )
        return await self._commit_terminal(
            snapshot=snapshot,
            attempt=attempt,
            effect_claim=effect_claim,
            release_receipt_digest=release_receipt_digest,
            hold_revision=hold_revision,
        )

    async def _release(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        effect_claim: EffectCompletionClaim,
        approval: WorkflowApprovalSnapshot,
        hold_revision: int,
        compensation_receipt_digests: tuple[str, ...],
    ) -> AutomationHoldReleaseReceipt | None:
        assessment = await self._assess_admission(
            snapshot=snapshot,
            approval=approval,
            hold_revision=hold_revision,
            compensation_receipt_digests=compensation_receipt_digests,
        )
        if (
            not assessment.eligible
            or assessment.admission is None
            or assessment.admission.receipt_digest != effect_claim.admission_digest
        ):
            return None
        try:
            return await self._holds.release_admitted(
                target_ref=snapshot.target_resource_id,
                process_id=snapshot.process_id,
                action_id=_recovery_action_id(attempt),
                hold_revision=hold_revision,
                approval_snapshot=approval,
                quorum=self._config.quorum,
                no_self_approval=self._config.no_self_approval,
                compensation_receipt_digests=compensation_receipt_digests,
                executor_identity=self._config.executor_identity,
                source_revision=self._config.source_revision,
                assessment=assessment,
                workflow_lineage=(
                    snapshot.process_id,
                    recovery_attempt_step_id(attempt),
                ),
            )
        except Exception:  # noqa: BLE001 - release persistence keeps the hold in force
            _LOGGER.exception(
                "workflow_recovery_release_failed",
                extra={"process_id": snapshot.process_id},
            )
            return None

    async def _store_release_lookup(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        effect_claim: EffectCompletionClaim,
        hold_revision: int,
        release_receipt_digest: str,
    ) -> None:
        lookup = ReleaseReceiptLookup.create(
            recovery_attempt_digest=attempt.identity_digest,
            effect_claim_digest=effect_claim.claim_digest,
            hold_revision=hold_revision,
            release_receipt_digest=release_receipt_digest,
        )
        record = {
            "process_id": attempt.process_id,
            "recovery_attempt_digest": lookup.recovery_attempt_digest,
            "effect_claim_digest": lookup.effect_claim_digest,
            "hold_revision": lookup.hold_revision,
            "release_receipt_digest": lookup.release_receipt_digest,
            "lookup_digest": lookup.lookup_digest,
            "execution_authority": False,
            "revision": 1,
        }
        await self._audit_store.write_state_with_audit_if_absent(
            _lookup_key(attempt, effect_claim, hold_revision),
            record,
            {
                "actor": _ACTOR,
                "action_kind": "workflow.recovery.release_lookup_stored",
                **record,
            },
        )

    async def _read_release_lookup(
        self,
        *,
        attempt: RecoveryAttemptIdentity,
        effect_claim: EffectCompletionClaim,
        hold_revision: int,
    ) -> ReleaseReceiptLookup | None:
        stored = await self._audit_store.read_state(
            _lookup_key(attempt, effect_claim, hold_revision)
        )
        return _lookup_from_record(stored)

    async def _read_release_lookup_for(
        self,
        attempt: RecoveryAttemptIdentity,
    ) -> ReleaseReceiptLookup | None:
        stored = await self._audit_store.find_state(
            _LOOKUP_PREFIX,
            field="recovery_attempt_digest",
            value=attempt.identity_digest,
        )
        return _lookup_from_record(stored)

    async def _commit_terminal(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        effect_claim: EffectCompletionClaim,
        release_receipt_digest: str,
        hold_revision: int,
        evaluated_at: datetime | None = None,
    ) -> RecoveryCoordinationResult:
        current = await self._process_store.get(snapshot.process_id) or snapshot
        committed = await self._committed_completion_digest(snapshot.process_id)
        terminal_event_digest = content_digest(
            {
                "domain": "workflow-recovery-terminal-event",
                "process_id": current.process_id,
                "attempt_identity_digest": attempt.identity_digest,
                "effect_claim_digest": effect_claim.claim_digest,
            }
        )
        audit_payload_digest = content_digest(
            {
                "domain": "workflow-recovery-saga-audit",
                "process_id": current.process_id,
                "release_receipt_digest": release_receipt_digest,
                "effect_claim_digest": effect_claim.claim_digest,
            }
        )
        expected_revision = current.revision if committed is None else current.revision - 1
        completion = RecoveryCompletionDigest.create(
            process_id=current.process_id,
            saga_id=current.correlation_id,
            expected_process_revision=max(expected_revision, 0),
            recovery_attempt_digest=attempt.identity_digest,
            effect_claim_generation=effect_claim.generation,
            effect_claim_digest=effect_claim.claim_digest,
            release_receipt_digest=release_receipt_digest,
            terminal_event_digest=terminal_event_digest,
            audit_payload_digest=audit_payload_digest,
        )
        if check_replay_idempotent(
            committed_completion_digest=committed,
            expected_completion_digest=completion.completion_digest,
        ):
            await self._drain_outbox(snapshot=current, completion=completion)
            return RecoveryCoordinationResult(
                disposition=RecoveryDisposition.REPLAYED,
                attempt_identity_digest=attempt.identity_digest,
                effect_claim_digest=effect_claim.claim_digest,
                release_receipt_digest=release_receipt_digest,
                completion_digest=completion.completion_digest,
            )
        eligible, reasons = validate_terminal_preconditions(
            claim=effect_claim,
            completion=completion,
            hold_revision=hold_revision,
            fencing_generation=hold_revision + 1,
            process_revision=max(expected_revision, 0),
            expected_completion_digest=completion.completion_digest,
            release_receipt_digest=release_receipt_digest,
            committed_completion_digest=committed,
            now=evaluated_at if evaluated_at is not None else self._now(),
        )
        if not eligible:
            return await self._reject(
                current,
                reason=_terminal_reason(reasons),
                attempt=attempt,
                disposition=RecoveryDisposition.EFFECT_UNVERIFIED,
            )
        await self._stage_outbox(completion=completion)
        terminal = await self._append_terminal(
            snapshot=current,
            attempt=attempt,
            completion=completion,
            effect_claim=effect_claim,
            release_receipt_digest=release_receipt_digest,
        )
        if terminal is None:
            return await self._reject(
                current,
                reason=TerminalTransitionRejection.PROCESS_REVISION_CONFLICT.value,
                attempt=attempt,
                disposition=RecoveryDisposition.EFFECT_UNVERIFIED,
            )
        await self._drain_outbox(snapshot=terminal, completion=completion)
        return RecoveryCoordinationResult(
            disposition=RecoveryDisposition.COMPLETED,
            attempt_identity_digest=attempt.identity_digest,
            effect_claim_digest=effect_claim.claim_digest,
            release_receipt_digest=release_receipt_digest,
            completion_digest=completion.completion_digest,
        )

    async def _append_terminal(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        completion: RecoveryCompletionDigest,
        effect_claim: EffectCompletionClaim,
        release_receipt_digest: str,
    ) -> ProcessSnapshot | None:
        try:
            return await self._process_store.transition(
                process_id=snapshot.process_id,
                expected_revision=completion.expected_process_revision,
                status=ProcessStatus.COMPENSATED,
                current_step="",
                event=ProcessEvent(
                    event_id=event_id(
                        snapshot.process_id,
                        f"recovery:completed:{completion.completion_digest}",
                    ),
                    process_id=snapshot.process_id,
                    kind=ProcessEventKind.RECOVERY_COMPLETED,
                    idempotency_key=(
                        f"{snapshot.process_id}:recovery:{completion.completion_digest}"
                    ),
                    recorded_at=self._now(),
                    correlation_id=snapshot.correlation_id,
                    payload={
                        "completion_digest": completion.completion_digest,
                        "recovery_attempt_digest": attempt.identity_digest,
                        "effect_claim_digest": effect_claim.claim_digest,
                        "effect_claim_generation": effect_claim.generation,
                        "release_receipt_digest": release_receipt_digest,
                        "terminal_event_digest": completion.terminal_event_digest,
                        "audit_payload_digest": completion.audit_payload_digest,
                        "execution_authority": False,
                    },
                ),
            )
        except ProcessRevisionConflictError:
            _LOGGER.warning(
                "workflow_recovery_process_revision_conflict",
                extra={"process_id": snapshot.process_id},
            )
            return None

    async def _committed_completion_digest(self, process_id: str) -> str | None:
        events = await self._process_store.events(process_id)
        for event in reversed(events):
            if event.kind is ProcessEventKind.RECOVERY_COMPLETED:
                digest = event.payload.get("completion_digest")
                if isinstance(digest, str):
                    return digest
        return None

    # -- completion outbox --------------------------------------------------

    async def _stage_outbox(self, *, completion: RecoveryCompletionDigest) -> None:
        for kind, payload_digest in (
            (_PROCESS_EVENT_DELIVERY, completion.terminal_event_digest),
            (_SAGA_AUDIT_DELIVERY, completion.audit_payload_digest),
        ):
            entry = CompletionOutboxEntry.create_pending(
                completion_digest=completion.completion_digest,
                delivery_kind=kind,
                payload_digest=payload_digest,
            )
            record = {
                "process_id": completion.process_id,
                "completion_digest": entry.completion_digest,
                "delivery_kind": entry.delivery_kind,
                "delivery_state": entry.delivery_state,
                "payload_digest": entry.payload_digest,
                "attempt_count": entry.attempt_count,
                "entry_digest": entry.entry_digest,
                "execution_authority": False,
                "revision": 1,
            }
            await self._audit_store.write_state_with_audit_if_absent(
                _outbox_key(completion.completion_digest, kind),
                record,
                {
                    "actor": _ACTOR,
                    "action_kind": "workflow.recovery.outbox_staged",
                    **record,
                },
            )

    async def _drain_outbox(
        self,
        *,
        snapshot: ProcessSnapshot,
        completion: RecoveryCompletionDigest,
    ) -> None:
        for kind in (_PROCESS_EVENT_DELIVERY, _SAGA_AUDIT_DELIVERY):
            key = _outbox_key(completion.completion_digest, kind)
            stored = await self._audit_store.read_state(key)
            if stored is None:
                continue
            if stored.get("delivery_state") == OutboxDeliveryState.DELIVERED:
                continue
            revision = _int_or_none(stored.get("revision"))
            if revision is None:
                continue
            if kind == _SAGA_AUDIT_DELIVERY:
                await self._audit(
                    snapshot,
                    action_kind="workflow.recovery.completed",
                    payload={
                        "completion_digest": completion.completion_digest,
                        "recovery_attempt_digest": completion.recovery_attempt_digest,
                        "effect_claim_digest": completion.effect_claim_digest,
                        "release_receipt_digest": completion.release_receipt_digest,
                        "audit_payload_digest": completion.audit_payload_digest,
                    },
                )
            await self._audit_store.compare_and_set_state_with_audit(
                key,
                {
                    **dict(stored),
                    "delivery_state": OutboxDeliveryState.DELIVERED,
                    "attempt_count": (_int_or_none(stored.get("attempt_count")) or 0) + 1,
                    "last_attempt_at": self._now().isoformat(),
                    "revision": revision + 1,
                },
                expected_revision=revision,
                audit_entry={
                    "actor": _ACTOR,
                    "action_kind": "workflow.recovery.outbox_delivered",
                    "completion_digest": completion.completion_digest,
                    "delivery_kind": kind,
                    "payload_digest": stored.get("payload_digest"),
                },
            )

    async def _heal_committed(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
    ) -> RecoveryCoordinationResult | None:
        committed = await self._committed_completion_digest(snapshot.process_id)
        if committed is None:
            return None
        lookup = await self._read_release_lookup_for(attempt)
        effect_claim = await self._read_current_claim(attempt)
        completion = await self._committed_completion(snapshot.process_id, committed)
        if completion is not None:
            await self._drain_outbox(snapshot=snapshot, completion=completion)
        return RecoveryCoordinationResult(
            disposition=RecoveryDisposition.REPLAYED,
            attempt_identity_digest=attempt.identity_digest,
            effect_claim_digest=(effect_claim.claim_digest if effect_claim is not None else None),
            release_receipt_digest=(lookup.release_receipt_digest if lookup is not None else None),
            completion_digest=committed,
        )

    async def _committed_completion(
        self,
        process_id: str,
        completion_digest: str,
    ) -> RecoveryCompletionDigest | None:
        events = await self._process_store.events(process_id)
        for event in reversed(events):
            if (
                event.kind is not ProcessEventKind.RECOVERY_COMPLETED
                or event.payload.get("completion_digest") != completion_digest
            ):
                continue
            snapshot = await self._process_store.get(process_id)
            if snapshot is None:
                return None
            try:
                return RecoveryCompletionDigest.create(
                    process_id=process_id,
                    saga_id=event.correlation_id,
                    expected_process_revision=max(snapshot.revision - 1, 0),
                    recovery_attempt_digest=str(event.payload["recovery_attempt_digest"]),
                    effect_claim_generation=int(str(event.payload["effect_claim_generation"])),
                    effect_claim_digest=str(event.payload["effect_claim_digest"]),
                    release_receipt_digest=str(event.payload["release_receipt_digest"]),
                    terminal_event_digest=str(event.payload["terminal_event_digest"]),
                    audit_payload_digest=str(event.payload["audit_payload_digest"]),
                )
            except (KeyError, TypeError, ValueError):
                return None
        return None

    # -- shared helpers -----------------------------------------------------

    async def _reject(
        self,
        snapshot: ProcessSnapshot,
        *,
        reason: str,
        detail: str | None = None,
        attempt: RecoveryAttemptIdentity | None = None,
        claim: RecoveryPreDispatchClaim | None = None,
        disposition: RecoveryDisposition = RecoveryDisposition.REJECTED,
    ) -> RecoveryCoordinationResult:
        await self._audit(
            snapshot,
            action_kind="workflow.recovery.rejected",
            payload={
                "reason": reason,
                "detail": detail,
                "attempt_identity_digest": (
                    attempt.identity_digest if attempt is not None else None
                ),
                "claim_digest": claim.claim_digest if claim is not None else None,
                "recovery_incomplete": True,
            },
        )
        return RecoveryCoordinationResult(
            disposition=disposition,
            reason=reason,
            attempt_identity_digest=(attempt.identity_digest if attempt is not None else None),
            claim_digest=claim.claim_digest if claim is not None else None,
        )

    async def _audit(
        self,
        snapshot: ProcessSnapshot,
        *,
        action_kind: str,
        payload: Mapping[str, object],
    ) -> None:
        await self._audit_store.append_audit_entry(
            {
                "event_id": event_id(
                    snapshot.process_id,
                    f"recovery:{action_kind}:{content_digest(dict(payload))}",
                ),
                "correlation_id": snapshot.correlation_id,
                "actor": _ACTOR,
                "action_kind": action_kind,
                "process_id": snapshot.process_id,
                **dict(payload),
                "recorded_at": self._now().isoformat(),
            }
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recovery coordinator clock MUST return aware time")
        return value.astimezone(UTC)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_DIGEST_LENGTH = len("sha256:") + 64


def _target_evidence_digest(target_ref: str) -> str:
    return f"sha256:{hashlib.sha256(target_ref.encode()).hexdigest()}"


def _unavailable(reason: str) -> _EffectClaimOutcome:
    """Name a missing or unreadable observation binding as a readiness fact."""

    return _EffectClaimOutcome(
        claim=None,
        reason=reason,
        disposition=RecoveryDisposition.OBSERVER_UNAVAILABLE,
    )


def _unverified(reason: str) -> _EffectClaimOutcome:
    """Name why an available observation still did not verify the effect."""

    return _EffectClaimOutcome(
        claim=None,
        reason=reason,
        disposition=RecoveryDisposition.EFFECT_UNVERIFIED,
    )


async def read_recovery_attempt(
    store: StateStore,
    *,
    process_id: str,
    recovery_step_id: str,
) -> RecoveryAttemptIdentity | None:
    """Return the persisted recovery attempt one workflow step belongs to.

    A production writer that only sees workflow lineage uses this to rebind
    evidence to the exact attempt identity the coordinator already persisted.
    """

    record = await store.find_state(
        _ATTEMPT_PREFIX,
        field="recovery_step_id",
        value=recovery_step_id,
    )
    if record is None or record.get("process_id") != process_id:
        return None
    return _attempt_from_record(record)


def _admission_reason(assessment: WorkflowRecoveryAdmissionAssessment) -> str:
    """Return the exact typed reason one ineligible admission MUST report."""

    if not assessment.rejection_reasons:
        return RecoveryAttemptRejectionReason.APPROVAL_MISSING
    ranked = {
        WorkflowRecoveryAdmissionRejectionReason.APPROVAL_REJECTED: 0,
        WorkflowRecoveryAdmissionRejectionReason.SELF_APPROVAL: 1,
        WorkflowRecoveryAdmissionRejectionReason.EXECUTOR_IDENTITY_NOT_DISTINCT: 2,
        WorkflowRecoveryAdmissionRejectionReason.APPROVAL_CANCELLED: 3,
        WorkflowRecoveryAdmissionRejectionReason.APPROVAL_TIMED_OUT: 4,
        WorkflowRecoveryAdmissionRejectionReason.APPROVAL_EXPIRED: 5,
        WorkflowRecoveryAdmissionRejectionReason.APPROVAL_EXPIRY_MISSING: 6,
        WorkflowRecoveryAdmissionRejectionReason.QUORUM_NOT_MET: 7,
    }
    ordered = sorted(
        assessment.rejection_reasons,
        key=lambda reason: (ranked.get(reason, len(ranked)), reason.value),
    )
    return ordered[0].value


def _attempt_key(attempt: RecoveryAttemptIdentity) -> str:
    return f"{_ATTEMPT_PREFIX}{attempt.identity_digest.removeprefix('sha256:')}"


def _claim_key(attempt: RecoveryAttemptIdentity, hold_revision: int) -> str:
    digest = attempt.identity_digest.removeprefix("sha256:")
    return f"{_CLAIM_PREFIX}{digest}:{hold_revision}"


def _effect_key(attempt: RecoveryAttemptIdentity) -> str:
    return f"{_EFFECT_PREFIX}{attempt.identity_digest.removeprefix('sha256:')}"


def _lookup_key(
    attempt: RecoveryAttemptIdentity,
    effect_claim: EffectCompletionClaim,
    hold_revision: int,
) -> str:
    digest = content_digest(
        {
            "recovery_attempt_digest": attempt.identity_digest,
            "effect_claim_digest": effect_claim.claim_digest,
            "hold_revision": hold_revision,
        }
    )
    return f"{_LOOKUP_PREFIX}{digest.removeprefix('sha256:')}"


def _outbox_key(completion_digest: str, delivery_kind: str) -> str:
    return f"{_OUTBOX_PREFIX}{completion_digest.removeprefix('sha256:')}:{delivery_kind}"


def _recovery_action_id(attempt: RecoveryAttemptIdentity) -> str:
    return f"workflow-recovery:{attempt.identity_digest.removeprefix('sha256:')[:32]}"


def _approval_digest(snapshot: WorkflowApprovalSnapshot) -> str:
    return content_digest(
        {
            "process_id": snapshot.process_id,
            "step_id": snapshot.step_id,
            "attempt": snapshot.attempt,
            "revision": snapshot.revision,
            "requester_principal": snapshot.requester_principal,
            "decisions": sorted(
                (decision.principal.strip().casefold(), decision.decision, decision.receipt_ref)
                for decision in snapshot.decisions
            ),
        }
    )


def _approver_identity(snapshot: WorkflowApprovalSnapshot) -> str:
    approvers = sorted(
        decision.principal.strip().casefold()
        for decision in snapshot.decisions
        if decision.decision == "approved"
    )
    return approvers[0] if approvers else snapshot.requester_principal


def _active_hold_revision(record: Mapping[str, Any] | None, *, process_id: str) -> int | None:
    if record is None or record.get("state") != "active":
        return None
    if record.get("process_id") != process_id:
        return None
    return _int_or_none(record.get("revision"))


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _aware_or_none(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _attempt_from_record(record: Mapping[str, Any]) -> RecoveryAttemptIdentity | None:
    try:
        identity = RecoveryAttemptIdentity.create(
            process_id=str(record["process_id"]),
            failed_compensation_proposal_digest=str(record["failed_compensation_proposal_digest"]),
            hold_revision=int(str(record["hold_revision"])),
            recovery_action_type=str(record["recovery_action_type"]),
            recovery_payload_digest=str(record["recovery_payload_digest"]),
            target_digest=str(record["target_digest"]),
            source_revision=str(record["source_revision"]),
            attempt_number=int(str(record["attempt_number"])),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if identity.identity_digest != record.get("attempt_identity_digest"):
        return None
    return identity


def _claim_from_record(
    record: Mapping[str, Any],
    *,
    attempt: RecoveryAttemptIdentity,
    hold_revision: int,
) -> RecoveryPreDispatchClaim | None:
    try:
        claim = RecoveryPreDispatchClaim.create(
            attempt_identity_digest=str(record["attempt_identity_digest"]),
            hold_revision=int(str(record["hold_revision"])),
            claim_revision=int(str(record["claim_revision"])),
            idempotency_key=str(record["idempotency_key"]),
            claimed_at=datetime.fromisoformat(str(record["claimed_at"])),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if (
        claim.attempt_identity_digest != attempt.identity_digest
        or claim.hold_revision != hold_revision
        or claim.claim_digest != record.get("claim_digest")
        or claim.idempotency_key != recovery_attempt_idempotency_key(attempt)
    ):
        return None
    return claim


def _dispatch_from_record(
    record: Mapping[str, Any] | None,
    *,
    claim: RecoveryPreDispatchClaim,
) -> RecoveryDispatchResult | None:
    if record is None:
        return None
    outcome = record.get("dispatch_outcome")
    recorded_at = record.get("dispatch_recorded_at")
    if not isinstance(outcome, str) or not isinstance(recorded_at, str):
        return None
    receipt = record.get("provider_receipt_digest")
    try:
        result = RecoveryDispatchResult.create(
            attempt_identity_digest=claim.attempt_identity_digest,
            claim_digest=claim.claim_digest,
            outcome=outcome,
            provider_receipt_digest=receipt if isinstance(receipt, str) else None,
            recorded_at=datetime.fromisoformat(recorded_at),
        )
    except (TypeError, ValueError):
        return None
    if result.result_digest != record.get("dispatch_result_digest"):
        return None
    return result


def _claim_records(record: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = record.get("claims")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _observation_records(record: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = record.get("observations")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _claim_record(claim: EffectCompletionClaim) -> dict[str, Any]:
    return {
        "attempt_identity_digest": claim.attempt_identity_digest,
        "action_digest": claim.action_digest,
        "safeguard_bundle_digest": claim.safeguard_bundle_digest,
        "provider_receipt_digest": claim.provider_receipt_digest,
        "target_digest": claim.target_digest,
        "expected_effect_digest": claim.expected_effect_digest,
        "approved_envelope_digest": claim.approved_envelope_digest,
        "source_revision": claim.source_revision,
        "evidence_window_start": claim.evidence_window_start.astimezone(UTC).isoformat(),
        "evidence_window_end": claim.evidence_window_end.astimezone(UTC).isoformat(),
        "effect_evidence_digest": claim.effect_evidence_digest,
        "validity_start": claim.validity_start.astimezone(UTC).isoformat(),
        "validity_end": claim.validity_end.astimezone(UTC).isoformat(),
        "watermark_set_digest": claim.watermark_set_digest,
        "hold_revision": claim.hold_revision,
        "admission_digest": claim.admission_digest,
        "success": claim.success,
        "generation": claim.generation,
        "superseded_by": claim.superseded_by,
        "claim_digest": claim.claim_digest,
        "execution_authority": False,
    }


def _claim_from_mapping(record: Mapping[str, Any]) -> EffectCompletionClaim | None:
    try:
        return EffectCompletionClaim(
            attempt_identity_digest=str(record["attempt_identity_digest"]),
            action_digest=str(record["action_digest"]),
            safeguard_bundle_digest=str(record["safeguard_bundle_digest"]),
            provider_receipt_digest=str(record["provider_receipt_digest"]),
            target_digest=str(record["target_digest"]),
            expected_effect_digest=str(record["expected_effect_digest"]),
            approved_envelope_digest=str(record["approved_envelope_digest"]),
            source_revision=str(record["source_revision"]),
            evidence_window_start=datetime.fromisoformat(str(record["evidence_window_start"])),
            evidence_window_end=datetime.fromisoformat(str(record["evidence_window_end"])),
            effect_evidence_digest=str(record["effect_evidence_digest"]),
            validity_start=datetime.fromisoformat(str(record["validity_start"])),
            validity_end=datetime.fromisoformat(str(record["validity_end"])),
            watermark_set_digest=str(record["watermark_set_digest"]),
            hold_revision=int(str(record["hold_revision"])),
            admission_digest=str(record["admission_digest"]),
            success=bool(record["success"]),
            generation=int(str(record["generation"])),
            superseded_by=(
                str(record["superseded_by"]) if record.get("superseded_by") is not None else None
            ),
            claim_digest=str(record["claim_digest"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _lookup_from_record(record: Mapping[str, Any] | None) -> ReleaseReceiptLookup | None:
    if record is None:
        return None
    try:
        lookup = ReleaseReceiptLookup.create(
            recovery_attempt_digest=str(record["recovery_attempt_digest"]),
            effect_claim_digest=str(record["effect_claim_digest"]),
            hold_revision=int(str(record["hold_revision"])),
            release_receipt_digest=str(record["release_receipt_digest"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if lookup.lookup_digest != record.get("lookup_digest"):
        return None
    return lookup


def _terminal_reason(reasons: tuple[TerminalTransitionRejection, ...]) -> str:
    return reasons[0].value if reasons else TerminalTransitionRejection.ALREADY_TERMINAL.value


__all__ = [
    "EffectEvidenceClass",
    "RecoveryApprovalReader",
    "RecoveryCoordinationResult",
    "RecoveryCoordinatorConfig",
    "RecoveryDispatchPort",
    "RecoveryDisposition",
    "RecoveryEffectObservation",
    "RecoveryEffectObserver",
    "RecoverySafeguardBundleReader",
    "WorkflowRecoveryCoordinator",
]
