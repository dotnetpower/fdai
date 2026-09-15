"""Single-axis, protected-path and approval-bound alert plan tests."""

from datetime import datetime, timedelta

import pytest
from fdai.core.detection.alert_noise.planning import AlertPlanHeld, plan_alert_change
from fdai_service_contracts.alert_noise import AlertEvidence, NoisePolicy, ProcessingRule
from fdai_service_contracts.alert_noise_plan import AlertTreatment


def routing() -> AlertTreatment:
    return AlertTreatment(
        kind="routing",
        target_ref="rule:example",
        remove_group_ref="group:old",
        replacement_group_ref="group:new",
    )


def test_routing_plan_is_inert(evidence: AlertEvidence, now: datetime) -> None:
    plan = plan_alert_change(
        evidence, routing(), policy=NoisePolicy(), requester_ref="person:requester", now=now
    )
    assert plan.execution_path == "pr_manual"
    assert plan.default_mode == "shadow"
    assert plan.quorum_required == 2
    assert not plan.execution_authority
    assert plan.lock_refs == tuple(sorted(set(plan.lock_refs)))


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("severity", 1, "protected_alert"),
        ("classification", "unknown", "protected_alert"),
        ("active_incident", True, "active_incident_dependency"),
        ("iac_owned", False, "iac_ownership_missing"),
        ("ownership_verified", False, "service_ownership_missing"),
    ],
)
def test_unsafe_rule_holds(
    evidence: AlertEvidence, now: datetime, field: str, value: object, reason: str
) -> None:
    evidence = evidence.model_copy(
        update={"rules": (evidence.rules[0].model_copy(update={field: value}),)}
    )
    with pytest.raises(AlertPlanHeld, match=reason):
        plan_alert_change(
            evidence, routing(), policy=NoisePolicy(), requester_ref="person:requester", now=now
        )


def test_automation_and_missing_group_block(evidence: AlertEvidence, now: datetime) -> None:
    group = evidence.groups[0].model_copy(update={"automation_refs": ("automation:ingress",)})
    evidence = evidence.model_copy(update={"groups": (group, evidence.groups[1])})
    with pytest.raises(AlertPlanHeld, match="automation_path_protected"):
        plan_alert_change(
            evidence, routing(), policy=NoisePolicy(), requester_ref="person:requester", now=now
        )


def test_suppression_requires_finite_delayed_window(evidence: AlertEvidence, now: datetime) -> None:
    processing = ProcessingRule(
        ref="processing:example",
        revision=evidence.rules[0].revision,
        rule_refs=("rule:example",),
        action="suppress",
        enabled=False,
        semantics_complete=True,
        effective_from=now,
        effective_to=now + timedelta(hours=2),
    )
    evidence = evidence.model_copy(update={"processing_rules": (processing,)})
    treatment = AlertTreatment(
        kind="suppression",
        target_ref="rule:example",
        processing_rule_ref=processing.ref,
        starts_at=now + timedelta(hours=1),
        ends_at=now + timedelta(hours=2),
    )
    plan = plan_alert_change(
        evidence, treatment, policy=NoisePolicy(), requester_ref="person:requester", now=now
    )
    assert plan.action_type == "ops.set-alert-notification-window"
    with pytest.raises(AlertPlanHeld, match="propagation_budget_insufficient"):
        plan_alert_change(
            evidence,
            treatment.model_copy(update={"starts_at": now}),
            policy=NoisePolicy(),
            requester_ref="person:requester",
            now=now,
        )
