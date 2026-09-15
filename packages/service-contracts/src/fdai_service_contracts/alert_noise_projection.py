"""Exact immutable proposal detail; current approval and effects remain Process-owned."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from fdai_service_contracts.alert_noise import Ref, digest_record
from fdai_service_contracts.alert_noise_base import AlertContractBase, AlertTime, FalseOnly
from fdai_service_contracts.alert_noise_evaluation import (
    EvaluationReceipt,
    evaluation_method_matches,
)
from fdai_service_contracts.alert_noise_plan import AlertChangePlan, AlertRollbackBaseline
from fdai_service_contracts.executor_models import Digest


class AlertProcessLink(AlertContractBase):
    """Recorded invocation reference, never a substitute for the current canonical journal."""

    process_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,200}$")]
    workflow_ref: Ref
    status: Literal[
        "pending",
        "running",
        "waiting",
        "compensating",
        "compensated",
        "succeeded",
        "failed",
        "cancelled",
        "timed_out",
    ]
    mode: Literal["shadow", "enforce"]


class AlertProposalDetail(AlertContractBase):
    """Safe baseline values and measured detector guards with exact retained-plan commitments."""

    plan_digest: Digest
    baseline: AlertRollbackBaseline
    evaluation: EvaluationReceipt | None = None
    process: AlertProcessLink | None = None
    recorded_at: AlertTime
    execution_authority: FalseOnly = False

    def require_plan(self, plan: AlertChangePlan) -> None:
        """Reject detached baseline, detector comparison or an unbound target before projection."""
        if (
            self.plan_digest != digest_record(plan)
            or digest_record(self.baseline) != plan.rollback_ref
            or self.baseline.rule.ref != plan.treatment.target_ref
            or self.recorded_at < plan.created_at
        ):
            raise ValueError("alert proposal detail does not match its retained plan")
        changed = self.baseline.processing_rule or self.baseline.rule
        if changed.revision != plan.target_revision:
            raise ValueError("alert proposal detail target revision does not match")
        if (self.evaluation is None) != (plan.evaluation_receipt_digest is None):
            raise ValueError("alert proposal detail MUST preserve its measured evaluation")
        if self.evaluation is not None and (
            digest_record(self.evaluation) != plan.evaluation_receipt_digest
            or not self.evaluation.accepted
            or not evaluation_method_matches(self.evaluation)
            or self.evaluation.rule_ref != plan.treatment.target_ref
            or self.evaluation.rule_revision != self.baseline.rule.revision
            or self.evaluation.baseline != self.baseline.rule.evaluation
            or self.evaluation.treatment != plan.treatment.evaluation
        ):
            raise ValueError("alert proposal detail evaluation commitment does not match")
