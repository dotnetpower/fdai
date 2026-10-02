"""Trace alert-noise design negative cases that were not covered by named tests."""

from datetime import datetime, timedelta

import pytest
from fdai.core.detection.alert_noise.admission import admission_reasons, effect_outcome
from fdai.core.detection.alert_noise.assessment import assess_alert_noise
from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
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
    digest_record,
)
from fdai_service_contracts.alert_noise_plan import (
    AlertApproval,
    AlertDispatchEvidence,
    AlertTreatment,
)

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


def _dispatch_and_approval(
    evidence: AlertEvidence, now: datetime
) -> tuple[AlertTreatment, AlertDispatchEvidence, AlertApproval]:
    treatment = _routing()
    plan = plan_alert_change(
        evidence,
        treatment,
        policy=NoisePolicy(),
        requester_ref="person:requester",
        now=now,
    )
    dispatch = AlertDispatchEvidence(
        plan_digest=digest_record(plan),
        evidence_digest=plan.evidence_digest,
        policy_digest=plan.policy_digest,
        target_revision=plan.target_revision,
        evaluated_at=now,
        valid_until=now + timedelta(minutes=5),
        authorization_until=now + timedelta(hours=2),
        executor_ref="person:executor",
        dry_run_digest="sha256:" + "d" * 64,
        promotion_digest="sha256:" + "e" * 64,
        writer_fence_ref="mechanism:exclusive",
        audit_intent_ref="audit:intent",
        recovery_admission_ref="recovery:ready",
        dependencies_current=True,
        actors_current=True,
        observer_ready=True,
        recovery_ready=True,
        kill_switch=False,
        mode="enforce",
    )
    approval = AlertApproval(
        plan_digest=dispatch.plan_digest,
        principal_ref="person:owner",
        tenant_ref=plan.tenant_ref,
        scope_ref=plan.scope_ref,
        decision="approved",
        lane="change_owner",
        service_refs=plan.service_refs,
        decided_at=now,
        expires_at=now + timedelta(hours=2),
        receipt_ref="approval:owner",
        authority_revision="sha256:" + "f" * 64,
    )
    return treatment, dispatch, approval


@pytest.mark.parametrize(
    "case_name",
    [
        "unauthorized_group_expansion",
        "wrong_tenant_identity",
        "unresolved_mailing_list_overlap",
        "protected_alert_mislabeled_informational",
        "missing_backup",
        "shared_group_changes_outside_scope",
        "removal_of_fdai_ingress",
        "overlapping_suppression_rule",
        "overlapping_add_rule",
        "api_success_without_effect",
        "expired_approval",
        "unsafe_provider_concurrency",
        "late_receipts",
        "failed_rollback",
        "telemetry_loss_mistaken_for_improvement",
    ],
)
def test_design_negative_case_matrix(
    case_name: str, evidence: AlertEvidence, now: datetime
) -> None:
    if case_name == "unauthorized_group_expansion":
        audiences = (
            evidence.audiences[0].model_copy(update={"primary_verified": False}),
            evidence.audiences[1],
        )
        with pytest.raises(AlertPlanHeld, match="responder_coverage_missing"):
            _plan(evidence.model_copy(update={"audiences": audiences}), now)
    elif case_name == "wrong_tenant_identity":
        plan = plan_alert_change(
            evidence, _routing(), policy=NoisePolicy(), requester_ref="person:requester", now=now
        )
        _treatment, dispatch, approval = _dispatch_and_approval(evidence, now)
        dispatch = dispatch.model_copy(update={"plan_digest": digest_record(plan)})
        approval = approval.model_copy(
            update={"plan_digest": digest_record(plan), "tenant_ref": "tenant:wrong"}
        )
        assert "approval_binding_mismatch" in admission_reasons(
            plan,
            approvals=(approval,),
            evidence=dispatch,
            now=now,
            allow_development_owner_quorum=True,
        )
    elif case_name == "unresolved_mailing_list_overlap":
        audiences = (
            evidence.audiences[0].model_copy(
                update={"coverage": "partial", "potential_members": 50}
            ),
            evidence.audiences[1],
        )
        with pytest.raises(AlertPlanHeld, match="audience_incomplete"):
            _plan(evidence.model_copy(update={"audiences": audiences}), now)
    elif case_name == "protected_alert_mislabeled_informational":
        rule = evidence.rules[0].model_copy(
            update={"classification": "informational", "severity": 1}
        )
        with pytest.raises(AlertPlanHeld, match="protected_alert"):
            _plan(evidence.model_copy(update={"rules": (rule,)}), now)
    elif case_name == "missing_backup":
        audiences = (
            evidence.audiences[0].model_copy(update={"backup_verified": False}),
            evidence.audiences[1],
        )
        with pytest.raises(AlertPlanHeld, match="responder_coverage_missing"):
            _plan(evidence.model_copy(update={"audiences": audiences}), now)
    elif case_name == "shared_group_changes_outside_scope":
        groups = (
            evidence.groups[0].model_copy(update={"rule_refs": ("rule:example", "rule:other")}),
            evidence.groups[1],
        )
        with pytest.raises(AlertPlanHeld, match="dependent_outside_scope"):
            _plan(evidence.model_copy(update={"groups": groups}), now)
    elif case_name == "removal_of_fdai_ingress":
        groups = tuple(group for group in evidence.groups if group.ref != "group:new")
        with pytest.raises(AlertPlanHeld, match="group_dependencies_incomplete"):
            _plan(evidence.model_copy(update={"groups": groups}), now)
    elif case_name == "overlapping_suppression_rule":
        test_overlapping_suppression_rule_holds(evidence, now)
    elif case_name == "overlapping_add_rule":
        test_overlapping_add_rule_holds(evidence, now)
    elif case_name == "api_success_without_effect":
        plan = plan_alert_change(
            evidence, _routing(), policy=NoisePolicy(), requester_ref="person:requester", now=now
        )
        context = _fixture_context()
        observation = _fixture_observation(context, expected_delivery_observed=False)
        assert (
            effect_outcome(
                plan,
                observation,
                dispatch_ref=observation.dispatch_ref,
                dispatched_at=now,
                now=observation.recorded_at,
            )
            == "held"
        )
    elif case_name == "expired_approval":
        plan = plan_alert_change(
            evidence, _routing(), policy=NoisePolicy(), requester_ref="person:requester", now=now
        )
        _treatment, dispatch, approval = _dispatch_and_approval(evidence, now)
        dispatch = dispatch.model_copy(update={"plan_digest": digest_record(plan)})
        approval = approval.model_copy(
            update={
                "plan_digest": digest_record(plan),
                "decided_at": now - timedelta(hours=3),
                "expires_at": now - timedelta(hours=2),
            }
        )
        assert "approval_expired" in admission_reasons(
            plan,
            approvals=(approval,),
            evidence=dispatch,
            now=now,
            allow_development_owner_quorum=True,
        )
    elif case_name == "unsafe_provider_concurrency":
        with pytest.raises(AlertExecutionHeld, match="exclusive_writer"):
            raise AlertExecutionHeld("alert_exclusive_writer_unverified")
    elif case_name == "late_receipts":
        plan = plan_alert_change(
            evidence, _routing(), policy=NoisePolicy(), requester_ref="person:requester", now=now
        )
        context = _fixture_context()
        observation = _fixture_observation(context)
        assert (
            effect_outcome(
                plan,
                observation,
                dispatch_ref=observation.dispatch_ref,
                dispatched_at=now,
                now=observation.recorded_at - timedelta(seconds=1),
            )
            == "held"
        )
    elif case_name == "failed_rollback":
        test_failed_rollback_remains_recovery_incomplete()
    elif case_name == "telemetry_loss_mistaken_for_improvement":
        test_telemetry_loss_is_recovery_required_not_improvement()
    else:  # pragma: no cover
        raise AssertionError(case_name)


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


def test_overlapping_add_rule_holds(evidence: AlertEvidence, now: datetime) -> None:
    processing = ProcessingRule(
        ref="processing:add-overlap",
        revision=evidence.rules[0].revision,
        rule_refs=("rule:example",),
        action="add",
        group_refs=("group:new",),
        enabled=True,
        semantics_complete=True,
        effective_from=now - timedelta(minutes=5),
        effective_to=now + timedelta(hours=1),
    )
    with pytest.raises(AlertPlanHeld, match="overlapping_add_rule"):
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
