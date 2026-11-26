"""Pure, unselected DecisionCase projection for a retained alert workflow proposal."""

from __future__ import annotations

import json
from dataclasses import asdict

from fdai_service_contracts.alert_noise import digest_record
from fdai_service_contracts.alert_noise_plan import AlertChangePlan
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.decision_case.models import (
    ActionArguments,
    ActionOption,
    DecisionCase,
    ObjectiveEffect,
)
from fdai.core.detection.alert_noise.execution_models import AlertExecutionHeld
from fdai.core.detection.alert_noise.workflow_models import AlertWorkflowBinding


def alert_decision_case(binding: AlertWorkflowBinding, plan: AlertChangePlan) -> DecisionCase:
    """Record no-change and an unselected proposal without predicting numeric benefit.

    The only numeric effect is the declared object count (zero or one), not an estimate
    of notifications, utility gain, delivery, recall or human interruption reduction.
    Both utilities are neutral; no arbitration or approval is fabricated.
    """
    if (
        binding.plan_digest != digest_record(plan)
        or binding.evidence_digest != plan.evidence_digest
    ):
        raise AlertExecutionHeld("workflow_decision_case_binding_mismatch")
    refs = (binding.plan_digest, plan.evidence_digest, plan.policy_digest, plan.rollback_ref)

    def footprint(count: int) -> ObjectiveEffect:
        return ObjectiveEffect(
            objective_id="declared_change_footprint",
            utility=0.0,
            confidence=1.0,
            metric="planned_changed_objects",
            expected_min=float(count),
            expected_max=float(count),
            observation_window_seconds=plan.max_observation_seconds,
        )

    baseline = (footprint(0),)
    return DecisionCase(
        case_id="alert-noise-case:"
        + content_digest(
            {
                "process_id": binding.process_id,
                "plan_digest": binding.plan_digest,
                "workflow_digest": binding.workflow_digest,
            }
        ).removeprefix("sha256:"),
        correlation_id=binding.correlation_id,
        context_snapshot_id=plan.evidence_digest,
        created_at=plan.created_at,
        no_action_effects=baseline,
        options=(
            ActionOption(
                option_id="no-action",
                action_type=None,
                effects=baseline,
                evidence_refs=refs,
            ),
            ActionOption(
                option_id="proposed-change",
                action_type=plan.action_type,
                effects=(footprint(1),),
                evidence_refs=refs,
                proposing_agents=("Forseti",),
                assumptions=("Notification benefit is unmeasured; this proposal is not selected.",),
                arguments=ActionArguments.create({"plan_digest": binding.plan_digest[7:]}),
            ),
        ),
        protected_objective_ids=("protected_alert_coverage",),
        active_constraint_ids=("independent_approval", "promotion", "seven_safeguards"),
        evidence_refs=refs,
        process_id=binding.process_id,
        logic_release_digest=binding.workflow_digest,
    )


def _proposal_payload(binding: AlertWorkflowBinding, plan: AlertChangePlan) -> dict[str, object]:
    case = alert_decision_case(binding, plan)
    case_record = asdict(case)
    case_record["created_at"] = case.created_at.isoformat()
    return {
        "domain": "alert_noise",
        "phase": "proposal_ready",
        "actor_agent": "Forseti",
        "decision_case_id": case.case_id,
        "decision_case": json.loads(json.dumps(case_record, allow_nan=False)),
        "context_digest": content_digest(dict(binding.context)),
        "logic_release_digest": binding.workflow_digest,
        "evidence_refs": list(case.evidence_refs),
        "plan_digest": binding.plan_digest,
        "evidence_digest": plan.evidence_digest,
        "proposal_ref": "alert-noise:plan:" + binding.plan_digest,
        "proposal": plan.model_dump(mode="json"),
        "expected_notification_benefit": None,
        "selected_option_id": None,
        "execution_authority": False,
        "approval_authority": False,
        "promotion_authority": False,
    }
