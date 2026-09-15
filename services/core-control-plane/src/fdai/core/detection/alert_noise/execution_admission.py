"""Exact retained-plan and current-authority checks for the alert execution facade."""

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
    AlertRollbackBaseline,
)

from fdai.core.detection.alert_noise.admission import admission_reasons
from fdai.core.detection.alert_noise.execution_models import (
    RESTORE_ACTION,
    AlertAuthorityLease,
    AlertExecutionHeld,
    AlertPlanReader,
    AlertPublicationCheck,
    AlertRecoveryAdmission,
    AlertRecoveryAuthorityReader,
    alert_execution_key,
    alert_publication_digest,
)
from fdai.core.executor.safeguards import full_action_digest
from fdai.shared.contracts.models import (
    Action,
    BlastRadiusScope,
    OntologyTypeRef,
    Operation,
    RollbackKind,
    Rule,
)
from fdai.shared.providers.alert_noise import AlertAuthorityReader
from fdai.shared.providers.remediation_pr import RemediationPr


class _AlertExecutionAdmission:
    """Keep admission helpers on the facade's original instance and injected attributes."""

    _plans: AlertPlanReader
    _registered: Mapping[str, OntologyTypeRef]
    _clock: Callable[[], datetime]
    _recovery: AlertRecoveryAuthorityReader | None
    _authority: AlertAuthorityReader | None

    async def _load(self, action: Action, rule: Rule) -> AlertChangePlan:
        raw = action.params.get("plan_digest")
        if (
            set(action.params) != {"plan_digest"}
            or type(raw) is not str
            or re.fullmatch(r"[a-f0-9]{64}", raw) is None
        ):
            raise AlertExecutionHeld("plan_digest_invalid")
        digest = "sha256:" + raw
        plan = AlertChangePlan.model_validate(await self._plans.read(digest))
        baseline = AlertRollbackBaseline.model_validate(await self._plans.baseline(plan))
        target = (
            baseline.processing_rule.ref
            if baseline.processing_rule is not None
            else baseline.rule.ref
        )
        if (
            digest_record(plan) != digest
            or digest_record(baseline) != plan.rollback_ref
            or baseline.rule.ref != plan.treatment.target_ref
            or (baseline.processing_rule is not None) != (plan.treatment.kind == "suppression")
            or (
                baseline.processing_rule is not None
                and baseline.processing_rule.ref != plan.treatment.processing_rule_ref
            )
            or (
                baseline.processing_rule.revision
                if baseline.processing_rule
                else baseline.rule.revision
            )
            != plan.target_revision
            or action.target_resource_ref != target
            or target not in plan.lock_refs
            or action.action_type not in {plan.action_type, RESTORE_ACTION}
            or action.action_type_ref is None
            or action.action_type_ref != self._registered.get(action.action_type)
            or action.workflow_action is None
            or not action.executor_identity_ref
            or action.idempotency_key != alert_execution_key(action.action_type, digest)
            or action.operation is not Operation.UPDATE
            or action.rollback_ref.kind is not RollbackKind.PR_REVERT
            or action.rollback_ref.reference != plan.rollback_ref
            or action.blast_radius.count != 1
            or action.blast_radius.scope
            not in {BlastRadiusScope.RESOURCE, BlastRadiusScope.RESOURCE_GROUP}
            or rule.id not in action.citing_rules
            or rule.remediates not in {plan.action_type, action.action_type}
            or (plan.treatment.kind == "evaluation" and not plan.evaluation_receipt_digest)
        ):
            raise AlertExecutionHeld("action_plan_binding_mismatch")
        return plan

    async def _authorize(
        self,
        action: Action,
        plan: AlertChangePlan,
        pr: RemediationPr,
        lease: AlertAuthorityLease,
    ) -> AlertPublicationCheck:
        approvals: tuple[AlertApproval, ...] = ()
        evidence: AlertDispatchEvidence | AlertRecoveryAdmission
        async with asyncio.timeout(15):
            if action.action_type == RESTORE_ACTION:
                if self._recovery is None:
                    raise AlertExecutionHeld("recovery_authority_missing")
                receipt = await self._recovery.admission(action=action, plan=plan)
                if receipt is None:
                    raise AlertExecutionHeld("recovery_authority_missing")
                evidence = AlertRecoveryAdmission.model_validate(receipt)
            else:
                if self._authority is None:
                    raise AlertExecutionHeld("authority_reader_missing")
                evidence = AlertDispatchEvidence.model_validate(
                    await self._authority.dispatch_evidence(plan)
                )
                approvals = tuple(
                    AlertApproval.model_validate(item)
                    for item in await self._authority.approvals(plan)
                )

            def check(at: datetime) -> None:
                now = self._clock()
                if (
                    now.tzinfo is None
                    or now.utcoffset() is None
                    or at.tzinfo is None
                    or at.utcoffset() is None
                ):
                    raise AlertExecutionHeld("clock_invalid")
                now = max(now, at)
                if isinstance(evidence, AlertRecoveryAdmission):
                    if (
                        evidence.action_digest != full_action_digest(action)
                        or evidence.plan_digest != digest_record(plan)
                        or evidence.rollback_ref != plan.rollback_ref
                        or not evidence.evaluated_at <= now < evidence.valid_until
                        or now + timedelta(seconds=plan.max_recovery_seconds)
                        > evidence.authorization_until
                    ):
                        raise AlertExecutionHeld("recovery_admission_mismatch")
                elif admission_reasons(plan, approvals=approvals, evidence=evidence, now=now):
                    raise AlertExecutionHeld("forward_admission_held")
                if (
                    evidence.executor_ref != action.executor_identity_ref
                    or evidence.dry_run_digest != alert_publication_digest(plan, pr)
                ):
                    raise AlertExecutionHeld("authority_patch_binding_mismatch")

            check(self._clock())
            await lease.require_current(
                action=action,
                plan=plan,
                pr=pr,
                evidence=evidence,
                approvals=approvals,
                now=self._clock(),
            )
            check(self._clock())

            def boundary_check(at: datetime) -> None:
                check(at)
                lease.require_active(now=max(at, self._clock()))

            boundary_check(self._clock())
            return boundary_check
