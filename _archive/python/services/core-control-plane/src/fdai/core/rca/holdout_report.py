"""Disjoint calibration and holdout evaluation report with Wilson 95% intervals.

Wraps :func:`~fdai.core.rca.evaluation.evaluate_causal_quality` so a calibration cohort and a
strictly disjoint holdout cohort are evaluated with explicit 95% Wilson confidence intervals
for root-cause accuracy, cause recall, correct abstention rate, and wrong-action (unsupported
cause claim) rate. Offline evaluation only; grants no deployment qualification or execution
authority.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Final

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.rca.evaluation import (
    CausalEvaluationCase,
    CausalEvaluationDisposition,
    CausalEvaluationReceipt,
    CausalEvaluationResult,
    evaluate_causal_quality,
)

_Z_95: Final[float] = 1.959963984540054
_HOLD_DISPOSITIONS: Final = frozenset(
    {CausalEvaluationDisposition.UNRESOLVED, CausalEvaluationDisposition.UNAVAILABLE}
)


@dataclass(frozen=True, slots=True)
class RateInterval:
    """Point rate and 95% Wilson score interval in [0.0, 1.0]."""

    numerator: int
    denominator: int
    rate: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True, slots=True)
class CohortIntervalSummary:
    """Interval-bounded causal quality metrics for one cohort."""

    receipt: CausalEvaluationReceipt
    root_cause_accuracy: RateInterval
    cause_recall: RateInterval
    correct_abstention_rate: RateInterval
    wrong_action_rate: RateInterval


@dataclass(frozen=True, slots=True)
class CausalHoldoutEvaluationReport:
    """Replay-stable report across disjoint calibration and holdout cohorts."""

    calibration: CohortIntervalSummary
    holdout: CohortIntervalSummary
    report_digest: str
    deployed_qualification: bool = False
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.deployed_qualification) is not bool
            or self.deployed_qualification
            or type(self.execution_authority) is not bool
            or self.execution_authority
        ):
            raise ValueError(
                "CausalHoldoutEvaluationReport MUST NOT claim qualification or authority"
            )


def wilson_interval(numerator: int, denominator: int) -> RateInterval:
    """Compute the 95% Wilson score interval for a binomial proportion."""

    if denominator < 0 or numerator < 0 or numerator > denominator:
        raise ValueError("wilson_interval requires 0 <= numerator <= denominator")
    if denominator == 0:
        return RateInterval(numerator=0, denominator=0, rate=0.0, ci_low=0.0, ci_high=0.0)
    n = float(denominator)
    p = numerator / n
    z2 = _Z_95 * _Z_95
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = (_Z_95 * math.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * n * n)))) / denom
    return RateInterval(
        numerator=numerator,
        denominator=denominator,
        rate=round(p, 6),
        ci_low=round(max(0.0, center - half), 6),
        ci_high=round(min(1.0, center + half), 6),
    )


def summarize_cohort_intervals(receipt: CausalEvaluationReceipt) -> CohortIntervalSummary:
    """Derive 95% Wilson intervals for accuracy, recall, abstention, and wrong-action rate."""

    metrics = receipt.metrics
    expected_holds = sum(
        1 for case in receipt.cases if case.expected_disposition in _HOLD_DISPOSITIONS
    )
    return CohortIntervalSummary(
        receipt=receipt,
        root_cause_accuracy=wilson_interval(metrics.correct_cases, metrics.denominator),
        cause_recall=wilson_interval(metrics.correct_cause_claims, metrics.expected_cause_claims),
        correct_abstention_rate=wilson_interval(metrics.justified_holds, expected_holds),
        wrong_action_rate=wilson_interval(metrics.unsupported_cause_claims, metrics.denominator),
    )


def evaluate_disjoint_causal_holdout(
    *,
    calibration_cases: tuple[CausalEvaluationCase, ...],
    calibration_results: tuple[CausalEvaluationResult, ...],
    holdout_cases: tuple[CausalEvaluationCase, ...],
    holdout_results: tuple[CausalEvaluationResult, ...],
    runner_id: str,
    runner_source_revision: str,
    runner_method: str,
) -> CausalHoldoutEvaluationReport:
    """Evaluate calibration and holdout cohorts after verifying disjoint case identities."""

    cal_ids = {case.case_id for case in calibration_cases}
    hold_ids = {case.case_id for case in holdout_cases}
    overlap = sorted(cal_ids & hold_ids)
    if overlap:
        raise ValueError(f"calibration and holdout cohorts MUST be disjoint; overlap: {overlap}")
    cal_receipt = evaluate_causal_quality(
        cases=calibration_cases,
        results=calibration_results,
        runner_id=runner_id,
        runner_source_revision=runner_source_revision,
        runner_method=runner_method,
    )
    hold_receipt = evaluate_causal_quality(
        cases=holdout_cases,
        results=holdout_results,
        runner_id=runner_id,
        runner_source_revision=runner_source_revision,
        runner_method=runner_method,
    )
    cal_summary = summarize_cohort_intervals(cal_receipt)
    hold_summary = summarize_cohort_intervals(hold_receipt)
    digest = content_digest(
        {
            "calibration_receipt_digest": cal_receipt.receipt_digest,
            "holdout_receipt_digest": hold_receipt.receipt_digest,
            "calibration_accuracy": asdict(cal_summary.root_cause_accuracy),
            "holdout_accuracy": asdict(hold_summary.root_cause_accuracy),
            "holdout_abstention": asdict(hold_summary.correct_abstention_rate),
            "holdout_wrong_action": asdict(hold_summary.wrong_action_rate),
        }
    )
    return CausalHoldoutEvaluationReport(
        calibration=cal_summary,
        holdout=hold_summary,
        report_digest=digest,
    )


__all__ = [
    "CausalHoldoutEvaluationReport",
    "CohortIntervalSummary",
    "RateInterval",
    "evaluate_disjoint_causal_holdout",
    "summarize_cohort_intervals",
    "wilson_interval",
]
