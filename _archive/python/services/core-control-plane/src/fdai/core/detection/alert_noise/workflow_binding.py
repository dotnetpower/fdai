"""Retained input and current-promotion checks for the alert workflow coordinator."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime

from fdai_service_contracts.alert_noise import AlertEvidence, digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan, AlertRollbackBaseline
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.execution_models import (
    RESTORE_ACTION,
    AlertExecutionHeld,
    AlertPlanReader,
)
from fdai.core.detection.alert_noise.workflow_catalog import (
    alert_workflow_for_plan,
    alert_workflow_target,
    workflow_promotion_binding,
)
from fdai.core.detection.alert_noise.workflow_models import (
    ALERT_WORKFLOW_PROMOTION_PURPOSE,
    AlertRequesterReader,
    AlertWorkflowBinding,
    AlertWorkflowResolution,
    WorkflowPromotionReader,
)
from fdai.core.risk_gate.gate import ActionPromotionRegistry
from fdai.core.workflow.workflow_runtime import derive_process_id
from fdai.shared.contracts.models import Mode, OntologyActionType, Workflow
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    assess_decision_evidence_admission,
)
from fdai.shared.providers.state_store import StateStore


class _AlertWorkflowBindingSupport:
    """Read and check invocation bindings using the coordinator's original attributes."""

    _plans: AlertPlanReader
    _requesters: AlertRequesterReader
    _workflows: Mapping[str, Workflow]
    _action_types: Mapping[str, OntologyActionType]
    _registry: ActionPromotionRegistry
    _promotions: WorkflowPromotionReader
    _store: StateStore
    _source_revision: str
    _clock: Callable[[], datetime]

    async def _read_plan(
        self,
        plan_digest: str,
    ) -> tuple[AlertChangePlan, AlertEvidence, Workflow, str, str]:
        if (
            type(plan_digest) is not str
            or re.fullmatch(r"sha256:[a-f0-9]{64}", plan_digest) is None
        ):
            raise AlertExecutionHeld("plan_digest_invalid")
        plan = AlertChangePlan.model_validate(await self._plans.read(plan_digest))
        baseline = AlertRollbackBaseline.model_validate(await self._plans.baseline(plan))
        raw = await self._store.read_state("alert-noise:evidence:" + plan.evidence_digest)
        if raw is None:
            raise AlertExecutionHeld("evidence_not_retained")
        evidence = AlertEvidence.model_validate(raw)
        if (
            digest_record(plan) != plan_digest
            or digest_record(evidence) != plan.evidence_digest
            or evidence.stamp.synthetic
            or evidence.stamp.coverage != "complete"
            or evidence.stamp.tenant_ref != plan.tenant_ref
            or evidence.stamp.scope_ref != plan.scope_ref
            or not evidence.stamp.current_at(plan.created_at)
            or baseline.rule not in evidence.rules
            or (
                baseline.processing_rule is not None
                and baseline.processing_rule not in evidence.processing_rules
            )
        ):
            raise AlertExecutionHeld("workflow_retained_evidence_mismatch")
        workflow = alert_workflow_for_plan(
            plan,
            workflows=self._workflows,
            action_types=self._action_types,
        )
        target = alert_workflow_target(plan, baseline)
        principal = await self._requesters.resolve(requester_ref=plan.requester_ref)
        if not principal:
            raise AlertExecutionHeld("workflow_requester_unavailable")
        return plan, evidence, workflow, target, principal

    def _binding(
        self,
        plan: AlertChangePlan,
        workflow: Workflow,
        target: str,
        principal: str,
        *,
        correlation_id: str,
        mode: Mode,
    ) -> AlertWorkflowBinding:
        return AlertWorkflowBinding(
            process_id=derive_process_id(
                workflow_name=workflow.name,
                target_resource_id=target,
                trigger_ts=plan.created_at,
            ),
            workflow_ref=workflow.name,
            workflow_version=workflow.version,
            workflow_digest=content_digest(workflow.model_dump(mode="json")),
            plan_digest=digest_record(plan),
            evidence_digest=plan.evidence_digest,
            target_resource_id=target,
            requester_ref=plan.requester_ref,
            requester_principal=principal,
            correlation_id=correlation_id,
            trigger_ts=plan.created_at,
            mode=mode,
            source_revision=self._source_revision,
        )

    @staticmethod
    def _decode(raw: Mapping[str, object]) -> AlertWorkflowBinding:
        try:
            binding = AlertWorkflowBinding.model_validate(raw.get("binding"))
        except (TypeError, ValueError):
            # A decoder error must not include the private subject in exception text.
            raise AlertExecutionHeld("workflow_invocation_record_malformed") from None
        if binding.to_record() != raw:
            raise AlertExecutionHeld("workflow_invocation_record_mismatch")
        return binding

    async def promotion_admission(
        self,
        resolution: AlertWorkflowResolution,
    ) -> DecisionEvidenceAdmission | None:
        """Resolve exact promotion evidence for a later synchronous expiry/mode recheck."""
        return await self._promotion_admission(
            resolution.workflow,
            resolution.plan,
            resolution.binding.target_resource_id,
        )

    async def _promotion_admission(
        self,
        workflow: Workflow,
        plan: AlertChangePlan,
        target: str,
    ) -> DecisionEvidenceAdmission | None:
        proof = await self._promotions.read(
            workflow=workflow,
            plan=plan,
            target_resource_id=target,
            now=self._clock(),
        )
        return proof if self._promotion_current(workflow, plan, target, proof) else None

    def _promotion_current(
        self,
        workflow: Workflow,
        plan: AlertChangePlan,
        target: str,
        proof: DecisionEvidenceAdmission | None,
    ) -> bool:
        expected = workflow_promotion_binding(
            workflow=workflow,
            plan=plan,
            target_resource_id=target,
            source_revision=self._source_revision,
        )
        now = self._clock()
        return (
            type(proof) is DecisionEvidenceAdmission
            and proof.execution_authority is False
            and proof.promotion_authority is False
            and not assess_decision_evidence_admission(
                proof,
                expected_evidence_digest=content_digest(expected),
                expected_scope_digest=str(expected["scope_digest"]),
                expected_purpose_id=ALERT_WORKFLOW_PROMOTION_PURPOSE,
                expected_source_revision=self._source_revision,
                evaluated_at=now,
            )
            and now < proof.valid_until
            and all(
                self._registry.mode_of(name) is Mode.ENFORCE
                for name in (plan.action_type, RESTORE_ACTION)
            )
        )

    def require_promotion_current(
        self,
        resolution: AlertWorkflowResolution,
        proof: DecisionEvidenceAdmission | None,
    ) -> None:
        """Recheck expiry and registry demotion after I/O; no new authority is created.

        This is not a sink lease. The ordinary risk and execution boundaries must still
        revalidate revocation and all current authority immediately before any effect.
        """
        if not self._promotion_current(
            resolution.workflow,
            resolution.plan,
            resolution.binding.target_resource_id,
            proof,
        ):
            raise AlertExecutionHeld("workflow_promotion_not_current")

    def require_current(self, resolution: AlertWorkflowResolution) -> None:
        """Reject expired/future forward evidence without turning it into recovery authority."""
        now = self._clock()
        if (
            now.tzinfo is None
            or now.utcoffset() is None
            or not resolution.plan.created_at <= now < resolution.plan.expires_at
            or not resolution.evidence.stamp.current_at(now)
        ):
            raise AlertExecutionHeld("workflow_evidence_not_current")
