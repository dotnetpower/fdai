"""Tests for ARB-4 independent multi-effect closure and Vidar recovery coordination."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.architecture_review import (
    ArchitectureReviewActionRunLink,
    ArchitectureReviewEffectObservation,
    ArchitectureReviewExpectedEffect,
    evaluate_architecture_review_effect_closure,
)

_NOW = datetime(2026, 8, 29, 4, 0, tzinfo=UTC)
_DIGEST_1 = "sha256:" + "1" * 64
_DIGEST_2 = "sha256:" + "2" * 64
_DIGEST_3 = "sha256:" + "3" * 64


def _link() -> ArchitectureReviewActionRunLink:
    return ArchitectureReviewActionRunLink(
        review_case_id="arb-review:change-1",
        change_id="change-1",
        decision_case_id="decision-case-1",
        impact_envelope_id="impact-envelope-1",
        action_run_id="action-run-1",
        selected_option_id="option-right-size",
        action_type="remediate.right-size-compute@1.0.0",
        executor_principal="Thor",
        idempotency_key="arb4-idempotency-1",
        target_lock_ref="lock:resource-1",
        stop_condition_ref="stop:error-budget-burn",
        rollback_ref="rollback:restore-sku",
        executed_at=_NOW,
        expected_effects=(
            ArchitectureReviewExpectedEffect(
                effect_id="eff-latency-p95",
                metric="http_latency_p95_ms",
                target_ref="resource-1",
                expected_min=0.0,
                expected_max=250.0,
                window_seconds=300,
            ),
            ArchitectureReviewExpectedEffect(
                effect_id="eff-availability",
                metric="availability_ratio",
                target_ref="resource-1",
                expected_min=0.999,
                expected_max=1.0,
                window_seconds=300,
            ),
        ),
        mode="shadow",
    )


def test_independent_multi_effect_closure_succeeds_without_granting_authority() -> None:
    link = _link()
    observations = (
        ArchitectureReviewEffectObservation(
            observation_id="obs-1",
            effect_id="eff-latency-p95",
            action_run_id="action-run-1",
            observer_principal="Heimdall",
            observed_value=140.0,
            observed_at=_NOW + timedelta(seconds=30),
            evidence_digest=_DIGEST_1,
        ),
        ArchitectureReviewEffectObservation(
            observation_id="obs-2",
            effect_id="eff-availability",
            action_run_id="action-run-1",
            observer_principal="Heimdall",
            observed_value=0.9995,
            observed_at=_NOW + timedelta(seconds=60),
            evidence_digest=_DIGEST_2,
        ),
    )

    result = evaluate_architecture_review_effect_closure(link, observations)
    reordered = evaluate_architecture_review_effect_closure(link, tuple(reversed(observations)))

    assert result == reordered
    assert result.status == "closed_conformant"
    assert result.review_status == "conformant"
    assert result.closed_effect_ids == ("eff-latency-p95", "eff-availability")
    assert result.pending_effect_ids == ()
    assert result.failed_effect_ids == ()
    assert result.reason_codes == ()
    assert result.recovery_request is None
    assert result.arb_execution_authority is False
    assert result.closure_digest.startswith("sha256:")


def test_missing_incomplete_or_self_scored_observations_remain_pending() -> None:
    link = _link()
    self_scored_and_incomplete = (
        ArchitectureReviewEffectObservation(
            observation_id="obs-thor-self-score",
            effect_id="eff-latency-p95",
            action_run_id="action-run-1",
            observer_principal="Thor",
            observed_value=100.0,
            observed_at=_NOW + timedelta(seconds=10),
            evidence_digest=_DIGEST_1,
        ),
        ArchitectureReviewEffectObservation(
            observation_id="obs-incomplete",
            effect_id="eff-availability",
            action_run_id="action-run-1",
            observer_principal="Heimdall",
            observed_value=None,
            observed_at=_NOW + timedelta(seconds=20),
            evidence_digest=_DIGEST_2,
            complete=False,
        ),
    )

    result = evaluate_architecture_review_effect_closure(link, self_scored_and_incomplete)

    assert result.status == "pending_observation"
    assert result.review_status == "pending"
    assert result.closed_effect_ids == ()
    assert result.pending_effect_ids == ("eff-latency-p95", "eff-availability")
    assert result.failed_effect_ids == ()
    assert "self_scored_or_unauthorized_observer:Thor" in result.reason_codes
    assert "missing_observation:eff-latency-p95" in result.reason_codes
    assert "incomplete_observation:eff-availability" in result.reason_codes
    assert result.recovery_request is None
    assert result.arb_execution_authority is False


def test_out_of_bounds_or_stop_condition_triggers_vidar_recovery_and_reopens_review() -> None:
    link = _link()
    failure_fixture = (
        ArchitectureReviewEffectObservation(
            observation_id="obs-latency-breach",
            effect_id="eff-latency-p95",
            action_run_id="action-run-1",
            observer_principal="Heimdall",
            observed_value=420.0,
            observed_at=_NOW + timedelta(seconds=45),
            evidence_digest=_DIGEST_1,
            stop_condition_triggered=True,
        ),
        ArchitectureReviewEffectObservation(
            observation_id="obs-slo-violation",
            effect_id="eff-availability",
            action_run_id="action-run-1",
            observer_principal="Heimdall",
            observed_value=0.985,
            observed_at=_NOW + timedelta(seconds=90),
            evidence_digest=_DIGEST_3,
            protected_objective_violated=True,
        ),
    )

    result = evaluate_architecture_review_effect_closure(link, failure_fixture)

    assert result.status == "recovery_required"
    assert result.review_status == "reopened"
    assert result.closed_effect_ids == ()
    assert result.failed_effect_ids == ("eff-latency-p95", "eff-availability")
    assert "effect_out_of_bounds:eff-latency-p95" in result.reason_codes
    assert "stop_condition_triggered:eff-latency-p95" in result.reason_codes
    assert "protected_objective_violated:eff-availability" in result.reason_codes
    assert result.recovery_request is not None
    assert result.recovery_request.target_agent == "Vidar"
    assert result.recovery_request.impact_envelope_id == "impact-envelope-1"
    assert result.recovery_request.rollback_ref == "rollback:restore-sku"
    assert result.recovery_request.stop_condition_ref == "stop:error-budget-burn"
    assert result.recovery_request.failed_effect_ids == ("eff-latency-p95", "eff-availability")
    assert result.recovery_request.requested_at == _NOW + timedelta(seconds=90)
    assert result.recovery_request.arb_execution_authority is False


def test_executor_cannot_be_configured_as_allowed_observer() -> None:
    link = _link()
    with pytest.raises(ValueError, match="executor_principal MUST NOT be an allowed"):
        evaluate_architecture_review_effect_closure(
            link,
            (),
            allowed_observer_principals=frozenset({"Heimdall", "Thor"}),
        )


def test_observations_outside_declared_window_remain_pending() -> None:
    link = _link()
    out_of_window = (
        ArchitectureReviewEffectObservation(
            observation_id="obs-before-execution",
            effect_id="eff-latency-p95",
            action_run_id="action-run-1",
            observer_principal="Heimdall",
            observed_value=120.0,
            observed_at=_NOW - timedelta(seconds=1),
            evidence_digest=_DIGEST_1,
        ),
        ArchitectureReviewEffectObservation(
            observation_id="obs-after-window",
            effect_id="eff-availability",
            action_run_id="action-run-1",
            observer_principal="Heimdall",
            observed_value=0.9999,
            observed_at=_NOW + timedelta(seconds=301),
            evidence_digest=_DIGEST_2,
        ),
    )

    result = evaluate_architecture_review_effect_closure(link, out_of_window)

    assert result.status == "pending_observation"
    assert result.review_status == "pending"
    assert result.closed_effect_ids == ()
    assert result.pending_effect_ids == ("eff-latency-p95", "eff-availability")
    assert "observation_outside_window:eff-latency-p95" in result.reason_codes
    assert "observation_outside_window:eff-availability" in result.reason_codes
    assert result.recovery_request is None
