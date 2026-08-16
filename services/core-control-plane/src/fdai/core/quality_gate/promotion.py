"""Deterministic shadow-to-enforce decision for the rubric hallucination gate.

The rubric gate ships shadow-first
(:class:`~fdai.core.quality_gate.gate.QualityGateConfig.rubric_shadow` defaults
to ``True``). This module owns the *decision* half of that transition: given a
baseline-versus-treatment measurement on a frozen labeled scenario set, it
reports whether the evidence supports enforcing, holding, or demoting.

Design invariants
-----------------
- **Deterministic, never a model judge.** The recommendation is a pure function
  of recorded counts and rates. A judge model produces the measured signal; it
  can never grade its own promotion.
- **Evidence, not application.** The evaluator returns a recommendation. Nothing
  here flips ``rubric_shadow``; applying it stays an explicit, separately
  reviewed configuration change, exactly as
  ``coding-conventions.instructions.md`` requires of any shadow promotion.
- **Fail closed.** A missing measurement, a scenario set below the labeled-case
  floor, or an unmeasured baseline arm holds the current posture. Absence of
  evidence never reads as evidence of safety.
- **An escape can never promote.** A policy-violation escape in the treatment
  arm blocks promotion regardless of catch rate, latency, or cost, and demotes
  from enforce once the scenario set is trustworthy enough to be believed.
- **Never a promotion from enforce.** From enforce mode the only outcomes are
  hold and demote, so the evaluator cannot raise autonomy twice.

See also
--------
- ``docs/roadmap/decisioning/hallucination-rubric-gate.md``
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

_MAX_SCENARIO_SET_VERSION = 128


class RubricPromotionOutcome(StrEnum):
    """The deterministic recommendation for the rubric gate's mode."""

    PROMOTE = "promote"
    HOLD = "hold"
    DEMOTE = "demote"


class RubricPromotionReason(StrEnum):
    """Why the recommendation was reached; reported in declaration order."""

    NO_MEASUREMENT = "no_measurement"
    BASELINE_ARM_MISSING = "baseline_arm_missing"
    INSUFFICIENT_LABELED_CASES = "insufficient_labeled_cases"
    POLICY_VIOLATION_ESCAPE = "policy_violation_escape"
    CATCH_RATE_BELOW_TARGET = "catch_rate_below_target"
    FALSE_POSITIVE_RATE_ABOVE_CEILING = "false_positive_rate_above_ceiling"
    ADDED_LATENCY_ABOVE_CEILING = "added_latency_above_ceiling"
    ADDED_COST_ABOVE_CEILING = "added_cost_above_ceiling"
    GATE_MET = "gate_met"


def _require_rate(value: float, field: str) -> float:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"rubric promotion {field} MUST be finite and in [0, 1]")
    return value


def _require_finite(value: float, field: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"rubric promotion {field} MUST be finite")
    return value


@dataclass(frozen=True, slots=True)
class RubricPromotionThresholds:
    """Configuration-owned promotion gate; a model never sets its own bar."""

    minimum_catch_rate: float
    maximum_false_positive_rate: float
    maximum_added_latency_ms: float
    maximum_added_token_cost: float
    minimum_labeled_cases: int

    def __post_init__(self) -> None:
        _require_rate(self.minimum_catch_rate, "minimum_catch_rate")
        _require_rate(self.maximum_false_positive_rate, "maximum_false_positive_rate")
        if not math.isfinite(self.maximum_added_latency_ms) or self.maximum_added_latency_ms < 0:
            raise ValueError("rubric promotion maximum_added_latency_ms MUST be finite and >= 0")
        if not math.isfinite(self.maximum_added_token_cost) or self.maximum_added_token_cost < 0:
            raise ValueError("rubric promotion maximum_added_token_cost MUST be finite and >= 0")
        if self.minimum_labeled_cases < 1:
            raise ValueError("rubric promotion minimum_labeled_cases MUST be at least 1")


@dataclass(frozen=True, slots=True)
class RubricPromotionMeasurement:
    """One paired baseline-versus-treatment run on a frozen scenario set.

    ``added_latency_ms`` and ``added_token_cost`` are treatment minus baseline,
    so an improvement is negative. ``baseline_measured`` is explicit because a
    treatment-only run cannot support any promotion claim.
    """

    scenario_set_version: str
    labeled_cases: int
    baseline_measured: bool
    catch_rate: float
    false_positive_rate: float
    added_latency_ms: float
    added_token_cost: float
    policy_violation_escapes: int

    def __post_init__(self) -> None:
        if (
            not self.scenario_set_version.strip()
            or len(self.scenario_set_version) > _MAX_SCENARIO_SET_VERSION
        ):
            raise ValueError(
                f"rubric promotion scenario_set_version MUST contain "
                f"1-{_MAX_SCENARIO_SET_VERSION} characters"
            )
        if self.labeled_cases < 0:
            raise ValueError("rubric promotion labeled_cases MUST NOT be negative")
        if self.policy_violation_escapes < 0:
            raise ValueError("rubric promotion policy_violation_escapes MUST NOT be negative")
        _require_rate(self.catch_rate, "catch_rate")
        _require_rate(self.false_positive_rate, "false_positive_rate")
        _require_finite(self.added_latency_ms, "added_latency_ms")
        _require_finite(self.added_token_cost, "added_token_cost")


@dataclass(frozen=True, slots=True)
class RubricPromotionDecision:
    """A recommendation plus every reason that produced it."""

    outcome: RubricPromotionOutcome
    reasons: tuple[RubricPromotionReason, ...]
    scenario_set_version: str | None


def evaluate_rubric_promotion(
    measurement: RubricPromotionMeasurement | None,
    *,
    thresholds: RubricPromotionThresholds,
    shadow: bool,
) -> RubricPromotionDecision:
    """Recommend the rubric gate's next mode from one measured scenario set.

    Args:
        measurement: The paired frozen-scenario-set result, or ``None`` when no
            measurement exists.
        thresholds: The configuration-owned promotion gate.
        shadow: Whether the gate is currently shadow-only. From enforce mode the
            evaluator can only hold or demote.

    Returns:
        The recommendation and its reasons. Applying it remains an explicit,
        separately reviewed configuration change. Demotion never grants
        execution authority: the rubric is subtractive, so removing it returns
        the gate to the deterministic verifier's authority rather than raising
        it. Untrustworthy evidence therefore holds the current posture, and
        only a measured regression on a sufficient scenario set demotes.
    """

    if measurement is None:
        return RubricPromotionDecision(
            outcome=RubricPromotionOutcome.HOLD,
            reasons=(RubricPromotionReason.NO_MEASUREMENT,),
            scenario_set_version=None,
        )

    blocking: list[RubricPromotionReason] = []
    unmeasured: list[RubricPromotionReason] = []
    if not measurement.baseline_measured:
        unmeasured.append(RubricPromotionReason.BASELINE_ARM_MISSING)
    if measurement.labeled_cases < thresholds.minimum_labeled_cases:
        unmeasured.append(RubricPromotionReason.INSUFFICIENT_LABELED_CASES)
    if measurement.policy_violation_escapes > 0:
        blocking.append(RubricPromotionReason.POLICY_VIOLATION_ESCAPE)
    if measurement.catch_rate < thresholds.minimum_catch_rate:
        blocking.append(RubricPromotionReason.CATCH_RATE_BELOW_TARGET)
    if measurement.false_positive_rate > thresholds.maximum_false_positive_rate:
        blocking.append(RubricPromotionReason.FALSE_POSITIVE_RATE_ABOVE_CEILING)
    if measurement.added_latency_ms > thresholds.maximum_added_latency_ms:
        blocking.append(RubricPromotionReason.ADDED_LATENCY_ABOVE_CEILING)
    if measurement.added_token_cost > thresholds.maximum_added_token_cost:
        blocking.append(RubricPromotionReason.ADDED_COST_ABOVE_CEILING)

    reasons = tuple(
        reason for reason in RubricPromotionReason if reason in set(unmeasured + blocking)
    )
    if not reasons:
        outcome = RubricPromotionOutcome.PROMOTE if shadow else RubricPromotionOutcome.HOLD
        return RubricPromotionDecision(
            outcome=outcome,
            reasons=(RubricPromotionReason.GATE_MET,),
            scenario_set_version=measurement.scenario_set_version,
        )
    if shadow or unmeasured:
        outcome = RubricPromotionOutcome.HOLD
    else:
        outcome = RubricPromotionOutcome.DEMOTE
    return RubricPromotionDecision(
        outcome=outcome,
        reasons=reasons,
        scenario_set_version=measurement.scenario_set_version,
    )


__all__ = [
    "RubricPromotionDecision",
    "RubricPromotionMeasurement",
    "RubricPromotionOutcome",
    "RubricPromotionReason",
    "RubricPromotionThresholds",
    "evaluate_rubric_promotion",
]
