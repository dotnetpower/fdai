"""Only the exact retained baseline, replay and real canonical Process reference are projected."""

import pytest
from fdai.core.detection.alert_noise.planning import plan_alert_change
from fdai.core.detection.alert_noise.workflow_models import AlertWorkflowResult
from fdai.delivery.alert_noise_projection import alert_proposal_detail
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.process_runtime import ProcessStatus
from fdai_service_contracts.alert_noise import NoisePolicy, digest_record
from fdai_service_contracts.alert_noise_projection import AlertProposalDetail

from .test_planning import routing


def test_bound_baseline_and_recorded_process_do_not_claim_approval(evidence, now):
    plan = plan_alert_change(
        evidence, routing(), policy=NoisePolicy(), requester_ref="person:requester", now=now
    )
    workflow = AlertWorkflowResult(
        "example-process",
        "alert-routing-change",
        digest_record(plan),
        ProcessStatus.WAITING,
        Mode.SHADOW,
    )
    detail = alert_proposal_detail(plan, evidence, None, workflow, now=now)
    assert detail.baseline.rule == evidence.rules[0]
    assert digest_record(detail.baseline) == plan.rollback_ref
    assert detail.process is not None and detail.process.status == "waiting"
    assert detail.process.mode == "shadow" and not detail.execution_authority
    assert AlertProposalDetail.model_validate_json(detail.model_dump_json()) == detail
    with pytest.raises(ValueError, match="retained plan"):
        detail.model_copy(update={"plan_digest": "sha256:" + "f" * 64}).require_plan(plan)
    wrong = detail.baseline.model_copy(
        update={"rule": evidence.rules[0].model_copy(update={"enabled": False})}
    )
    with pytest.raises(ValueError, match="retained plan"):
        detail.model_copy(update={"baseline": wrong}).require_plan(plan)


def test_missing_workflow_is_explicit_absence(evidence, now):
    plan = plan_alert_change(
        evidence, routing(), policy=NoisePolicy(), requester_ref="person:requester", now=now
    )
    detail = alert_proposal_detail(plan, evidence, None, None, now=now)
    assert detail.process is None and detail.evaluation is None
