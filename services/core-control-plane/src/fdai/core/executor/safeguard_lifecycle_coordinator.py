"""Production coordinator for the complete safeguard evidence lifecycle."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.executor.audit_intent import (
    AuditIntentAppendDecision,
    AuditIntentStore,
    PreEffectAuditIntent,
)
from fdai.core.executor.hold_dispatch_fence import (
    HoldFenceAuditResult,
    HoldFenceCheckResult,
    HoldLineage,
    recheck_hold_fence,
)
from fdai.core.executor.idempotency_reservation import (
    IdempotencyReservationIdentity,
    IdempotencyReservationRecord,
    IdempotencyReservationStore,
    ReservationMatch,
    ReservationState,
)
from fdai.core.executor.idempotency_reservation_identity import same_operation
from fdai.core.executor.lock_continuity import EffectSinkContinuityPolicy
from fdai.core.executor.post_release_closure import PostReleaseClosureOutcome
from fdai.core.executor.post_release_closure_plan import (
    build_initial_post_release_closure,
)
from fdai.core.executor.post_release_closure_store import (
    PostReleaseClosureStore,
    PostReleaseClosureStoreReceipt,
)
from fdai.core.executor.safeguard_bundle_context import (
    SafeguardBundlePersistenceContext,
)
from fdai.core.executor.safeguard_dispatch_checkpoint import (
    AuthoritativeSinkState,
    DispatchTransportState,
    SafeguardDispatchEvidenceRecord,
)
from fdai.core.executor.safeguard_dispatch_store import (
    SafeguardDispatchEvidenceStore,
)
from fdai.core.executor.safeguard_evidence_lifecycle import (
    DispatchPort,
    LifecycleTerminalKind,
    SafeguardEvidenceLifecycleResult,
    cancel_before_dispatch,
    run_safeguard_evidence_lifecycle,
)
from fdai.core.executor.safeguard_pre_bundle import (
    SafeguardPreBundleCommitment,
    SafeguardPreBundleCommitmentStore,
)
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
from fdai.shared.contracts.models import Action, ExecutionPath
from fdai.shared.providers.automation_hold_state import (
    AutomationHoldStateReader,
    HoldReleaseAuthorizationReader,
)
from fdai.shared.providers.resource_lock import (
    EvidenceResourceLock,
    HeldResourceLock,
    ResourceLockAcquisitionRequest,
    require_evidence_resource_lock,
)
from fdai.shared.providers.state_store import StateStore

_SOURCE_REVISION = re.compile(r"^commit:[a-f0-9]{40}(?:[a-f0-9]{24})?$")
_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class ProductionSafeguardStore(Protocol):
    """Marker implemented only by durable production lifecycle stores."""

    @property
    def production_eligible(self) -> bool:
        """Whether the store is durable and safe for production composition."""
        ...


class SafeguardCoordinationDisposition(StrEnum):
    """Caller-facing result without granting execution authority."""

    COMPLETED = "completed"
    DUPLICATE = "duplicate"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"


class SafeguardCoordinationError(RuntimeError):
    """A required lifecycle phase failed before a safe dispatch result existed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SafeguardCoordinatedDispatchResult:
    """Final bundle and closure evidence returned to a real executor."""

    disposition: SafeguardCoordinationDisposition
    bundle_digest: str | None
    lifecycle: SafeguardEvidenceLifecycleResult | None
    closure_receipt: PostReleaseClosureStoreReceipt | None
    dispatch_performed: bool
    reason: str | None = None
    execution_authority: Literal[False] = False
    effect_verification_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False or self.effect_verification_authority is not False:
            raise ValueError("safeguard coordinated result MUST NOT grant authority")
        if self.dispatch_performed and self.bundle_digest is None:
            raise ValueError("a performed dispatch requires a finalized bundle digest")


@dataclass(frozen=True, slots=True)
class SafeguardLifecycleCoordinatorConfig:
    """Immutable production identity, timing, and trust configuration."""

    source_revision: str
    producer_id: str
    producer_version: str
    actor: str
    expected_lock_verifier_id: str
    expected_lock_verifier_version: str
    expected_lock_trust_anchor_id: str
    reservation_lease: timedelta = timedelta(minutes=5)
    production: bool = False

    def __post_init__(self) -> None:
        if _SOURCE_REVISION.fullmatch(self.source_revision) is None:
            raise ValueError("safeguard lifecycle source revision MUST be canonical")
        for name, value in (
            ("producer_id", self.producer_id),
            ("producer_version", self.producer_version),
            ("actor", self.actor),
            ("expected_lock_verifier_id", self.expected_lock_verifier_id),
            ("expected_lock_verifier_version", self.expected_lock_verifier_version),
            ("expected_lock_trust_anchor_id", self.expected_lock_trust_anchor_id),
        ):
            if not value.strip() or value != value.strip() or len(value) > 512:
                raise ValueError(f"safeguard lifecycle {name} MUST be canonical and bounded")
        if self.reservation_lease <= timedelta(0):
            raise ValueError("safeguard lifecycle reservation lease MUST be positive")


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
        self._audit_intent_store = audit_intent_store
        self._fence_store = fence_store
        self._evidence_store = evidence_store
        self._closure_store = closure_store
        self._denial_audit_store = denial_audit_store
        self._continuity_policy = continuity_policy
        self._config = config
        self._commitment_store = commitment_store
        self._hold_state_reader = hold_state_reader
        self._hold_release_authorizations = hold_release_authorizations
        self._clock = clock or (lambda: datetime.now(UTC))
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
        """Run prior phases, the shared lifecycle, release, and atomic closure."""

        if type(safeguard_receipt) is not SafeguardReceipt:
            return await self._deny(action, "safeguard receipt is missing or invalid")
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
            return await self._deny(action, str(exc))
        if attempt < 1:
            return await self._deny(action, "safeguard lifecycle attempt MUST be positive")

        acquisition_request = ResourceLockAcquisitionRequest.create(
            target_ref=action.target_resource_ref,
            action_digest=safeguard_receipt.action_digest,
            attempt=attempt,
            producer_id=self._config.producer_id,
            producer_version=self._config.producer_version,
            source_revision=self.source_revision,
        )
        held_lock: HeldResourceLock | None = None
        lifecycle: SafeguardEvidenceLifecycleResult | None = None
        release_error: BaseException | None = None
        try:
            async with self._resource_lock.acquire_evidenced(acquisition_request) as active_lock:
                held_lock = active_lock
                lifecycle_or_result = await self._dispatch_while_held(
                    action=action,
                    safeguard_receipt=safeguard_receipt,
                    commitment=commitment,
                    held_lock=active_lock,
                    dispatch_port=dispatch_port,
                    correlation_id=correlation_id,
                )
                if isinstance(lifecycle_or_result, SafeguardCoordinatedDispatchResult):
                    return lifecycle_or_result
                lifecycle = lifecycle_or_result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if lifecycle is None:
                return await self._deny(
                    action,
                    "safeguard lifecycle failed before terminal evidence: "
                    f"{type(exc).__name__}: {exc}",
                )
            release_error = exc

        if held_lock is None or lifecycle is None:
            return await self._deny(action, "safeguard lifecycle lost its held-lock result")
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
            return await self._deny(action, "post-release safeguard evidence is unavailable")
        in_flight_reservation = (
            evidence_record.dispatch_start_checkpoint.in_flight_reservation_receipt.record
        )
        closed_at = max(
            self._now(),
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

    async def _dispatch_while_held(
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
        reserved_at = max(self._now(), acquisition.acquired_at)
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
        if reservation_result.match is ReservationMatch.CONFLICT:
            if (
                same_operation(
                    reservation_result.observed_record.identity,
                    reservation_identity,
                )
                and reservation_result.observed_record.state is ReservationState.TERMINAL
            ):
                return SafeguardCoordinatedDispatchResult(
                    disposition=SafeguardCoordinationDisposition.DUPLICATE,
                    bundle_digest=await self._existing_bundle_digest(
                        action=action,
                        safeguard_receipt=safeguard_receipt,
                    ),
                    lifecycle=None,
                    closure_receipt=None,
                    dispatch_performed=False,
                    reason="idempotent operation already reached terminal state",
                )
            return await self._deny(
                action,
                "idempotency reservation conflicts with a different action",
            )
        if reservation_result.match is ReservationMatch.DUPLICATE_SAME:
            return SafeguardCoordinatedDispatchResult(
                disposition=SafeguardCoordinationDisposition.DUPLICATE,
                bundle_digest=await self._existing_bundle_digest(
                    action=action,
                    safeguard_receipt=safeguard_receipt,
                ),
                lifecycle=None,
                closure_receipt=None,
                dispatch_performed=False,
                reason="idempotency reservation already exists",
            )
        reservation_receipt = reservation_result.transition_receipt
        if reservation_receipt is None:
            return await self._deny(action, "idempotency reservation receipt is unavailable")

        intent = PreEffectAuditIntent.create(
            reservation_receipt=reservation_receipt,
            actor=self._config.actor,
            created_at=max(self._now(), reservation_receipt.recorded_at),
        )
        append_result = await self._audit_intent_store.append_and_readback(intent)
        if append_result.decision is AuditIntentAppendDecision.CONFLICT:
            return await self._deny(action, "pre-effect audit intent conflicts with durable state")
        audit_receipt = append_result.receipt
        if audit_receipt is None:
            return await self._deny(action, "pre-effect audit intent readback is unavailable")

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
            changed_at=max(self._now(), audit_receipt.read_back_at),
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
                self._now(),
                proof_time,
                audit_receipt.read_back_at,
                preparing_fence.state_changed_at,
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
                dispatch_port=_HoldFencedDispatchPort(
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
                    clock=self._now,
                ),
                now=bundle_time,
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
                    now=max(self._now(), preparing_fence.state_changed_at),
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
        return await self._bundle_for_fence(
            action=action,
            safeguard_receipt=safeguard_receipt,
            fence=fence,
        )

    async def _bundle_for_fence(
        self,
        *,
        action: Action,
        safeguard_receipt: SafeguardReceipt,
        fence: TargetDispatchFenceRecord,
    ) -> str | None:
        evidence = await self._evidence_store.read(
            fence.identity.target_digest,
            fence.identity.generation,
        )
        if evidence is None:
            return None
        identity = evidence.identity
        if (
            identity.action_id != str(action.action_id)
            or identity.execution_path != safeguard_receipt.execution_path.value
            or identity.execution_fingerprint != f"sha256:{safeguard_receipt.execution_fingerprint}"
            or identity.source_revision != self.source_revision
        ):
            return None
        return evidence.bundle.bundle_digest

    async def _deny(
        self,
        action: Action,
        reason: str,
    ) -> SafeguardCoordinatedDispatchResult:
        bounded_reason = reason[:512]
        await self._denial_audit_store.append_audit_entry(
            {
                "event_id": str(action.event_id),
                "action_id": str(action.action_id),
                "idempotency_key": action.idempotency_key,
                "actor": self._config.actor,
                "action_kind": "executor.safeguard_lifecycle.denied",
                "audit_phase": "terminal",
                "outcome": "denied",
                "reason": bounded_reason,
                "recorded_at": self._now().isoformat(),
                "execution_authority": False,
                "effect_verified": False,
            }
        )
        return SafeguardCoordinatedDispatchResult(
            disposition=SafeguardCoordinationDisposition.BLOCKED,
            bundle_digest=None,
            lifecycle=None,
            closure_receipt=None,
            dispatch_performed=False,
            reason=bounded_reason,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("safeguard lifecycle clock MUST return an aware datetime")
        return value.astimezone(UTC)


class _HoldFencedDispatchPort:
    """Recheck automation-hold state inside the held lock before invocation.

    The expected release lineage comes from the immutable authorization bound
    when the hold was released for this exact action, so a hold reissued and
    re-released between authorization and provider invocation denies dispatch
    instead of racing it (#640). Deriving lineage from the current hold record
    would make the fence agree with whatever release happens to be newest.
    """

    __slots__ = (
        "_inner",
        "_hold_state_reader",
        "_lineage_reader",
        "_workflow_lineage",
        "_target_ref",
        "_target_digest",
        "_lock_ownership_token",
        "_denial_audit_store",
        "_actor",
        "_action_id",
        "_clock",
    )

    def __init__(
        self,
        *,
        inner: DispatchPort,
        hold_state_reader: AutomationHoldStateReader | None,
        lineage_reader: HoldReleaseAuthorizationReader | None,
        workflow_lineage: tuple[str, str] | None,
        target_ref: str,
        target_digest: str,
        lock_ownership_token: str,
        denial_audit_store: StateStore,
        actor: str,
        action_id: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._inner = inner
        self._hold_state_reader = hold_state_reader
        self._lineage_reader = lineage_reader
        self._workflow_lineage = workflow_lineage
        self._target_ref = target_ref
        self._target_digest = target_digest
        self._lock_ownership_token = lock_ownership_token
        self._denial_audit_store = denial_audit_store
        self._actor = actor
        self._action_id = action_id
        self._clock = clock

    async def dispatch(
        self,
        *,
        evidence_record: SafeguardDispatchEvidenceRecord,
        started_at: datetime,
    ) -> tuple[
        DispatchTransportState,
        AuthoritativeSinkState,
        str | None,
        str | None,
    ]:
        """Fence the target, then delegate exactly once when it stays eligible."""

        check = await self._recheck()
        if check is not None and not check.eligible:
            audit = HoldFenceAuditResult.create(
                check_result=check,
                recorded_at=self._clock(),
            )
            await self._denial_audit_store.append_audit_entry(
                {
                    "action_id": self._action_id,
                    "actor": self._actor,
                    "action_kind": "executor.hold_dispatch_fence.denied",
                    "audit_phase": "pre-dispatch",
                    "outcome": "not_invoked",
                    "target_digest": audit.target_digest,
                    "hold_state": audit.hold_state.value,
                    "rejection_reasons": [reason.value for reason in audit.rejection_reasons],
                    "audit_digest": audit.audit_digest,
                    "recorded_at": audit.recorded_at.isoformat(),
                    "execution_authority": False,
                    "effect_verified": False,
                }
            )
            return (
                DispatchTransportState.FAILED,
                AuthoritativeSinkState.NOT_ACCEPTED,
                None,
                audit.audit_digest,
            )
        return await self._inner.dispatch(
            evidence_record=evidence_record,
            started_at=started_at,
        )

    async def _recheck(self) -> HoldFenceCheckResult | None:
        reader = self._hold_state_reader
        if reader is None:
            return None
        try:
            authorization = await self._authorization()
        except Exception:  # noqa: BLE001 - an unreadable authorization fails closed
            _LOGGER.exception(
                "hold_dispatch_fence_authorization_read_failed",
                extra={"action_id": self._action_id},
            )
            return self._unreadable_check()
        expected_lineage = _released_lineage(authorization)
        authorized_hold_revision = _authorized_hold_revision(authorization)
        if (
            authorization is not None
            and expected_lineage is None
            and (authorized_hold_revision is None)
        ):
            # An authorization exists but cannot be reconstructed: never treat
            # unusable evidence as "no authorization".
            return self._unreadable_check()
        record: Mapping[str, Any] | None
        try:
            record = await reader.read_hold_record(target_ref=self._target_ref)
        except Exception:  # noqa: BLE001 - an unreadable hold fails dispatch closed
            _LOGGER.exception(
                "hold_dispatch_fence_read_failed",
                extra={"action_id": self._action_id},
            )
            return self._unreadable_check()
        if record is None and authorization is None:
            return None
        return recheck_hold_fence(
            target_digest=self._target_digest,
            hold_record=dict(record) if record is not None else None,
            expected_lineage=expected_lineage,
            lock_ownership_token=self._lock_ownership_token,
            checked_at=self._clock(),
            authorized_hold_revision=authorized_hold_revision,
        )

    def _unreadable_check(self) -> HoldFenceCheckResult:
        return recheck_hold_fence(
            target_digest=self._target_digest,
            hold_record=_UNREADABLE_HOLD,
            expected_lineage=None,
            lock_ownership_token=self._lock_ownership_token,
            checked_at=self._clock(),
        )

    async def _authorization(self) -> Mapping[str, Any] | None:
        reader = self._lineage_reader
        lineage = self._workflow_lineage
        if reader is None or lineage is None:
            return None
        process_id, step_id = lineage
        return await reader.read_dispatch_authorization(
            target_ref=self._target_ref,
            process_id=process_id,
            step_id=step_id,
        )


_UNREADABLE_HOLD = object()
_HOLD_SCOPED_AUTHORIZATION = "hold_scoped"
_RELEASED_AUTHORIZATION = "released"


def _authorized_hold_revision(record: object) -> int | None:
    """Return the exact active hold revision one step may dispatch under."""

    if not isinstance(record, Mapping):
        return None
    if record.get("authorization_kind") != _HOLD_SCOPED_AUTHORIZATION:
        return None
    revision = record.get("authorized_hold_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        return None
    return revision


def _released_lineage(record: object) -> HoldLineage | None:
    """Rebuild the release lineage one step was explicitly authorized under.

    The reader owns the target and step binding, so this helper only
    reconstructs the content-addressed lineage the authorization recorded.
    """

    if not isinstance(record, Mapping):
        return None
    if record.get("authorization_kind") != _RELEASED_AUTHORIZATION:
        return None
    receipt_digest = record.get("release_receipt_digest")
    released_hold_revision = record.get("released_hold_revision")
    fencing_generation = record.get("fencing_generation")
    if (
        not isinstance(receipt_digest, str)
        or not isinstance(fencing_generation, int)
        or isinstance(fencing_generation, bool)
        or not isinstance(released_hold_revision, int)
        or isinstance(released_hold_revision, bool)
    ):
        return None
    try:
        return HoldLineage.create(
            release_receipt_digest=receipt_digest,
            released_hold_revision=released_hold_revision,
            fencing_generation=fencing_generation,
        )
    except ValueError:
        return None


__all__ = [
    "ProductionSafeguardStore",
    "SafeguardCoordinatedDispatchResult",
    "SafeguardCoordinationDisposition",
    "SafeguardCoordinationError",
    "SafeguardLifecycleCoordinator",
    "SafeguardLifecycleCoordinatorConfig",
]
