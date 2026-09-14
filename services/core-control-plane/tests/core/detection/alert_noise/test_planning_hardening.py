"""Round 4: missing ownership, paths, reverse dependencies or active incidents hold planning."""

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


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"ownership_verified": False}, "service_ownership_missing"),
        ({"iac_owned": False}, "iac_ownership_missing"),
        ({"enabled": False}, "disabled_detector"),
        ({"active_incident": True}, "active_incident_dependency"),
        ({"severity": 1}, "protected_alert"),
        ({"classification": "unknown"}, "protected_alert"),
    ],
)
def test_target_authority_and_protection_are_not_optional(
    evidence: AlertEvidence, now: datetime, change: dict, reason: str
) -> None:
    altered = evidence.model_copy(update={"rules": (evidence.rules[0].model_copy(update=change),)})
    with pytest.raises(AlertPlanHeld, match=reason):
        plan_alert_change(
            altered, routing(), policy=NoisePolicy(), requester_ref="principal:r", now=now
        )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"reverse_complete": False}, "group_dependencies_incomplete"),
        ({"automation_refs": ("automation:ingress",)}, "automation_path_protected"),
        ({"audience_refs": ()}, "audience_empty"),
        ({"rule_refs": ("rule:outside",)}, "dependent_outside_scope"),
        ({"audience_refs": ("audience:missing",)}, "audience_incomplete"),
    ],
)
def test_shared_group_dependencies_cannot_be_truncated(
    evidence: AlertEvidence, now: datetime, change: dict, reason: str
) -> None:
    altered = evidence.model_copy(
        update={"groups": (evidence.groups[0].model_copy(update=change), evidence.groups[1])}
    )
    with pytest.raises(AlertPlanHeld, match=reason):
        plan_alert_change(
            altered, routing(), policy=NoisePolicy(), requester_ref="principal:r", now=now
        )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"coverage": "partial"}, "audience_incomplete"),
        ({"primary_verified": False}, "responder_coverage_missing"),
        ({"backup_verified": False}, "responder_coverage_missing"),
        ({"member_refs": (), "potential_members": 0}, "audience_empty"),
    ],
)
def test_replacement_requires_actual_responder_coverage(
    evidence: AlertEvidence, now: datetime, change: dict, reason: str
) -> None:
    altered = evidence.model_copy(
        update={
            "audiences": (evidence.audiences[0], evidence.audiences[1].model_copy(update=change))
        }
    )
    with pytest.raises(AlertPlanHeld, match=reason):
        plan_alert_change(
            altered, routing(), policy=NoisePolicy(), requester_ref="principal:r", now=now
        )


def test_wrong_target_source_and_stale_evidence_are_held(
    evidence: AlertEvidence, now: datetime
) -> None:
    for treatment, at, reason in [
        (routing().model_copy(update={"target_ref": "rule:other"}), now, "target_not_observed"),
        (
            routing().model_copy(update={"remove_group_ref": "group:other"}),
            now,
            "routing_source_mismatch",
        ),
        (routing(), now + timedelta(days=1), "stale_evidence"),
    ]:
        with pytest.raises(AlertPlanHeld, match=reason):
            plan_alert_change(
                evidence, treatment, policy=NoisePolicy(), requester_ref="principal:r", now=at
            )


def test_processing_overlap_precedence_and_unknown_semantics_hold(
    evidence: AlertEvidence, now: datetime
) -> None:
    processing = ProcessingRule(
        ref="processing:one",
        revision="sha256:" + "a" * 64,
        rule_refs=(evidence.rules[0].ref,),
        action="suppress",
        enabled=True,
        effective_from=now - timedelta(hours=1),
        effective_to=now + timedelta(hours=1),
        semantics_complete=True,
    )
    for rule, reason in [
        (processing, "overlapping_suppression"),
        (
            processing.model_copy(update={"semantics_complete": False}),
            "processing_semantics_unknown",
        ),
    ]:
        with pytest.raises(AlertPlanHeld, match=reason):
            plan_alert_change(
                evidence.model_copy(update={"processing_rules": (rule,)}),
                routing(),
                policy=NoisePolicy(),
                requester_ref="principal:r",
                now=now,
            )
