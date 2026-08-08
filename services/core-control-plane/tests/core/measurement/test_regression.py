"""Regression detector outcomes."""

from __future__ import annotations

from fdai.core.measurement.regression import (
    GuardKind,
    GuardMetric,
    MeasurementSample,
    RegressionDetector,
    RegressionOutcome,
    SuccessMetric,
)


def _sample(
    *,
    guards: tuple[GuardMetric, ...] = (),
    successes: tuple[SuccessMetric, ...] = (),
) -> MeasurementSample:
    return MeasurementSample(
        action_type_id="remediate.tag-add",
        scenario_set_version="v2026.07",
        guard_metrics=guards,
        success_metrics=successes,
    )


def test_pass_when_no_guard_or_drop() -> None:
    detector = RegressionDetector()
    decision = detector.evaluate(
        _sample(
            guards=(GuardMetric(GuardKind.ROLLBACK_RATE, ceiling=0.05, observed=0.01),),
            successes=(SuccessMetric(name="auto_share", lower_ci=0.4, observed=0.55),),
        )
    )
    assert decision.outcome is RegressionOutcome.PASS
    assert decision.reasons == ()


def test_policy_violation_escape_dominates_success_gain() -> None:
    detector = RegressionDetector()
    decision = detector.evaluate(
        _sample(
            guards=(
                GuardMetric(GuardKind.POLICY_VIOLATION_ESCAPE, ceiling=0.0, observed=1.0),
                GuardMetric(GuardKind.ROLLBACK_RATE, ceiling=0.05, observed=0.01),
            ),
            successes=(SuccessMetric(name="auto_share", lower_ci=0.4, observed=0.9),),
        )
    )
    assert decision.outcome is RegressionOutcome.GUARD_BREACH
    # Only the breaching guard shows up; the passing one and the
    # non-dropped success do not add noise to the audit trail.
    assert any("policy_violation_escape" in r for r in decision.reasons)
    assert not any("rollback_rate" in r for r in decision.reasons)
    assert not any("success_drop" in r for r in decision.reasons)


def test_success_drop_without_guard_breach() -> None:
    detector = RegressionDetector()
    decision = detector.evaluate(
        _sample(
            guards=(GuardMetric(GuardKind.ROLLBACK_RATE, ceiling=0.05, observed=0.01),),
            successes=(SuccessMetric(name="auto_share", lower_ci=0.5, observed=0.35),),
        )
    )
    assert decision.outcome is RegressionOutcome.SUCCESS_DROP
    assert any("success_drop:auto_share" in r for r in decision.reasons)


def test_guard_and_drop_reported_together_but_guard_wins() -> None:
    detector = RegressionDetector()
    decision = detector.evaluate(
        _sample(
            guards=(GuardMetric(GuardKind.FALSE_POSITIVE_RATE, ceiling=0.1, observed=0.2),),
            successes=(SuccessMetric(name="auto_share", lower_ci=0.5, observed=0.3),),
        )
    )
    # Guard wins the outcome, but the audit reasons carry BOTH signals
    # so the audit trail is complete.
    assert decision.outcome is RegressionOutcome.GUARD_BREACH
    assert any("guard_breach" in r for r in decision.reasons)
    assert any("success_drop" in r for r in decision.reasons)


def test_ceiling_boundary_is_not_a_breach() -> None:
    detector = RegressionDetector()
    decision = detector.evaluate(
        _sample(guards=(GuardMetric(GuardKind.ROLLBACK_RATE, ceiling=0.05, observed=0.05),))
    )
    assert decision.outcome is RegressionOutcome.PASS


def test_lower_ci_boundary_is_not_a_drop() -> None:
    detector = RegressionDetector()
    decision = detector.evaluate(
        _sample(successes=(SuccessMetric(name="auto_share", lower_ci=0.4, observed=0.4),))
    )
    assert decision.outcome is RegressionOutcome.PASS
