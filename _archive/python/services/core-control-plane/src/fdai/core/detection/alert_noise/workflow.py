"""Bind retained alert proposals to the canonical Workflow and Process runtime.

This module records planning evidence, not another workflow state machine. Only the
injected WorkflowOrchestrator advances the Process. Its production composition must
use the same ProcessRuntimeStore, durable Var approval provider, admission provider,
typed dispatcher and independent outcome verifier as the ordinary runtime.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from datetime import datetime

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.execution_models import AlertExecutionHeld, AlertPlanReader
from fdai.core.detection.alert_noise.workflow_catalog import (
    alert_workflow_for_plan as alert_workflow_for_plan,
)
from fdai.core.detection.alert_noise.workflow_catalog import (
    alert_workflow_target as alert_workflow_target,
)
from fdai.core.detection.alert_noise.workflow_catalog import (
    workflow_binding_key as workflow_binding_key,
)
from fdai.core.detection.alert_noise.workflow_catalog import (
    workflow_promotion_binding as workflow_promotion_binding,
)
from fdai.core.detection.alert_noise.workflow_decision_case import (
    _proposal_payload as _proposal_payload,
)
from fdai.core.detection.alert_noise.workflow_decision_case import (
    alert_decision_case as alert_decision_case,
)
from fdai.core.detection.alert_noise.workflow_models import (
    _PLAN_PARAMS as _PLAN_PARAMS,
)
from fdai.core.detection.alert_noise.workflow_models import (
    ALERT_WORKFLOW_PROMOTION_PURPOSE as ALERT_WORKFLOW_PROMOTION_PURPOSE,
)
from fdai.core.detection.alert_noise.workflow_models import (
    ALERT_WORKFLOWS as ALERT_WORKFLOWS,
)
from fdai.core.detection.alert_noise.workflow_models import (
    PLAN_CONTEXT_KEY as PLAN_CONTEXT_KEY,
)
from fdai.core.detection.alert_noise.workflow_models import (
    AlertActionBinder as AlertActionBinder,
)
from fdai.core.detection.alert_noise.workflow_models import (
    AlertRequesterReader as AlertRequesterReader,
)
from fdai.core.detection.alert_noise.workflow_models import (
    AlertWorkflowBinding as AlertWorkflowBinding,
)
from fdai.core.detection.alert_noise.workflow_models import (
    AlertWorkflowResolution as AlertWorkflowResolution,
)
from fdai.core.detection.alert_noise.workflow_models import (
    AlertWorkflowResult as AlertWorkflowResult,
)
from fdai.core.detection.alert_noise.workflow_models import (
    WorkflowPromotionReader as WorkflowPromotionReader,
)
from fdai.core.detection.alert_noise.workflow_process import _AlertWorkflowProcessSupport
from fdai.core.risk_gate.gate import ActionPromotionRegistry
from fdai.core.workflow.orchestrator import WorkflowOrchestrator
from fdai.core.workflow.workflow_resume import build_resume_payload
from fdai.shared.contracts.models import Mode, OntologyActionType, Workflow
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai.shared.providers.process_runtime import ProcessRuntimeStore, ProcessStatus
from fdai.shared.providers.state_store import StateStore


class AlertWorkflowCoordinator(_AlertWorkflowProcessSupport):
    """Record exact input lineage and delegate create/run/resume to canonical APIs.

    All stores and the orchestrator are parent-owned runtime bindings. No database,
    in-memory runtime, dispatcher, approval or executor is constructed here. A shadow
    Process remains shadow on replay; losing promotion holds an enforce resume rather
    than rewriting its original mode or simulating completion of a dispatched action.
    """

    def __init__(
        self,
        *,
        plans: AlertPlanReader,
        requesters: AlertRequesterReader,
        workflows: Mapping[str, Workflow],
        action_types: Mapping[str, OntologyActionType],
        registry: ActionPromotionRegistry,
        promotions: WorkflowPromotionReader,
        orchestrator: WorkflowOrchestrator,
        process_store: ProcessRuntimeStore,
        store: StateStore,
        source_revision: str,
        clock: Callable[[], datetime],
    ) -> None:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}", source_revision) is None:
            raise ValueError("alert workflow source revision MUST be explicit")
        self._plans, self._requesters = plans, requesters
        self._workflows, self._action_types = workflows, action_types
        self._registry, self._promotions = registry, promotions
        self._orchestrator, self._processes, self._store = orchestrator, process_store, store
        self._source_revision, self._clock = source_revision, clock

    async def create(
        self,
        *,
        plan_digest: str,
        evidence_digest: str,
        correlation_id: str,
    ) -> AlertWorkflowResult:
        """Retain exact inputs, create a canonical pending Process and append its proposal.

        The trigger is the retained plan's creation time, never a retry timestamp. This
        method requests no approval and sends no action. Call ``run`` to advance it.
        """
        async with asyncio.timeout(15):
            if not correlation_id or correlation_id.strip() != correlation_id:
                raise AlertExecutionHeld("workflow_correlation_invalid")
            plan, evidence, workflow, target, principal = await self._read_plan(plan_digest)
            if evidence_digest != plan.evidence_digest:
                raise AlertExecutionHeld("workflow_source_evidence_mismatch")
            binding = self._binding(
                plan,
                workflow,
                target,
                principal,
                correlation_id=correlation_id,
                mode=Mode.SHADOW,
            )
            key = workflow_binding_key(binding.process_id)
            raw = await self._store.read_state(key)
            proof: DecisionEvidenceAdmission | None = None
            if raw is not None:
                retained = self._decode(raw)
                binding = binding.model_copy(update={"mode": retained.mode})
                if binding != retained:
                    raise AlertExecutionHeld("workflow_invocation_conflict")
                if binding.mode is Mode.ENFORCE:
                    proof = await self._promotion_admission(workflow, plan, target)
            else:
                if await self._processes.get(binding.process_id) is not None:
                    raise AlertExecutionHeld("workflow_binding_not_retained")
                proof = await self._promotion_admission(workflow, plan, target)
                if proof is not None:
                    binding = binding.model_copy(update={"mode": Mode.ENFORCE})
            if await self._requesters.resolve(requester_ref=plan.requester_ref) != principal:
                raise AlertExecutionHeld("workflow_requester_changed")
            now = self._clock()
            if not plan.created_at <= now < plan.expires_at or not evidence.stamp.current_at(now):
                raise AlertExecutionHeld("workflow_evidence_not_current")
            if binding.mode is Mode.ENFORCE and not self._promotion_current(
                workflow, plan, target, proof
            ):
                raise AlertExecutionHeld("workflow_promotion_not_current")
            record = binding.to_record()
            await self._store.write_state_with_audit_if_absent(
                key,
                record,
                {
                    "actor": "Forseti",
                    "action_kind": "alert_noise.workflow.bound",
                    "process_id": binding.process_id,
                    "correlation_id": binding.correlation_id,
                    "record_digest": record["record_digest"],
                    "plan_digest": plan_digest,
                    "mode": binding.mode.value,
                    "recorded_at": now.isoformat(),
                    "promotion_receipt_digest": proof.receipt_digest if proof else None,
                    "promotion_bundle_digest": proof.verification_bundle_digest if proof else None,
                    "execution_authority": False,
                },
            )
            if await self._store.read_state(key) != record:
                raise AlertExecutionHeld("workflow_invocation_conflict")
            await self._create_process(binding, workflow, plan, self._clock())
            resolution = await self.resolve(process_id=binding.process_id)
            self.require_current(resolution)
            if binding.mode is Mode.ENFORCE:
                self.require_promotion_current(resolution, proof)
            return self._result(resolution)

    async def run(
        self,
        *,
        plan_digest: str,
        evidence_digest: str,
        correlation_id: str,
    ) -> AlertWorkflowResult:
        """Create or reuse one retained-plan Process, then run its canonical workflow."""
        async with asyncio.timeout(30):
            initial = await self.create(
                plan_digest=plan_digest,
                evidence_digest=evidence_digest,
                correlation_id=correlation_id,
            )
            return await self.resume(process_id=initial.process_id)

    async def resume(self, *, process_id: str) -> AlertWorkflowResult:
        """Resume only the original target, mode, full private context and correlation."""
        async with asyncio.timeout(15):
            resolution = await self.resolve(process_id=process_id)
            binding = resolution.binding
            if resolution.snapshot.status.terminal:
                return self._result(resolution)
            if resolution.snapshot.status is not ProcessStatus.COMPENSATING:
                self.require_current(resolution)
            proof = None
            if binding.mode is Mode.ENFORCE:
                proof = await self.promotion_admission(resolution)
                self.require_promotion_current(resolution, proof)
            # The public canonical API verifies that the parent-bound orchestrator sees
            # this same retained Process, rather than silently starting in another store.
            envelope = await self._orchestrator.resume_metadata(
                process_id=process_id,
                workflows={resolution.workflow.name: resolution.workflow},
            )
            expected_resume = build_resume_payload(
                workflow=resolution.workflow,
                action_types=self._action_types,
                trigger_ts=binding.trigger_ts,
                mode=binding.mode,
                context=binding.context,
            )
            if (
                envelope.mode is not binding.mode
                or envelope.target_resource_id != binding.target_resource_id
                or envelope.correlation_id != binding.correlation_id
                or envelope.trigger_ts != binding.trigger_ts
                or dict(envelope.context) != expected_resume["context"]
            ):
                raise AlertExecutionHeld("workflow_runtime_binding_mismatch")
            await self._store.append_audit_entry(
                {
                    "actor": "Forseti",
                    "action_kind": "alert_noise.workflow.invocation",
                    "process_id": process_id,
                    "correlation_id": binding.correlation_id,
                    "record_ref": workflow_binding_key(process_id),
                    "context_digest": content_digest(dict(binding.context)),
                    "plan_digest": binding.plan_digest,
                    "mode": binding.mode.value,
                    "promotion_receipt_digest": proof.receipt_digest if proof else None,
                    "promotion_bundle_digest": proof.verification_bundle_digest if proof else None,
                    "recorded_at": self._clock().isoformat(),
                    "execution_authority": False,
                }
            )
            if (
                await self._requesters.resolve(requester_ref=binding.requester_ref)
                != binding.requester_principal
            ):
                raise AlertExecutionHeld("workflow_requester_changed")
            if resolution.snapshot.status is not ProcessStatus.COMPENSATING:
                self.require_current(resolution)
            if binding.mode is Mode.ENFORCE:
                self.require_promotion_current(resolution, proof)
            run = await self._orchestrator.run(
                resolution.workflow,
                target_resource_id=binding.target_resource_id,
                trigger_ts=binding.trigger_ts,
                context=binding.context,
                correlation_id=binding.correlation_id,
                now=self._clock(),
                mode=binding.mode,
            )
            if run.process_id != binding.process_id or run.mode != binding.mode.value:
                raise AlertExecutionHeld("workflow_runtime_result_mismatch")
            return AlertWorkflowResult(
                run.process_id, run.workflow_name, binding.plan_digest, run.status, binding.mode
            )

    @staticmethod
    def _result(resolution: AlertWorkflowResolution) -> AlertWorkflowResult:
        binding = resolution.binding
        return AlertWorkflowResult(
            binding.process_id,
            binding.workflow_ref,
            binding.plan_digest,
            resolution.snapshot.status,
            binding.mode,
        )
