"""Pure catalog, target, and promotion-input binding for retained alert plans."""

from __future__ import annotations

from collections.abc import Mapping

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan, AlertRollbackBaseline
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.detection.alert_noise.execution_models import RESTORE_ACTION, AlertExecutionHeld
from fdai.core.detection.alert_noise.workflow_models import (
    _PLAN_PARAMS,
    ALERT_WORKFLOW_PROMOTION_PURPOSE,
    ALERT_WORKFLOWS,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    Mode,
    OntologyActionType,
    Workflow,
    WorkflowStepKind,
)
from fdai.shared.providers.process_runtime import PROCESS_ID_PATTERN


def alert_workflow_target(plan: AlertChangePlan, baseline: AlertRollbackBaseline) -> str:
    """Return the one object being edited, never the detector's monitored Resource."""
    processing = baseline.processing_rule
    if (
        digest_record(baseline) != plan.rollback_ref
        or baseline.rule.ref != plan.treatment.target_ref
        or (processing is not None) != (plan.treatment.kind == "suppression")
    ):
        raise AlertExecutionHeld("workflow_baseline_mismatch")
    target, revision = baseline.rule.ref, baseline.rule.revision
    if processing is not None:
        if processing.ref != plan.treatment.processing_rule_ref or set(processing.rule_refs) != {
            baseline.rule.ref
        }:
            raise AlertExecutionHeld("workflow_processing_target_mismatch")
        target, revision = processing.ref, processing.revision
    if revision != plan.target_revision or target not in plan.lock_refs:
        raise AlertExecutionHeld("workflow_target_revision_mismatch")
    return target


def alert_workflow_for_plan(
    plan: AlertChangePlan,
    *,
    workflows: Mapping[str, Workflow],
    action_types: Mapping[str, OntologyActionType],
) -> Workflow:
    """Select the reviewed two-step catalog composition without authoring a workflow."""
    name, step_id = ALERT_WORKFLOWS[plan.action_type]
    candidate = workflows.get(name)
    if candidate is None:
        raise AlertExecutionHeld("workflow_not_registered")
    workflow = Workflow.model_validate(candidate.model_dump(mode="python"))
    if (
        workflow.name != name
        or workflow.default_mode is not Mode.SHADOW
        or len(workflow.steps) != 2
        or any(name not in action_types for name in (plan.action_type, RESTORE_ACTION))
    ):
        raise AlertExecutionHeld("workflow_catalog_mismatch")
    if any(action_types[name].name != name for name in (plan.action_type, RESTORE_ACTION)):
        raise AlertExecutionHeld("workflow_action_catalog_mismatch")
    approval, action = workflow.steps
    if (
        approval.id != "approve_plan"
        or approval.kind is not WorkflowStepKind.APPROVAL
        or approval.approval_role is not CeilingRole.OWNER
        or approval.quorum != 2
        or approval.no_self_approval is not True
        or approval.params
        or action.id != step_id
        or action.kind is not WorkflowStepKind.ACTION
        or action.action_type_ref != plan.action_type
        or action.params != _PLAN_PARAMS
        or action.compensated_by != RESTORE_ACTION
        or any(step.on_failure or step.guard_rule_ref or step.gate_ref for step in workflow.steps)
    ):
        raise AlertExecutionHeld("workflow_steps_mismatch")
    return workflow


def workflow_promotion_binding(
    *,
    workflow: Workflow,
    plan: AlertChangePlan,
    target_resource_id: str,
    source_revision: str,
) -> dict[str, object]:
    """Describe exact promotion inputs; this is not promotion evidence or a writer.

    A separately reviewed producer must supply the receipt and independent verifier.
    The full canonical Workflow, plan, target/dependencies and source version are bound.
    """
    document = workflow.model_dump(mode="json")
    return {
        "schema_version": "1.0.0",
        "workflow": document,
        "workflow_version": str(workflow.version),
        "workflow_digest": content_digest(document),
        "mode": Mode.ENFORCE.value,
        "plan_digest": digest_record(plan),
        "scope_digest": content_digest(
            {
                "tenant_ref": plan.tenant_ref,
                "scope_ref": plan.scope_ref,
                "target_resource_id": target_resource_id,
                "target_revision": plan.target_revision,
                "service_refs": list(plan.service_refs),
                "lock_refs": list(plan.lock_refs),
            }
        ),
        "purpose_id": ALERT_WORKFLOW_PROMOTION_PURPOSE,
        "source_revision": source_revision,
    }


def workflow_binding_key(process_id: str) -> str:
    """Address one private launch record, with no latest-record or cross-store lookup."""
    if not PROCESS_ID_PATTERN.fullmatch(process_id):
        raise AlertExecutionHeld("workflow_process_identity_invalid")
    return "alert-noise:workflow:" + process_id
