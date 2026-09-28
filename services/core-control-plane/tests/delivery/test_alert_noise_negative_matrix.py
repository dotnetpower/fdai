"""Trace alert-noise design negative cases that were not covered by named tests."""

from datetime import datetime, timedelta

import pytest
from fdai.core.detection.alert_noise.assessment import assess_alert_noise
from fdai.core.detection.alert_noise.outcomes import (
    alert_response_outcome,
    classify_alert_effect,
)
from fdai.core.detection.alert_noise.planning import AlertPlanHeld, plan_alert_change
from fdai.shared.contracts.models import ResponseOutcomeLabel
from fdai_service_contracts.alert_noise import (
    AlertDelivery,
    AlertEvidence,
    NoisePolicy,
    ProcessingRule,
)
from fdai_service_contracts.alert_noise_plan import AlertTreatment

from tests.core.detection.alert_noise.conftest import evidence as evidence
from tests.core.detection.alert_noise.conftest import now as now
from tests.core.detection.alert_noise.test_outcomes import (
    _fixture_context,
    _fixture_observation,
)


def _routing() -> AlertTreatment:
    return AlertTreatment(
        kind="routing",
        target_ref="rule:example",
        remove_group_ref="group:old",
        replacement_group_ref="group:new",
    )


def _plan(evidence: AlertEvidence, now: datetime) -> None:
    plan_alert_change(
        evidence,
        _routing(),
        policy=NoisePolicy(),
        requester_ref="person:requester",
        now=now,
    )


def test_unresolved_mailing_list_overlap_holds_approval_scope(
    evidence: AlertEvidence, now: datetime
) -> None:
    audiences = (
        evidence.audiences[0].model_copy(update={"coverage": "partial", "potential_members": 50}),
        evidence.audiences[1],
    )
    with pytest.raises(AlertPlanHeld, match="audience_incomplete"):
        _plan(evidence.model_copy(update={"audiences": audiences}), now)


def test_missing_backup_holds_approval_scope(evidence: AlertEvidence, now: datetime) -> None:
    audiences = (
        evidence.audiences[0].model_copy(update={"backup_verified": False}),
        evidence.audiences[1],
    )
    with pytest.raises(AlertPlanHeld, match="responder_coverage_missing"):
        _plan(evidence.model_copy(update={"audiences": audiences}), now)


def test_shared_group_changes_outside_scope_hold(evidence: AlertEvidence, now: datetime) -> None:
    groups = (
        evidence.groups[0].model_copy(update={"rule_refs": ("rule:example", "rule:other")}),
        evidence.groups[1],
    )
    with pytest.raises(AlertPlanHeld, match="dependent_outside_scope"):
        _plan(evidence.model_copy(update={"groups": groups}), now)


def test_protected_alert_mislabeled_informational_holds(
    evidence: AlertEvidence, now: datetime
) -> None:
    rule = evidence.rules[0].model_copy(update={"classification": "informational", "severity": 1})
    with pytest.raises(AlertPlanHeld, match="protected_alert"):
        _plan(evidence.model_copy(update={"rules": (rule,)}), now)


def test_overlapping_suppression_rule_holds(evidence: AlertEvidence, now: datetime) -> None:
    processing = ProcessingRule(
        ref="processing:overlap",
        revision=evidence.rules[0].revision,
        rule_refs=("rule:example",),
        action="suppress",
        enabled=True,
        semantics_complete=True,
        effective_from=now - timedelta(minutes=5),
        effective_to=now + timedelta(hours=1),
    )
    with pytest.raises(AlertPlanHeld, match="overlapping_suppression"):
        _plan(evidence.model_copy(update={"processing_rules": (processing,)}), now)


def test_candidate_bound_preserves_partial_evidence_without_truncating_scope(
    evidence: AlertEvidence, now: datetime
) -> None:
    rules = tuple(
        evidence.rules[0].model_copy(
            update={"ref": f"rule:{index}", "service_ref": f"service:{index}"}
        )
        for index in range(6)
    )
    deliveries = tuple(
        AlertDelivery(
            ref=f"event:{index}",
            episode_ref=f"episode:{index}",
            rule_ref=rules[index // 2].ref,
            rule_revision=rules[index // 2].revision,
            condition="fired",
            state="source",
            event_at=now - timedelta(seconds=index + 1),
            receipt_ref=f"receipt:{index}",
        )
        for index in range(12)
    )
    observed = evidence.model_copy(update={"rules": rules, "deliveries": deliveries})

    report = assess_alert_noise(
        observed,
        policy=NoisePolicy(burst_threshold=2, max_candidates=3),
        now=now,
    )

    assert report.coverage == "partial"
    assert "candidate_limit_reached" in report.reasons
    assert report.source_episodes == 12
    assert {finding.rule_ref for finding in report.findings} == {"rule:0", "rule:1", "rule:2"}


def test_telemetry_loss_is_recovery_required_not_improvement() -> None:
    context = _fixture_context()
    observation = _fixture_observation(context, collection_continues=False)

    assert classify_alert_effect(context, observation, now=observation.recorded_at) == (
        "recovery_required"
    )
    outcome = alert_response_outcome(
        context,
        observation,
        receipt_digest="sha256:" + "c" * 64,
        now=observation.recorded_at,
    )
    assert outcome is not None
    assert outcome.label is ResponseOutcomeLabel.MISMATCH
    assert outcome.observed_value == 0.0


def test_failed_rollback_remains_recovery_incomplete() -> None:
    context = _fixture_context(restore=True)
    observation = _fixture_observation(context, configuration_matches=False)

    assert classify_alert_effect(context, observation, now=observation.recorded_at) == (
        "recovery_incomplete"
    )
    outcome = alert_response_outcome(
        context,
        observation,
        receipt_digest="sha256:" + "c" * 64,
        now=observation.recorded_at,
    )
    assert outcome is not None
    assert outcome.label is ResponseOutcomeLabel.MISMATCH
    assert outcome.rollback_succeeded is None
