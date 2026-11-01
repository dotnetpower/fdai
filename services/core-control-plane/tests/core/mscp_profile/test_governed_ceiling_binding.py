"""Focused tests for governed MSCP profile lifecycle and never-raising ceiling binding."""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.mscp_profile.authority_ceiling import MscpAuthorityReason
from fdai.core.mscp_profile.governed_ceiling_binding import (
    ControlDecisionLevel,
    GovernedCeilingBindingError,
    GovernedCeilingDecisionInput,
    GovernedMscpCeilingBinding,
    GovernedReadinessWindowReceipt,
)
from fdai.core.mscp_profile.profile_lifecycle import IndependentProfileReview, readiness_digest
from fdai.core.mscp_profile.readiness import (
    MscpCandidateKey,
    MscpReadinessPolicy,
    MscpReadinessReport,
    ReviewedEffectOutcome,
    evaluate_mscp_readiness,
)

_NOW = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
_CANDIDATE = MscpCandidateKey(
    action_type="ops.restart-pod",
    effect_metric="pod_ready_ratio",
    environment="production",
    observer_version="observer-v2",
)
_DECISION_RANK: dict[ControlDecisionLevel, int] = {
    "deny": 0,
    "hold": 1,
    "require_approval": 2,
    "execute": 3,
}


def _readiness_report() -> MscpReadinessReport:
    outcomes = tuple(
        ReviewedEffectOutcome(
            candidate=_CANDIDATE,
            observed_at=_NOW - timedelta(days=index % 14, seconds=index),
            reviewed=True,
            prediction_accurate=True,
            false_positive=False,
            false_negative=False,
            policy_escape=False,
            correlation_error=False,
            verified_then_rollback_or_incident=False,
            observer_available=True,
            stale=False,
            provider_failed=False,
            observation_latency_ms=120,
            rollback=False,
            human_touchpoint=False,
        )
        for index in range(150)
    )
    return evaluate_mscp_readiness(
        outcomes,
        policy=MscpReadinessPolicy(demotion_drill_passed=True),
    )


def _valid_receipt(
    *,
    reviewer_id: str = "reviewer-alice",
    approver_id: str = "approver-bob",
    audit_failure_count: int = 0,
) -> GovernedReadinessWindowReceipt:
    report = _readiness_report()
    review = IndependentProfileReview(
        review_id="review-101",
        reviewer_id=reviewer_id,
        candidate=_CANDIDATE,
        readiness_digest=readiness_digest(report),
        reviewed_at=_NOW,
        approved=True,
    )
    return GovernedReadinessWindowReceipt(
        candidate=_CANDIDATE,
        readiness_report=report,
        review=review,
        approver_id=approver_id,
        audit_failure_count=audit_failure_count,
    )


def test_default_shadow_mode_preserves_fdai_decision_and_ownership_fields() -> None:
    binding = GovernedMscpCeilingBinding(candidate=_CANDIDATE, registered_at=_NOW)
    assert binding.mode == "shadow"
    assert binding.revision == 1

    decision_input = GovernedCeilingDecisionInput(
        decision_id="dec-shadow-1",
        candidate=_CANDIDATE,
        fdai_decision="execute",
        mscp_ceiling="deny",
        mscp_reason=MscpAuthorityReason.POLICY_DENY,
        risk_tier="medium",
        approval_required=False,
        executor_identity="Thor",
        audit_owner="Saga",
        evaluated_at=_NOW + timedelta(minutes=1),
    )
    result = binding.evaluate(decision_input)

    assert result.profile_mode == "shadow"
    assert result.lifecycle_revision == 1
    assert result.effective_decision == "execute"
    assert result.lowered is False
    assert result.shadow_projected_decision == "deny"
    assert result.shadow_would_lower is True
    assert result.risk_tier == "medium"
    assert result.approval_required is False
    assert result.executor_identity == "Thor"
    assert result.audit_owner == "Saga"
    assert result.audit_fields["safety_profile"] == "mscp-operational-v1"


def test_governed_activation_rejects_self_review_audit_failures_and_incomplete_readiness() -> None:
    with pytest.raises(
        GovernedCeilingBindingError,
        match="distinct reviewer_id and approver_id",
    ):
        _valid_receipt(reviewer_id="same-operator", approver_id="same-operator")

    with pytest.raises(
        GovernedCeilingBindingError,
        match="zero audit failures",
    ):
        _valid_receipt(audit_failure_count=1)

    report = _readiness_report()
    incomplete_report = replace(report, gaps=("sample_count",), ready_for_review=False)
    review = IndependentProfileReview(
        review_id="review-incomplete",
        reviewer_id="reviewer-alice",
        candidate=_CANDIDATE,
        readiness_digest=readiness_digest(incomplete_report),
        reviewed_at=_NOW,
        approved=True,
    )
    with pytest.raises(GovernedCeilingBindingError, match="incomplete or has unresolved gaps"):
        GovernedReadinessWindowReceipt(
            candidate=_CANDIDATE,
            readiness_report=incomplete_report,
            review=review,
            approver_id="approver-bob",
        )


@pytest.mark.parametrize(
    ("fdai_decision", "mscp_ceiling"),
    tuple(
        itertools.product(
            ("execute", "require_approval", "hold", "deny"),
            ("execute", "require_approval", "hold", "deny"),
        )
    ),
)
def test_active_mode_never_raises_authority_across_all_combinations(
    fdai_decision: ControlDecisionLevel,
    mscp_ceiling: ControlDecisionLevel,
) -> None:
    binding = GovernedMscpCeilingBinding(candidate=_CANDIDATE, registered_at=_NOW)
    binding.activate(_valid_receipt(), now=_NOW + timedelta(minutes=1))
    assert binding.mode == "active"
    assert binding.revision == 2

    decision_input = GovernedCeilingDecisionInput(
        decision_id=f"dec-{fdai_decision}-{mscp_ceiling}",
        candidate=_CANDIDATE,
        fdai_decision=fdai_decision,
        mscp_ceiling=mscp_ceiling,
        risk_tier="high",
        approval_required=(fdai_decision == "require_approval"),
        executor_identity="Thor",
        audit_owner="Saga",
        evaluated_at=_NOW + timedelta(minutes=2),
    )
    result = binding.evaluate(decision_input)

    expected_rank = min(_DECISION_RANK[fdai_decision], _DECISION_RANK[mscp_ceiling])
    assert _DECISION_RANK[result.effective_decision] == expected_rank
    assert _DECISION_RANK[result.effective_decision] <= _DECISION_RANK[fdai_decision]
    assert result.lowered is (expected_rank < _DECISION_RANK[fdai_decision])
    if fdai_decision in {"deny", "hold", "require_approval"}:
        assert result.effective_decision != "execute"
    assert result.risk_tier == "high"
    assert result.executor_identity == "Thor"
    assert result.audit_owner == "Saga"


def test_rollback_to_shadow_and_deterministic_replay_by_pinned_revision() -> None:
    binding = GovernedMscpCeilingBinding(candidate=_CANDIDATE, registered_at=_NOW)
    decision_input = GovernedCeilingDecisionInput(
        decision_id="dec-replay-check",
        candidate=_CANDIDATE,
        fdai_decision="execute",
        mscp_ceiling="require_approval",
        mscp_reason=MscpAuthorityReason.HUMAN_REVIEW_REQUIRED,
        risk_tier="medium",
        approval_required=False,
        executor_identity="Thor",
        audit_owner="Saga",
        evaluated_at=_NOW + timedelta(minutes=10),
    )

    rev1_eval = binding.evaluate(decision_input)
    assert rev1_eval.profile_mode == "shadow"
    assert rev1_eval.effective_decision == "execute"
    assert rev1_eval.approval_required is False

    binding.activate(_valid_receipt(), now=_NOW + timedelta(minutes=5))
    rev2_eval = binding.evaluate(decision_input)
    assert rev2_eval.profile_mode == "active"
    assert rev2_eval.effective_decision == "require_approval"
    assert rev2_eval.lowered is True
    assert rev2_eval.approval_required is True

    binding.rollback(
        reason="observer_drift_detected",
        actor="operator-oncall",
        now=_NOW + timedelta(minutes=15),
    )
    assert binding.mode == "shadow"
    assert binding.revision == 3
    rev3_eval = binding.evaluate(decision_input)
    assert rev3_eval.profile_mode == "shadow"
    assert rev3_eval.effective_decision == "execute"
    assert rev3_eval.lowered is False

    replayed_rev1 = binding.replay(decision_input, pinned_lifecycle_revision=1)
    replayed_rev2 = binding.replay(decision_input, pinned_lifecycle_revision=2)
    replayed_rev3 = binding.replay(decision_input, pinned_lifecycle_revision=3)

    assert replayed_rev1 == rev1_eval
    assert replayed_rev2 == rev2_eval
    assert replayed_rev3 == rev3_eval
    assert replayed_rev2.receipt_digest == rev2_eval.receipt_digest

    with pytest.raises(GovernedCeilingBindingError, match="unknown pinned_lifecycle_revision"):
        binding.replay(decision_input, pinned_lifecycle_revision=99)
