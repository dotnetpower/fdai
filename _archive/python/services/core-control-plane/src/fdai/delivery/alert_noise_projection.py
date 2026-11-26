"""Project exact retained alert plan inputs, not live claims or private audience membership."""

from __future__ import annotations

from datetime import datetime

from fdai_service_contracts.alert_noise import AlertEvidence, digest_record
from fdai_service_contracts.alert_noise_evaluation import EvaluationReceipt
from fdai_service_contracts.alert_noise_plan import AlertChangePlan, AlertRollbackBaseline
from fdai_service_contracts.alert_noise_projection import AlertProcessLink, AlertProposalDetail

from fdai.core.detection.alert_noise.workflow_models import AlertWorkflowResult


def alert_proposal_detail(
    plan: AlertChangePlan,
    evidence: AlertEvidence,
    evaluation: EvaluationReceipt | None,
    workflow: AlertWorkflowResult | None,
    *,
    now: datetime,
) -> AlertProposalDetail:
    """Copy only the exact no-authority baseline, measured replay and actual Process reference."""
    if workflow is not None and workflow.plan_digest != digest_record(plan):
        raise ValueError("alert proposal Process does not match its retained plan")
    baseline = AlertRollbackBaseline(
        rule=next(row for row in evidence.rules if row.ref == plan.treatment.target_ref),
        processing_rule=next(
            (
                row
                for row in evidence.processing_rules
                if row.ref == plan.treatment.processing_rule_ref
            ),
            None,
        ),
    )
    detail = AlertProposalDetail(
        plan_digest=digest_record(plan),
        baseline=baseline,
        evaluation=evaluation,
        process=AlertProcessLink.model_validate(
            {
                "process_id": workflow.process_id,
                "workflow_ref": workflow.workflow_ref,
                "status": workflow.status.value,
                "mode": workflow.mode.value,
            }
        )
        if workflow is not None
        else None,
        recorded_at=now,
    )
    detail.require_plan(plan)
    return detail
