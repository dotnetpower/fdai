"""Deterministic rubric shadow-to-enforce promotion decision tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.core.quality_gate.promotion import (
    RubricPromotionMeasurement,
    RubricPromotionOutcome,
    RubricPromotionReason,
    RubricPromotionThresholds,
    evaluate_rubric_promotion,
)

_THRESHOLDS = RubricPromotionThresholds(
    minimum_catch_rate=0.90,
    maximum_false_positive_rate=0.05,
    maximum_added_latency_ms=800.0,
    maximum_added_token_cost=1500.0,
    minimum_labeled_cases=200,
)


def _measurement(**overrides: object) -> RubricPromotionMeasurement:
    base = RubricPromotionMeasurement(
        scenario_set_version="rubric-scenarios-v1",
        labeled_cases=200,
        baseline_measured=True,
        catch_rate=0.92,
        false_positive_rate=0.03,
        added_latency_ms=400.0,
        added_token_cost=900.0,
        policy_violation_escapes=0,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_missing_measurement_holds_shadow() -> None:
    decision = evaluate_rubric_promotion(None, thresholds=_THRESHOLDS, shadow=True)

    assert decision.outcome is RubricPromotionOutcome.HOLD
    assert decision.reasons == (RubricPromotionReason.NO_MEASUREMENT,)
    assert decision.scenario_set_version is None


def test_missing_measurement_never_demotes_enforce() -> None:
    decision = evaluate_rubric_promotion(None, thresholds=_THRESHOLDS, shadow=False)

    assert decision.outcome is RubricPromotionOutcome.HOLD


def test_met_gate_recommends_promotion_from_shadow() -> None:
    decision = evaluate_rubric_promotion(_measurement(), thresholds=_THRESHOLDS, shadow=True)

    assert decision.outcome is RubricPromotionOutcome.PROMOTE
    assert decision.reasons == (RubricPromotionReason.GATE_MET,)
    assert decision.scenario_set_version == "rubric-scenarios-v1"


def test_met_gate_from_enforce_holds_instead_of_promoting_twice() -> None:
    decision = evaluate_rubric_promotion(_measurement(), thresholds=_THRESHOLDS, shadow=False)

    assert decision.outcome is RubricPromotionOutcome.HOLD
    assert decision.reasons == (RubricPromotionReason.GATE_MET,)


def test_threshold_boundaries_are_inclusive() -> None:
    decision = evaluate_rubric_promotion(
        _measurement(
            catch_rate=0.90,
            false_positive_rate=0.05,
            added_latency_ms=800.0,
            added_token_cost=1500.0,
        ),
        thresholds=_THRESHOLDS,
        shadow=True,
    )

    assert decision.outcome is RubricPromotionOutcome.PROMOTE


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"policy_violation_escapes": 1}, RubricPromotionReason.POLICY_VIOLATION_ESCAPE),
        ({"catch_rate": 0.89}, RubricPromotionReason.CATCH_RATE_BELOW_TARGET),
        (
            {"false_positive_rate": 0.06},
            RubricPromotionReason.FALSE_POSITIVE_RATE_ABOVE_CEILING,
        ),
        ({"added_latency_ms": 801.0}, RubricPromotionReason.ADDED_LATENCY_ABOVE_CEILING),
        (
            {"added_token_cost": 1501.0},
            RubricPromotionReason.ADDED_COST_ABOVE_CEILING,
        ),
    ],
)
def test_failed_gate_holds_shadow_and_demotes_enforce(
    overrides: dict[str, object], reason: RubricPromotionReason
) -> None:
    measurement = _measurement(**overrides)

    held = evaluate_rubric_promotion(measurement, thresholds=_THRESHOLDS, shadow=True)
    demoted = evaluate_rubric_promotion(measurement, thresholds=_THRESHOLDS, shadow=False)

    assert held.outcome is RubricPromotionOutcome.HOLD
    assert demoted.outcome is RubricPromotionOutcome.DEMOTE
    assert held.reasons == demoted.reasons == (reason,)


def test_one_escape_blocks_an_otherwise_perfect_run() -> None:
    decision = evaluate_rubric_promotion(
        _measurement(catch_rate=1.0, false_positive_rate=0.0, policy_violation_escapes=1),
        thresholds=_THRESHOLDS,
        shadow=True,
    )

    assert decision.outcome is RubricPromotionOutcome.HOLD
    assert decision.reasons == (RubricPromotionReason.POLICY_VIOLATION_ESCAPE,)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"baseline_measured": False}, RubricPromotionReason.BASELINE_ARM_MISSING),
        ({"labeled_cases": 199}, RubricPromotionReason.INSUFFICIENT_LABELED_CASES),
    ],
)
def test_untrustworthy_evidence_holds_both_postures(
    overrides: dict[str, object], reason: RubricPromotionReason
) -> None:
    measurement = _measurement(**overrides)

    held = evaluate_rubric_promotion(measurement, thresholds=_THRESHOLDS, shadow=True)
    kept = evaluate_rubric_promotion(measurement, thresholds=_THRESHOLDS, shadow=False)

    assert held.outcome is RubricPromotionOutcome.HOLD
    assert kept.outcome is RubricPromotionOutcome.HOLD
    assert held.reasons == kept.reasons == (reason,)


def test_regression_on_an_insufficient_scenario_set_holds_enforce() -> None:
    decision = evaluate_rubric_promotion(
        _measurement(labeled_cases=10, catch_rate=0.10),
        thresholds=_THRESHOLDS,
        shadow=False,
    )

    assert decision.outcome is RubricPromotionOutcome.HOLD
    assert decision.reasons == (
        RubricPromotionReason.INSUFFICIENT_LABELED_CASES,
        RubricPromotionReason.CATCH_RATE_BELOW_TARGET,
    )


def test_every_failure_is_reported_in_declaration_order() -> None:
    decision = evaluate_rubric_promotion(
        _measurement(
            policy_violation_escapes=2,
            catch_rate=0.10,
            false_positive_rate=1.0,
            added_latency_ms=5000.0,
            added_token_cost=9000.0,
        ),
        thresholds=_THRESHOLDS,
        shadow=True,
    )

    assert decision.reasons == (
        RubricPromotionReason.POLICY_VIOLATION_ESCAPE,
        RubricPromotionReason.CATCH_RATE_BELOW_TARGET,
        RubricPromotionReason.FALSE_POSITIVE_RATE_ABOVE_CEILING,
        RubricPromotionReason.ADDED_LATENCY_ABOVE_CEILING,
        RubricPromotionReason.ADDED_COST_ABOVE_CEILING,
    )


def test_improved_latency_and_cost_do_not_block_promotion() -> None:
    decision = evaluate_rubric_promotion(
        _measurement(added_latency_ms=-50.0, added_token_cost=-10.0),
        thresholds=_THRESHOLDS,
        shadow=True,
    )

    assert decision.outcome is RubricPromotionOutcome.PROMOTE


@pytest.mark.parametrize(
    "overrides",
    [
        {"scenario_set_version": "  "},
        {"scenario_set_version": "v" * 129},
        {"labeled_cases": -1},
        {"policy_violation_escapes": -1},
        {"catch_rate": 1.5},
        {"false_positive_rate": -0.1},
        {"added_latency_ms": float("nan")},
        {"added_token_cost": float("inf")},
    ],
)
def test_invalid_measurements_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _measurement(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"minimum_catch_rate": 1.1},
        {"maximum_false_positive_rate": -0.1},
        {"maximum_added_latency_ms": -1.0},
        {"maximum_added_token_cost": float("nan")},
        {"minimum_labeled_cases": 0},
    ],
)
def test_invalid_thresholds_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(_THRESHOLDS, **overrides)  # type: ignore[arg-type]
