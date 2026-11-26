"""Independent authoritative post-effect observation and completion claims.

Dispatch acceptance is never success. This module reads one observation from
an authority independent of the executor and the provider, re-verifies
identity separation and finality, and only then records a completion claim
that supersedes every earlier claim for the same attempt.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC
from typing import Any

from fdai.core.workflow.recovery_attempt import (
    RecoveryAttemptIdentity,
    RecoveryAttemptRejectionReason,
)
from fdai.core.workflow.recovery_coordinator_models import (
    RecoveryCoordinatorConfig,
    RecoveryDisposition,
    RecoveryEffectClaimOutcome,
    RecoveryEffectObservation,
    RecoveryEffectObservationIntake,
    RecoveryEffectObserver,
)
from fdai.core.workflow.recovery_coordinator_records import (
    ACTOR,
    claim_from_mapping,
    claim_records,
    claim_to_record,
    effect_key,
    int_or_none,
    observation_records,
)
from fdai.core.workflow.recovery_coordinator_support import (
    RecoveryAdmissionGate,
    RecoveryEvidenceJournal,
)
from fdai.core.workflow.recovery_effect_claim import (
    CompletionClaimRejectionReason,
    EffectCompletionClaim,
    supersede_claim,
    verify_effect_evidence,
)
from fdai.core.workflow.workflow_runtime import WorkflowApprovalSnapshot
from fdai.shared.providers.process_runtime import ProcessSnapshot
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger(__name__)


def _unavailable(reason: str) -> RecoveryEffectClaimOutcome:
    """Name a missing or unreadable observation binding as a readiness fact."""

    return RecoveryEffectClaimOutcome(
        claim=None,
        reason=reason,
        disposition=RecoveryDisposition.OBSERVER_UNAVAILABLE,
    )


def _unverified(reason: str) -> RecoveryEffectClaimOutcome:
    """Name why an available observation still did not verify the effect."""

    return RecoveryEffectClaimOutcome(
        claim=None,
        reason=reason,
        disposition=RecoveryDisposition.EFFECT_UNVERIFIED,
    )


class RecoveryEffectCoordinator:
    """Turn one independent observation into one durable completion claim."""

    __slots__ = (
        "_admission",
        "_audit_store",
        "_config",
        "_effect_observations",
        "_effect_observer",
        "_journal",
    )

    def __init__(
        self,
        *,
        admission: RecoveryAdmissionGate,
        audit_store: StateStore,
        config: RecoveryCoordinatorConfig,
        journal: RecoveryEvidenceJournal,
        effect_observer: RecoveryEffectObserver | None = None,
        effect_observations: RecoveryEffectObservationIntake | None = None,
    ) -> None:
        self._admission = admission
        self._audit_store = audit_store
        self._config = config
        self._journal = journal
        self._effect_observer = effect_observer
        self._effect_observations = effect_observations

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

    async def claim_effect(
        self,
        *,
        snapshot: ProcessSnapshot,
        attempt: RecoveryAttemptIdentity,
        hold_revision: int,
        safeguard_bundle_digest: str,
        provider_receipt_digest: str,
        approval: WorkflowApprovalSnapshot,
        compensation_receipt_digests: tuple[str, ...],
    ) -> RecoveryEffectClaimOutcome:
        if self._effect_observer is None:
            return _unavailable(RecoveryAttemptRejectionReason.EFFECT_OBSERVER_UNBOUND)
        observed_at = self._journal.now()
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
            await self._journal.audit(
                snapshot,
                action_kind="workflow.recovery.effect_rejected",
                payload={
                    "attempt_identity_digest": attempt.identity_digest,
                    "rejection_reasons": [str(reason) for reason in reasons],
                    "finalized": observation.finalized,
                },
            )
            return _unverified(CompletionClaimRejectionReason.EVIDENCE_INELIGIBLE.value)
        admission_digest = await self.admission_digest(
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
        return RecoveryEffectClaimOutcome(
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
        key = effect_key(attempt)
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
        current_claim_record = claim_to_record(claim)
        if stored is None:
            record = {
                "process_id": attempt.process_id,
                "attempt_identity_digest": attempt.identity_digest,
                "current_claim_digest": claim.claim_digest,
                "generation": claim.generation,
                "claims": [current_claim_record],
                "observations": [observation_record],
                "execution_authority": False,
                "revision": 1,
            }
            created = await self._audit_store.write_state_with_audit_if_absent(
                key,
                record,
                {
                    "actor": ACTOR,
                    "action_kind": "workflow.recovery.effect_claimed",
                    "attempt_identity_digest": attempt.identity_digest,
                    "claim_digest": claim.claim_digest,
                    "generation": claim.generation,
                    "success": claim.success,
                    "effect_evidence_digest": claim.effect_evidence_digest,
                },
            )
            return claim if created else await self.read_current_claim(attempt)
        revision = int_or_none(stored.get("revision"))
        if revision is None:
            return None
        prior_claims = claim_records(stored)
        superseded: list[Mapping[str, Any]] = []
        for prior in prior_claims:
            restored = claim_from_mapping(prior)
            if restored is None or restored.superseded_by is not None:
                superseded.append(prior)
                continue
            superseded.append(
                claim_to_record(supersede_claim(restored, superseding_digest=claim.claim_digest))
            )
        updated = {
            **dict(stored),
            "current_claim_digest": claim.claim_digest,
            "generation": claim.generation,
            "claims": [*superseded, current_claim_record],
            "observations": [*observation_records(stored), observation_record],
            "revision": revision + 1,
        }
        committed = await self._audit_store.compare_and_set_state_with_audit(
            key,
            updated,
            expected_revision=revision,
            audit_entry={
                "actor": ACTOR,
                "action_kind": "workflow.recovery.effect_claim_superseded",
                "attempt_identity_digest": attempt.identity_digest,
                "claim_digest": claim.claim_digest,
                "generation": claim.generation,
                "success": claim.success,
            },
        )
        if not committed:
            return await self.read_current_claim(attempt)
        return claim

    async def _next_generation(self, attempt: RecoveryAttemptIdentity) -> int:
        stored = await self._audit_store.read_state(effect_key(attempt))
        if stored is None:
            return 1
        generation = int_or_none(stored.get("generation"))
        return 1 if generation is None else generation + 1

    async def read_current_claim(
        self,
        attempt: RecoveryAttemptIdentity,
    ) -> EffectCompletionClaim | None:
        stored = await self._audit_store.read_state(effect_key(attempt))
        if stored is None:
            return None
        current = stored.get("current_claim_digest")
        for raw in claim_records(stored):
            if raw.get("claim_digest") == current:
                return claim_from_mapping(raw)
        return None

    async def admission_digest(
        self,
        *,
        snapshot: ProcessSnapshot,
        approval: WorkflowApprovalSnapshot,
        hold_revision: int,
        compensation_receipt_digests: tuple[str, ...],
    ) -> str | None:
        assessment = await self._admission.assess(
            snapshot=snapshot,
            approval=approval,
            hold_revision=hold_revision,
            compensation_receipt_digests=compensation_receipt_digests,
        )
        if not assessment.eligible or assessment.admission is None:
            return None
        return assessment.admission.receipt_digest


__all__ = ["RecoveryEffectCoordinator"]
