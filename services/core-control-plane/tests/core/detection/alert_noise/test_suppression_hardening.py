"""Round 5: propagation, provider expiry and rollback bind the actual processing object."""

from datetime import datetime, timedelta

import pytest
from fdai.core.detection.alert_noise.planning import AlertPlanHeld, plan_alert_change
from fdai_service_contracts.alert_noise import (
    AlertEvidence,
    NoisePolicy,
    ProcessingRule,
    digest_record,
)
from fdai_service_contracts.alert_noise_plan import AlertRollbackBaseline, AlertTreatment


def setup_window(evidence: AlertEvidence, now: datetime) -> tuple[AlertEvidence, AlertTreatment]:
    processing = ProcessingRule(
        ref="processing:window",
        revision="sha256:" + "d" * 64,
        rule_refs=(evidence.rules[0].ref,),
        action="suppress",
        enabled=False,
        effective_from=now - timedelta(days=1),
        effective_to=now + timedelta(days=1),
        semantics_complete=True,
    )
    treatment = AlertTreatment(
        kind="suppression",
        target_ref=evidence.rules[0].ref,
        processing_rule_ref=processing.ref,
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
    )
    return evidence.model_copy(update={"processing_rules": (processing,)}), treatment


def test_finite_window_pins_processing_baseline(evidence: AlertEvidence, now: datetime) -> None:
    observed, treatment = setup_window(evidence, now)
    plan = plan_alert_change(
        observed, treatment, policy=NoisePolicy(), requester_ref="principal:r", now=now
    )
    assert plan.target_revision == observed.processing_rules[0].revision
    assert plan.rollback_ref == digest_record(
        AlertRollbackBaseline(rule=observed.rules[0], processing_rule=observed.processing_rules[0])
    )
    assert treatment.processing_rule_ref in plan.lock_refs and plan.execution_authority is False


@pytest.mark.parametrize(
    ("start", "end", "reason"),
    [
        (10, 40, "propagation_budget_insufficient"),
        (60, 121, "suppression_window_exceeds_policy"),
        (1400, 1440, "suppression_deadline_does_not_fit"),
    ],
)
def test_window_budgets_cannot_overrun(
    evidence: AlertEvidence, now: datetime, start: int, end: int, reason: str
) -> None:
    observed, treatment = setup_window(evidence, now)
    treatment = treatment.model_copy(
        update={
            "starts_at": now + timedelta(minutes=start),
            "ends_at": now + timedelta(minutes=end),
        }
    )
    with pytest.raises(AlertPlanHeld, match=reason):
        plan_alert_change(
            observed, treatment, policy=NoisePolicy(), requester_ref="principal:r", now=now
        )


def test_independent_collection_and_exact_scope_required(
    evidence: AlertEvidence, now: datetime
) -> None:
    observed, treatment = setup_window(evidence, now)
    for altered, reason in [
        (
            observed.model_copy(update={"independent_collection": False}),
            "independent_collection_missing",
        ),
        (observed.model_copy(update={"processing_rules": ()}), "processing_target_not_inert"),
        (
            observed.model_copy(
                update={
                    "processing_rules": (
                        observed.processing_rules[0].model_copy(update={"rule_refs": ()}),
                    )
                }
            ),
            "processing_target_scope_mismatch",
        ),
    ]:
        with pytest.raises(AlertPlanHeld, match=reason):
            plan_alert_change(
                altered, treatment, policy=NoisePolicy(), requester_ref="principal:r", now=now
            )


def test_empty_delivery_graph_never_allows_suppression(
    evidence: AlertEvidence, now: datetime
) -> None:
    observed, treatment = setup_window(evidence, now)
    observed = observed.model_copy(
        update={"rules": (observed.rules[0].model_copy(update={"group_refs": ()}),)}
    )
    with pytest.raises(AlertPlanHeld, match="no_delivery_path"):
        plan_alert_change(
            observed, treatment, policy=NoisePolicy(), requester_ref="principal:r", now=now
        )
