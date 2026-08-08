"""Baseline-vs-treatment regression detector.

Phase 4 § Continuous Measurement and Improvement. Re-runs the frozen,
versioned scenario set periodically and detects **regressions**:

- a **guard-metric breach** (rollback rate rises, false-positive/negative
  rises, or the policy-violation-escapes count > 0), OR
- a **success-metric drop beyond the reported confidence interval**.

Detection is deterministic; the caller wires the outcome into an
automatic-demotion action on the affected ActionType via the
:class:`~fdai.core.risk_gate.gate.ActionPromotionRegistry`
already delivered in P2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class GuardKind(StrEnum):
    """Kinds of guard metrics tracked per measurement window."""

    POLICY_VIOLATION_ESCAPE = "policy_violation_escape"
    """The one true zero-tolerance metric. Any positive value is a breach."""

    ROLLBACK_RATE = "rollback_rate"
    """Share of executed actions that later rolled back."""

    FALSE_POSITIVE_RATE = "false_positive_rate"
    FALSE_NEGATIVE_RATE = "false_negative_rate"


class RegressionOutcome(StrEnum):
    PASS = "pass"  # noqa: S105 - enum value, not a secret
    """No regression; capability may stay in enforce mode."""

    GUARD_BREACH = "guard_breach"
    """A guard metric moved past its ceiling → demote to shadow."""

    SUCCESS_DROP = "success_drop"
    """Success metric fell past its lower CI bound → demote to shadow."""


@dataclass(frozen=True, slots=True)
class GuardMetric:
    """A guard metric with a ceiling and its observed value."""

    kind: GuardKind
    ceiling: float
    """Values <= ceiling are OK. Policy-violation-escape uses ceiling=0."""

    observed: float

    def is_breach(self) -> bool:
        return self.observed > self.ceiling


@dataclass(frozen=True, slots=True)
class SuccessMetric:
    """A success metric with a lower CI bound and its observed value."""

    name: str
    lower_ci: float
    """Observed values below this are a regression."""

    observed: float

    def is_drop(self) -> bool:
        return self.observed < self.lower_ci


@dataclass(frozen=True, slots=True)
class MeasurementSample:
    """One measurement over the fixed scenario set + window."""

    action_type_id: str
    scenario_set_version: str
    guard_metrics: tuple[GuardMetric, ...] = field(default_factory=tuple)
    success_metrics: tuple[SuccessMetric, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RegressionDecision:
    """Frozen record of one regression evaluation."""

    action_type_id: str
    scenario_set_version: str
    outcome: RegressionOutcome
    reasons: tuple[str, ...] = field(default_factory=tuple)


class RegressionDetector:
    """Pure evaluator of :class:`MeasurementSample` → :class:`RegressionDecision`.

    Guard breaches always dominate success drops: a policy-violation
    escape MUST demote even when success metrics moved up. Emitting
    both in the reasons keeps the audit trail useful.
    """

    def evaluate(self, sample: MeasurementSample) -> RegressionDecision:
        reasons: list[str] = []
        breach = False
        drop = False

        for guard in sample.guard_metrics:
            if guard.is_breach():
                breach = True
                reasons.append(
                    f"guard_breach:{guard.kind}:observed={guard.observed}>ceiling={guard.ceiling}"
                )

        for metric in sample.success_metrics:
            if metric.is_drop():
                drop = True
                reasons.append(
                    f"success_drop:{metric.name}"
                    f":observed={metric.observed}<lower_ci={metric.lower_ci}"
                )

        outcome: RegressionOutcome
        if breach:
            outcome = RegressionOutcome.GUARD_BREACH
        elif drop:
            outcome = RegressionOutcome.SUCCESS_DROP
        else:
            outcome = RegressionOutcome.PASS

        return RegressionDecision(
            action_type_id=sample.action_type_id,
            scenario_set_version=sample.scenario_set_version,
            outcome=outcome,
            reasons=tuple(reasons),
        )


__all__ = [
    "GuardKind",
    "GuardMetric",
    "MeasurementSample",
    "RegressionDecision",
    "RegressionDetector",
    "RegressionOutcome",
    "SuccessMetric",
]
