"""Resolve admitted alert authority against current Var journals and promotion state.

The private OID-to-pseudonym mapping establishes identity only. Neither directory membership,
environment roles, a stored boolean, nor these readers can create human or executor authority.
The shared independent DE producer must verify every current right and referenced safeguard.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

from fdai_service_contracts.alert_noise import digest_record
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
from fdai.core.executor.safeguards import full_action_digest
from fdai.core.risk_gate.gate import ActionModeRecord
from fdai.core.workflow.recovery_attempt import is_recovery_attempt_step_id
from fdai.delivery.alert_noise_authority_quorum import _identity_digest, _quorum
from fdai.delivery.alert_noise_authority_records import (
    AdmittedAlertAuthority as AdmittedAlertAuthority,
)
from fdai.delivery.alert_noise_authority_records import (
    _ApprovalContext,
    _ForwardRecord,
    _RecoveryRecord,
)
from fdai.delivery.alert_noise_authority_records import (
    alert_dispatch_binding as alert_dispatch_binding,
)
from fdai.delivery.alert_noise_evidence import (
    AdmittedAlertRecord,
    alert_scope_digest,
    exact_alert_model,
    read_admitted_alert_record,
)
from fdai.delivery.persistence.state_store_action_promotion import StateStoreActionPromotionRegistry
from fdai.delivery.persistence.workflow_approval import StateStoreWorkflowApprovalProvider
from fdai.shared.contracts.models import Action, Mode
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.remediation_pr import RemediationPr
from fdai.shared.providers.state_store import StateStore

ALERT_AUTHORITY_PURPOSE = "alert-noise-authority"
ALERT_RECOVERY_PURPOSE = "alert-noise-recovery"
ALERT_DISPATCH_PURPOSE = "alert-noise-dispatch"
ALERT_RECOVERY_DISPATCH_PURPOSE = "alert-noise-recovery-dispatch"


class _AuthorityReader:
    """Shared read-only admission, scoped identity, Var and promotion checks."""

    def __init__(
        self,
        *,
        store: StateStore,
        admissions: DecisionEvidenceAdmissionProvider | None,
        promotion_registry: StateStoreActionPromotionRegistry | None,
        principal_refs: Mapping[str, str],
        scope_ref: str,
        tenant_ref: str,
        source_revision: str,
        clock: Callable[[], datetime],
    ) -> None:
        """Bind Core-owned records, current scoped private identities, and the verified registry."""
        self._scope = alert_scope_digest(tenant_ref=tenant_ref, scope_ref=scope_ref)
        if re.fullmatch(r"commit:[a-f0-9]{40}(?:[a-f0-9]{24})?", source_revision) is None:
            raise ValueError("alert authority source revision MUST be an explicit commit")
        self._store, self._admissions, self._promotions = store, admissions, promotion_registry
        self._principal_refs, self._revision, self._clock = principal_refs, source_revision, clock
        self._var = StateStoreWorkflowApprovalProvider(store=store)

    async def _read(
        self, plan: AlertChangePlan, action: Action | None = None
    ) -> AdmittedAlertAuthority | None:
        try:
            async with asyncio.timeout(15):
                plan = AlertChangePlan.model_validate(plan)
                now = self._clock()
                if (
                    alert_scope_digest(tenant_ref=plan.tenant_ref, scope_ref=plan.scope_ref)
                    != self._scope
                    or now.tzinfo is None
                    or now.utcoffset() is None
                ):
                    raise AlertExecutionHeld("alert_authority_scope_mismatch")
                restoring = action is not None
                key = (
                    "alert-noise:recovery-authority:" + full_action_digest(action)
                    if action is not None
                    else "alert-noise:authority:" + digest_record(plan)
                )
                proof = await read_admitted_alert_record(
                    self._store,
                    self._admissions,
                    key,
                    ALERT_RECOVERY_PURPOSE if restoring else ALERT_AUTHORITY_PURPOSE,
                    self._scope,
                    self._revision,
                    now,
                )
                if proof is None:
                    return None
                context: _ApprovalContext
                dispatch: AlertDispatchEvidence | AlertRecoveryAdmission
                if action is None:
                    forward = exact_alert_model(_ForwardRecord, proof.payload)
                    context, dispatch = forward, forward.dispatch
                    if context.approval_step_id != "approve_plan" or admission_reasons(
                        plan, approvals=forward.approvals, evidence=dispatch, now=now
                    ):
                        raise AlertExecutionHeld("alert_authority_forward_held")
                    promotion_digest = dispatch.promotion_digest
                    end = now + timedelta(
                        seconds=plan.max_execution_seconds
                        + plan.max_observation_seconds
                        + plan.max_recovery_seconds
                    )
                    if plan.treatment.ends_at is not None:
                        end = max(
                            end,
                            plan.treatment.ends_at + timedelta(seconds=plan.max_recovery_seconds),
                        )
                    floor = plan.created_at
                else:
                    action = Action.model_validate(action.model_dump(mode="python"))
                    recovery = exact_alert_model(_RecoveryRecord, proof.payload)
                    context, dispatch, promotion_digest = (
                        recovery,
                        recovery.admission,
                        recovery.promotion_digest,
                    )
                    lineage = action.workflow_action
                    end, floor = (
                        now + timedelta(seconds=plan.max_recovery_seconds),
                        action.created_at,
                    )
                    if (
                        action.action_type != RESTORE_ACTION
                        or action.mode is not Mode.ENFORCE
                        or lineage is None
                        or not is_recovery_attempt_step_id(context.approval_step_id)
                        or (context.process_id, context.attempt)
                        != (lineage.process_id, lineage.attempt)
                        or dispatch.action_digest != full_action_digest(action)
                        or dispatch.plan_digest != digest_record(plan)
                        or dispatch.rollback_ref != plan.rollback_ref
                        or dispatch.executor_ref != action.executor_identity_ref
                        or not floor <= dispatch.evaluated_at <= now < dispatch.valid_until
                        or end > dispatch.authorization_until
                    ):
                        raise AlertExecutionHeld("alert_recovery_binding_mismatch")
                    previous = await self._store.read_state(
                        "alert-noise:authority:" + digest_record(plan)
                    )
                    if previous is not None:
                        old = exact_alert_model(_ForwardRecord, previous.get("payload"))
                        if {item.receipt_ref for item in old.approvals}.intersection(
                            item.receipt_ref for item in recovery.approvals
                        ):
                            raise AlertExecutionHeld("alert_recovery_forward_approval_reused")
                if (
                    context.plan_digest != digest_record(plan)
                    or dispatch.evaluated_at > proof.admission.verified_at
                    or any(
                        item.decided_at > proof.admission.verified_at for item in context.approvals
                    )
                ):
                    raise AlertExecutionHeld("alert_authority_plan_mismatch")
                promotion = await self._promotion(
                    RESTORE_ACTION if restoring else plan.action_type, promotion_digest, now
                )
                snapshot_digest, approval_until = await self._quorum(
                    context, plan, dispatch.executor_ref, floor, end
                )
                identities = self._identity_digest(plan, dispatch.executor_ref, context.approvals)
                if not proof.matches(await self._store.read_state(key)):
                    raise AlertExecutionHeld("alert_authority_changed")
                at = self._clock()
                if (
                    at < now
                    or not dispatch.evaluated_at <= at < dispatch.valid_until
                    or at + (end - now) > approval_until
                ):
                    raise AlertExecutionHeld("alert_authority_expired")
                proof.require_current(now=at)
                if isinstance(dispatch, AlertDispatchEvidence):
                    if admission_reasons(
                        plan, approvals=context.approvals, evidence=dispatch, now=at
                    ):
                        raise AlertExecutionHeld("alert_authority_forward_held")
                elif (
                    at + timedelta(seconds=plan.max_recovery_seconds) > dispatch.authorization_until
                ):
                    raise AlertExecutionHeld("alert_recovery_expired")
                resolved = AdmittedAlertAuthority(
                    proof,
                    context.approvals,
                    dispatch,
                    context.process_id,
                    context.approval_step_id,
                    context.attempt,
                    snapshot_digest,
                    promotion,
                    approval_until,
                    identities,
                )
                self.require_retained_current(resolved, plan)
                return resolved
        except AlertExecutionHeld:
            raise
        except Exception:
            raise AlertExecutionHeld("alert_authority_unavailable") from None

    async def _promotion(
        self, action_type: str, digest: str | None, now: datetime
    ) -> ActionModeRecord:
        registry = self._promotions
        if registry is None:
            raise AlertExecutionHeld("alert_promotion_unavailable")
        await registry.refresh(action_type)
        record = registry.record(action_type)
        if (
            registry.mode_of(action_type) is not Mode.ENFORCE
            or record is None
            or record.mode is not Mode.ENFORCE
            or record.action_type != action_type
            or record.promotion_evidence_digest is None
            or "sha256:" + record.promotion_evidence_digest != digest
            or record.fdai_revision != self._revision.removeprefix("commit:")
            or record.promoted_at is None
            or record.promoted_at > now
            or (record.demoted_at is not None and record.demoted_at >= record.promoted_at)
        ):
            raise AlertExecutionHeld("alert_promotion_not_current")
        return record

    async def _quorum(
        self,
        context: _ApprovalContext,
        plan: AlertChangePlan,
        executor: str,
        floor: datetime,
        end: datetime,
    ) -> tuple[str, datetime]:
        """Match exact opaque decisions to the real Var journal, never normalized aliases."""
        return await _quorum(self, context, plan, executor, floor, end)

    def _identity_digest(
        self, plan: AlertChangePlan, executor: str, approvals: tuple[AlertApproval, ...]
    ) -> str:
        return _identity_digest(self, plan, executor, approvals)

    def require_retained_current(
        self, authority: AdmittedAlertAuthority, plan: AlertChangePlan
    ) -> None:
        """Veto identity rebinding or observed demotion; this is not a fresh store admission."""
        if (
            self._identity_digest(plan, authority.dispatch.executor_ref, authority.approvals)
            != authority.identity_binding_digest
            or self._promotions is None
            or self._promotions.record(authority.promotion.action_type) != authority.promotion
        ):
            raise AlertExecutionHeld("alert_authority_binding_changed")

    async def dispatch_proof(
        self,
        *,
        action: Action,
        plan: AlertChangePlan,
        pr: RemediationPr,
        authority: AdmittedAlertAuthority,
        evidence_receipt_digest: str | None,
        evaluation_admission_digest: str | None,
    ) -> AdmittedAlertRecord | None:
        """Resolve separate full-action dispatch admission; authority flags cannot replace it."""
        self.require_retained_current(authority, plan)
        lineage = action.workflow_action
        restoring = isinstance(authority.dispatch, AlertRecoveryAdmission)
        if (
            lineage is None
            or lineage.process_id != authority.process_id
            or lineage.attempt != authority.attempt
            or alert_scope_digest(tenant_ref=plan.tenant_ref, scope_ref=plan.scope_ref)
            != self._scope
            or authority.dispatch.plan_digest != digest_record(plan)
            or action.executor_identity_ref != authority.dispatch.executor_ref
            or authority.dispatch.dry_run_digest != alert_publication_digest(plan, pr)
            or action.action_type != (RESTORE_ACTION if restoring else plan.action_type)
            or authority.promotion.action_type != action.action_type
            or action.action_type_ref is None
            or authority.promotion.action_type_version != action.action_type_ref.version
            or (
                not restoring
                and (
                    evidence_receipt_digest is None
                    or (plan.treatment.kind == "evaluation" and evaluation_admission_digest is None)
                )
            )
            or (
                restoring
                and (evidence_receipt_digest is not None or evaluation_admission_digest is not None)
            )
        ):
            raise AlertExecutionHeld("alert_dispatch_lineage_mismatch")
        binding = alert_dispatch_binding(
            action=action,
            plan=plan,
            pr=pr,
            authority=authority,
            evidence_receipt_digest=evidence_receipt_digest,
            evaluation_admission_digest=evaluation_admission_digest,
        )
        record = await read_admitted_alert_record(
            self._store,
            self._admissions,
            ("alert-noise:recovery-dispatch:" if restoring else "alert-noise:dispatch:")
            + full_action_digest(action),
            ALERT_RECOVERY_DISPATCH_PURPOSE if restoring else ALERT_DISPATCH_PURPOSE,
            self._scope,
            self._revision,
            self._clock(),
        )
        if record is not None:
            if content_digest(record.payload) != content_digest(binding):
                raise AlertExecutionHeld("alert_dispatch_proof_mismatch")
            record.require_current(now=self._clock())
            authority.proof.require_current(now=self._clock())
            self.require_retained_current(authority, plan)
        return record


class StateStoreAlertAuthorityReader(_AuthorityReader):
    """Implement forward authority using exact alert-noise:authority:<plan digest> records.

    Payload is exactly {plan_digest, approvals, dispatch, process_id, approval_step_id,
    attempt}. Store, admissions, verified persisted promotion registry, scoped private
    principal_refs, tenant_ref, scope_ref, source_revision and clock are explicit bindings.
    Missing authority yields no approvals and makes dispatch_evidence raise an audited-port hold.
    """

    async def read(self, plan: AlertChangePlan) -> AdmittedAlertAuthority | None:
        """Resolve a current independently admitted forward record and exact Var decisions."""
        return await self._read(plan)

    async def approvals(self, plan: AlertChangePlan) -> tuple[AlertApproval, ...]:
        """Return only current journal-matched decisions, or no decisions when unbound."""
        record = await self.read(plan)
        return record.approvals if record is not None else ()

    async def dispatch_evidence(self, plan: AlertChangePlan) -> AlertDispatchEvidence:
        """Return independently admitted forward evidence; absence grants no permission."""
        record = await self.read(plan)
        if record is None or not isinstance(record.dispatch, AlertDispatchEvidence):
            raise AlertExecutionHeld("alert_authority_missing")
        return record.dispatch


class StateStoreAlertRecoveryAuthorityReader(_AuthorityReader):
    """Resolve separate alert-noise:recovery-authority:<full Action digest> evidence.

    Payload is exactly {plan_digest, approvals, admission, promotion_digest, process_id,
    approval_step_id, attempt}. Var approval uses the canonical recover approval step in the
    same Process/attempt, independently bound to the full Action; its compensation step is not
    renamed. Never use approve_plan or a forward receipt. Recovery owns independent DE and
    promotion; expired forward plans do not renew, authorize, or prevent approved recovery.
    """

    async def read(self, *, action: Action, plan: AlertChangePlan) -> AdmittedAlertAuthority | None:
        """Resolve only this full recovery Action and its separate live approval attempt."""
        return await self._read(plan, action)

    async def admission(
        self, *, action: Action, plan: AlertChangePlan
    ) -> AlertRecoveryAdmission | None:
        """Return typed recovery admission or explicit absence, never forward authority."""
        record = await self.read(action=action, plan=plan)
        if record is None:
            return None
        if not isinstance(record.dispatch, AlertRecoveryAdmission):
            raise AlertExecutionHeld("alert_recovery_binding_mismatch")
        return record.dispatch
