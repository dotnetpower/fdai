"""RegressionGate - thresholds + decision invariants."""

from __future__ import annotations

import pytest
from fdai.rule_catalog.pipeline import (
    RegressionDecision,
    RegressionGate,
    RegressionGateConfig,
    RegressionOutcome,
    ScenarioOutcome,
    ShadowEvalReport,
)


def _outcome(
    *,
    scenario_id: str,
    matched: tuple[str, ...] = (),
    expected: tuple[str, ...] = (),
    should_trigger_policy_violation: bool = False,
) -> ScenarioOutcome:
    return ScenarioOutcome(
        scenario_id=scenario_id,
        expected_tier="t0",
        expected_decision="auto" if expected else "abstain",
        actual_tier="t0",
        actual_pipeline_stage="L1_evaluate" if matched else "abstain",
        matched_rule_ids=matched,
        expected_rule_ids=expected,
        expected_should_execute=bool(expected),
        expected_should_trigger_policy_violation=should_trigger_policy_violation,
    )


def _report(*outcomes: ScenarioOutcome, tag: str = "v1") -> ShadowEvalReport:
    return ShadowEvalReport(
        scenario_set_id=tag,
        candidate_rule_ids=("r.x",),
        scenario_count=len(outcomes),
        outcomes=outcomes,
    )


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def test_negative_max_escapes_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_policy_escapes"):
        RegressionGate(config=RegressionGateConfig(max_policy_escapes=-1))


@pytest.mark.parametrize("ratio", [-0.1, 1.01, 2.0])
def test_min_coverage_ratio_out_of_range_is_rejected(ratio: float) -> None:
    with pytest.raises(ValueError, match="min_coverage_ratio"):
        RegressionGate(config=RegressionGateConfig(min_coverage_ratio=ratio))


def test_negative_missing_rules_cap_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_missing_expected_rules"):
        RegressionGate(config=RegressionGateConfig(max_missing_expected_rules=-1))


# ---------------------------------------------------------------------------
# PASS paths
# ---------------------------------------------------------------------------


def test_passes_when_no_escapes_no_missing_and_no_baseline() -> None:
    gate = RegressionGate()
    candidate = _report(_outcome(scenario_id="ok", matched=("r.x",), expected=("r.x",)))
    decision = gate.evaluate(candidate=candidate, baseline=None)
    assert decision.outcome is RegressionOutcome.PASS
    assert decision.reasons == ()


def test_passes_when_baseline_coverage_zero_and_no_escapes() -> None:
    """First-time rollout has an empty baseline; the ratio check is a no-op."""
    gate = RegressionGate()
    candidate = _report(_outcome(scenario_id="ok"))
    baseline = _report()  # 0 scenarios, coverage 0.0
    decision = gate.evaluate(candidate=candidate, baseline=baseline)
    assert decision.outcome is RegressionOutcome.PASS


def test_passes_when_candidate_coverage_meets_floor() -> None:
    gate = RegressionGate(config=RegressionGateConfig(min_coverage_ratio=0.5))
    # baseline: 2/2 matched → coverage 1.0. Candidate: 1/2 matched → 0.5.
    baseline = _report(
        _outcome(scenario_id="b1", matched=("r.x",)),
        _outcome(scenario_id="b2", matched=("r.x",)),
    )
    candidate = _report(
        _outcome(scenario_id="c1", matched=("r.x",)),
        _outcome(scenario_id="c2"),
    )
    decision = gate.evaluate(candidate=candidate, baseline=baseline)
    assert decision.outcome is RegressionOutcome.PASS


# ---------------------------------------------------------------------------
# FAIL paths - each threshold in isolation
# ---------------------------------------------------------------------------


def test_fails_on_any_policy_violation_escape_by_default() -> None:
    gate = RegressionGate()
    candidate = _report(
        _outcome(
            scenario_id="escape",
            matched=(),
            expected=("r.x",),
            should_trigger_policy_violation=True,
        )
    )
    decision = gate.evaluate(candidate=candidate)
    assert decision.outcome is RegressionOutcome.FAIL
    assert any("policy_violation_escapes" in r for r in decision.reasons)


def test_fails_when_expected_rules_are_missing_by_default() -> None:
    gate = RegressionGate()
    candidate = _report(_outcome(scenario_id="miss", matched=(), expected=("r.x",)))
    decision = gate.evaluate(candidate=candidate)
    assert decision.outcome is RegressionOutcome.FAIL
    assert any("missing_expected_rules" in r for r in decision.reasons)


def test_fails_when_candidate_coverage_regresses_below_floor() -> None:
    gate = RegressionGate(config=RegressionGateConfig(min_coverage_ratio=0.9))
    baseline = _report(
        _outcome(scenario_id="b1", matched=("r.x",)),
        _outcome(scenario_id="b2", matched=("r.x",)),
    )
    # 1/2 → 0.5, way below 0.9 * 1.0 = 0.9.
    candidate = _report(
        _outcome(scenario_id="c1", matched=("r.x",)),
        _outcome(scenario_id="c2"),
    )
    decision = gate.evaluate(candidate=candidate, baseline=baseline)
    assert decision.outcome is RegressionOutcome.FAIL
    assert any("coverage" in r for r in decision.reasons)


def test_multiple_reasons_are_all_reported() -> None:
    gate = RegressionGate(config=RegressionGateConfig(min_coverage_ratio=0.9))
    baseline = _report(_outcome(scenario_id="b", matched=("r.x",)))
    candidate = _report(
        _outcome(
            scenario_id="c",
            matched=(),
            expected=("r.x",),
            should_trigger_policy_violation=True,
        )
    )
    decision = gate.evaluate(candidate=candidate, baseline=baseline)
    assert decision.outcome is RegressionOutcome.FAIL
    # Escape + missing rules + coverage regression all cited.
    assert len(decision.reasons) == 3


# ---------------------------------------------------------------------------
# Frozen decision
# ---------------------------------------------------------------------------


def test_regression_decision_is_immutable() -> None:
    gate = RegressionGate()
    decision = gate.evaluate(candidate=_report(_outcome(scenario_id="ok")))
    with pytest.raises((AttributeError, TypeError)):
        decision.outcome = RegressionOutcome.FAIL  # type: ignore[misc]


def test_regression_decision_carries_thresholds_for_audit() -> None:
    gate = RegressionGate()
    baseline = _report(_outcome(scenario_id="b1", matched=("r.x",)))
    candidate = _report(_outcome(scenario_id="c1", matched=("r.x",)))
    decision = gate.evaluate(candidate=candidate, baseline=baseline)
    assert isinstance(decision, RegressionDecision)
    assert decision.candidate_coverage == 1.0
    assert decision.baseline_coverage == 1.0
    assert decision.policy_violation_escapes == 0
    assert decision.missing_expected_rules == 0
