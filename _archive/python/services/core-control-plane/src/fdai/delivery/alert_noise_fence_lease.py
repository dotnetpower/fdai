"""Retain and recheck the exact admitted writer-exclusion lease during manual publication."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from fdai_service_contracts.alert_noise import AlertEvidence, digest_record
from fdai_service_contracts.alert_noise_plan import (
    AlertApproval,
    AlertChangePlan,
    AlertDispatchEvidence,
)
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.admission import admission_reasons
from fdai.core.detection.alert_noise.execution import (
    RESTORE_ACTION,
    AlertExecutionHeld,
    AlertRecoveryAdmission,
    alert_publication_digest,
)
from fdai.core.detection.alert_noise.planning import plan_alert_change
from fdai.core.executor.safeguards import full_action_digest
from fdai.delivery.alert_noise_authority import (
    AdmittedAlertAuthority,
    StateStoreAlertAuthorityReader,
    StateStoreAlertRecoveryAuthorityReader,
)
from fdai.delivery.alert_noise_evidence import (
    ALERT_SCOPE_EVIDENCE_PURPOSE,
    AdmittedAlertRecord,
    alert_evidence_binding_digest,
    exact_alert_model,
    read_admitted_alert_record,
)
from fdai.delivery.alert_noise_fence_records import (
    ALERT_WRITER_EXCLUSIVITY_PURPOSE,
    _WriterExclusion,
    alert_writer_binding,
)
from fdai.shared.contracts.models import Action
from fdai.shared.providers.remediation_pr import RemediationPr
from fdai.shared.providers.resource_lock import (
    MAX_LOCK_ASSESSMENT_TTL,
    HeldResourceLock,
    LiveLockOwnershipAssessment,
    require_current_lock_ownership,
    require_evidence_resource_lock,
)

if TYPE_CHECKING:
    from fdai.delivery.alert_noise_fence import StateStoreAlertAuthorityFence


class _AlertAuthorityLease:
    """An inert-after-exit lease retaining exact positive evidence, never a cached grant flag."""

    def __init__(
        self,
        owner: StateStoreAlertAuthorityFence,
        action: Action,
        plan: AlertChangePlan,
        pr: RemediationPr,
        handles: tuple[HeldResourceLock, ...],
    ) -> None:
        self._owner, self._handles, self._action, self._plan, self._pr = (
            owner,
            handles,
            action,
            plan,
            pr,
        )
        self._binding = alert_writer_binding(
            action=action,
            plan=plan,
            pr=pr,
            repository_ref=owner._repository,
            repository_revision=owner._repository_revision,
        )
        self._key = "alert-noise:writer-exclusivity:" + full_action_digest(action)
        self._proofs: tuple[AdmittedAlertRecord, ...] = ()
        self._assessments: tuple[LiveLockOwnershipAssessment, ...] = ()
        self._acquisitions = tuple(held.acquisition_receipt for held in handles)
        self._active = True
        self._authority: AdmittedAlertAuthority | None = None

    async def _initialize(self) -> None:
        owner = self._owner
        proof = await read_admitted_alert_record(
            owner._store,
            owner._admissions,
            self._key,
            ALERT_WRITER_EXCLUSIVITY_PURPOSE,
            owner._scope,
            owner._revision,
            owner._clock(),
        )
        if proof is None:
            raise AlertExecutionHeld("alert_exclusive_writer_unverified")
        self._writer_proof, self._writer = proof, exact_alert_model(_WriterExclusion, proof.payload)
        self._ceiling = min(self._writer.exclusive_until, proof.admission.valid_until)
        self._require_window(owner._clock())
        await owner._require_anchor(proof)

    def _require_window(self, now: datetime) -> None:
        writer = self._writer
        budget = (
            self._plan.max_recovery_seconds
            if self._action.action_type == RESTORE_ACTION
            else self._plan.max_execution_seconds
        )
        if (
            content_digest(writer.binding) != content_digest(self._binding)
            or writer.writer_ref != self._owner._writer
            or writer.released_at is not None
            or not writer.exclusive_from <= now < self._ceiling
            or not timedelta(0)
            < writer.exclusive_until - writer.exclusive_from
            <= timedelta(days=1)
            or writer.release_not_before < writer.exclusive_until
            or writer.release_not_before
            > writer.exclusive_until + timedelta(seconds=self._plan.max_recovery_seconds)
            or now + timedelta(seconds=budget) > writer.exclusive_until
        ):
            raise AlertExecutionHeld("alert_exclusive_window_invalid")

    async def require_current(
        self,
        *,
        action: Action,
        plan: AlertChangePlan,
        pr: RemediationPr,
        evidence: AlertDispatchEvidence | AlertRecoveryAdmission,
        approvals: tuple[AlertApproval, ...],
        now: datetime,
    ) -> None:
        """Re-read actual evidence, Var, promotion, dispatch and exclusion before each boundary."""
        self._proofs = ()
        owner = self._owner
        try:
            async with asyncio.timeout(15):
                owner._require_inputs(action, plan, pr)
                if (
                    not self._active
                    or alert_writer_binding(
                        action=action,
                        plan=plan,
                        pr=pr,
                        repository_ref=owner._repository,
                        repository_revision=owner._repository_revision,
                    )
                    != self._binding
                ):
                    raise AlertExecutionHeld("alert_fence_binding_changed")
                self._require_window(max(now, owner._clock()))
                current_writer = await read_admitted_alert_record(
                    owner._store,
                    owner._admissions,
                    self._key,
                    ALERT_WRITER_EXCLUSIVITY_PURPOSE,
                    owner._scope,
                    owner._revision,
                    owner._clock(),
                )
                if current_writer is None or current_writer != self._writer_proof:
                    raise AlertExecutionHeld("alert_exclusive_writer_changed")
                proofs = [current_writer]
                source_ref = evaluation_ref = None
                if isinstance(evidence, AlertRecoveryAdmission):
                    if owner._recovery is None or approvals:
                        raise AlertExecutionHeld("alert_recovery_authority_missing")
                    authority = await owner._recovery.read(action=action, plan=plan)
                    reader: (
                        StateStoreAlertAuthorityReader | StateStoreAlertRecoveryAuthorityReader
                    ) = owner._recovery
                else:
                    if owner._authority is None:
                        raise AlertExecutionHeld("alert_authority_missing")
                    source, evaluation = await self._forward_evidence(plan)
                    proofs.append(source)
                    source_ref = source.receipt_digest
                    if evaluation is not None:
                        proofs.append(evaluation)
                        evaluation_ref = evaluation.receipt_digest
                    authority, reader = await owner._authority.read(plan), owner._authority
                if (
                    authority is None
                    or authority.dispatch != evidence
                    or evidence.dry_run_digest != alert_publication_digest(plan, pr)
                    or (
                        isinstance(evidence, AlertDispatchEvidence)
                        and (
                            authority.approvals != approvals
                            or evidence.writer_fence_ref != self._writer.mechanism_ref
                        )
                    )
                ):
                    raise AlertExecutionHeld("alert_fence_authority_changed")
                dispatch = await reader.dispatch_proof(
                    action=action,
                    plan=plan,
                    pr=pr,
                    authority=authority,
                    evidence_receipt_digest=source_ref,
                    evaluation_admission_digest=evaluation_ref,
                )
                if (
                    dispatch is None
                    or dispatch.receipt_digest != self._writer.dispatch_receipt_digest
                ):
                    raise AlertExecutionHeld("alert_dispatch_proof_missing")
                proofs.extend((authority.proof, dispatch))
                for proof in proofs:
                    await owner._require_anchor(proof)
                self._assessments = tuple([await held.assess_ownership() for held in self._handles])
                for proof in proofs:
                    await proof.require_unchanged(owner._store)
                self._authority, self._proofs = authority, tuple(proofs)
                self._ceiling = min(
                    self._ceiling, *(proof.admission.valid_until for proof in proofs)
                )
                self.require_active(now=max(now, owner._clock()))
        except Exception:
            self._proofs = ()
            raise AlertExecutionHeld("alert_fence_current_check_failed") from None

    async def _forward_evidence(
        self, plan: AlertChangePlan
    ) -> tuple[AdmittedAlertRecord, AdmittedAlertRecord | None]:
        owner = self._owner
        source = await read_admitted_alert_record(
            owner._store,
            owner._admissions,
            "alert-noise:scope-evidence:" + plan.scope_ref,
            ALERT_SCOPE_EVIDENCE_PURPOSE,
            owner._scope,
            owner._revision,
            owner._clock(),
        )
        if source is None or set(source.payload) != {"base_digest", "evidence"}:
            raise AlertExecutionHeld("alert_fence_evidence_missing")
        native = exact_alert_model(AlertEvidence, source.payload["evidence"])
        if (
            digest_record(native) != plan.evidence_digest
            or native.stamp.synthetic
            or native.history_coverage != "complete"
            or native.delivery_coverage != "complete"
            or native.stamp.recorded_at > source.admission.verified_at
            or not native.stamp.current_at(owner._clock())
            or digest_record(owner._policy) != plan.policy_digest
            or native.stamp.revision
            != alert_evidence_binding_digest(
                base_digest=source.payload["base_digest"], evidence=native
            )
        ):
            raise AlertExecutionHeld("alert_fence_evidence_mismatch")
        self._ceiling = min(self._ceiling, native.stamp.valid_until)
        comparison = None
        evaluation = None
        if plan.treatment.kind == "evaluation":
            if owner._evaluations is None:
                raise AlertExecutionHeld("alert_fence_evaluation_missing")
            reviewed = await owner._evaluations.read_admitted(
                evidence=native, treatment=plan.treatment, now=owner._clock()
            )
            if reviewed is None or digest_record(reviewed[0]) != plan.evaluation_receipt_digest:
                raise AlertExecutionHeld("alert_fence_evaluation_mismatch")
            comparison, evaluation = reviewed
            self._ceiling = min(self._ceiling, comparison.expires_at)
        rebuilt = plan_alert_change(
            native,
            plan.treatment,
            policy=owner._policy,
            requester_ref=plan.requester_ref,
            now=plan.created_at,
            evaluation_receipt=comparison,
        )
        if rebuilt != plan:
            raise AlertExecutionHeld("alert_fence_plan_mismatch")
        return source, evaluation

    def require_active(self, *, now: datetime) -> None:
        """Synchronously check retained windows and <=5-second exact live lock assessments."""
        owner, authority = self._owner, self._authority
        now = max(now, owner._clock())
        if (
            not self._active
            or not self._proofs
            or authority is None
            or len(self._assessments) != len(self._handles)
        ):
            raise AlertExecutionHeld("alert_exclusive_lease_inactive")
        if self._binding != alert_writer_binding(
            action=self._action,
            plan=self._plan,
            pr=self._pr,
            repository_ref=owner._repository,
            repository_revision=owner._repository_revision,
        ):
            raise AlertExecutionHeld("alert_fence_binding_changed")
        require_evidence_resource_lock(owner._lock, production=owner._production)
        self._require_window(now)
        for proof in self._proofs:
            proof.require_current(now=now)
        dispatch = authority.dispatch
        reader = (
            owner._recovery if isinstance(dispatch, AlertRecoveryAdmission) else owner._authority
        )
        if reader is None:
            raise AlertExecutionHeld("alert_authority_missing")
        reader.require_retained_current(authority, self._plan)
        budget = (
            self._plan.max_recovery_seconds
            if isinstance(dispatch, AlertRecoveryAdmission)
            else self._plan.max_execution_seconds
            + self._plan.max_observation_seconds
            + self._plan.max_recovery_seconds
        )
        if now + timedelta(seconds=budget) > authority.approval_valid_until:
            raise AlertExecutionHeld("alert_var_approval_expired")
        if isinstance(dispatch, AlertDispatchEvidence):
            if admission_reasons(
                self._plan, approvals=authority.approvals, evidence=dispatch, now=now
            ):
                raise AlertExecutionHeld("alert_fence_authority_expired")
        elif (
            not dispatch.evaluated_at <= now < dispatch.valid_until
            or now + timedelta(seconds=self._plan.max_recovery_seconds)
            > dispatch.authorization_until
        ):
            raise AlertExecutionHeld("alert_fence_recovery_expired")
        for held, assessment, acquired in zip(
            self._handles, self._assessments, self._acquisitions, strict=True
        ):
            held.require_active()
            current = require_current_lock_ownership(replace(assessment), observed_at=now)
            receipt, trust = held.acquisition_receipt, owner._trust
            if (
                receipt != acquired
                or current.acquisition_receipt != receipt
                or current.valid_until - current.evaluated_at > MAX_LOCK_ASSESSMENT_TTL
                or (receipt.provider_id, receipt.provider_version)
                != (trust.provider_id, trust.provider_version)
                or (current.verifier_id, current.verifier_version, current.trust_anchor_id)
                != (trust.verifier_id, trust.verifier_version, trust.trust_anchor_id)
                or receipt.trust_anchor_id != trust.trust_anchor_id
            ):
                raise AlertExecutionHeld("alert_exclusive_lock_proof_mismatch")
