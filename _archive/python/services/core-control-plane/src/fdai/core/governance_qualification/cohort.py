"""Measure Rule false positives, false negatives, holds, and coverage on a frozen cohort.

The cohort is frozen by digest before measurement; measuring against a different case set fails
closed. A held case is never counted as correct. Rates with a zero denominator are absent, never
zero.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from fdai.rule_catalog.schema.framework_assessment import canonical_digest

_Z_95 = 1.959963984540054


class GroundTruth(StrEnum):
    VIOLATION = "violation"
    COMPLIANT = "compliant"


class Verdict(StrEnum):
    FLAGGED = "flagged"
    NOT_FLAGGED = "not_flagged"
    HELD = "held"


@dataclass(frozen=True, slots=True)
class CohortCase:
    """One evaluated case; ``group_id`` is the independence unit (incident, resource, retry)."""

    case_id: str
    group_id: str
    truth: GroundTruth
    verdict: Verdict

    def __post_init__(self) -> None:
        if not (self.case_id and self.group_id):
            raise ValueError("cohort case MUST name its case and independence group")


@dataclass(frozen=True, slots=True)
class FrozenCohort:
    cases: tuple[CohortCase, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class Rate:
    """A proportion with its Wilson 95% interval."""

    numerator: int
    denominator: int
    value: float
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class CohortMeasurement:
    cohort_digest: str
    total: int
    independent_groups: int
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    held_violation: int
    held_compliant: int
    coverage: Rate | None
    false_positive_rate: Rate | None
    false_negative_rate: Rate | None
    # Held violations counted as misses, so a hold cannot hide a false negative.
    false_negative_rate_worst_case: Rate | None
    digest: str


def freeze_cohort(cases: Iterable[CohortCase]) -> FrozenCohort:
    """Freeze the case set; the digest covers case, group, truth, and verdict."""

    ordered = tuple(sorted(cases, key=lambda case: case.case_id))
    if not ordered:
        raise ValueError("cohort MUST contain at least one case")
    if len({case.case_id for case in ordered}) != len(ordered):
        raise ValueError("cohort case identifiers MUST be unique")
    digest = canonical_digest(
        [[c.case_id, c.group_id, c.truth.value, c.verdict.value] for c in ordered]
    )
    return FrozenCohort(ordered, digest)


def measure_cohort(cohort: FrozenCohort, *, expected_digest: str) -> CohortMeasurement:
    """Measure the cohort only when it still matches the digest that was frozen."""

    recomputed = freeze_cohort(cohort.cases).digest
    if cohort.digest != expected_digest or recomputed != expected_digest:
        raise ValueError("cohort differs from the frozen denominator digest")
    counts = {(truth, verdict): 0 for truth in GroundTruth for verdict in Verdict}
    for case in cohort.cases:
        counts[(case.truth, case.verdict)] += 1
    tp = counts[(GroundTruth.VIOLATION, Verdict.FLAGGED)]
    fn = counts[(GroundTruth.VIOLATION, Verdict.NOT_FLAGGED)]
    held_v = counts[(GroundTruth.VIOLATION, Verdict.HELD)]
    fp = counts[(GroundTruth.COMPLIANT, Verdict.FLAGGED)]
    tn = counts[(GroundTruth.COMPLIANT, Verdict.NOT_FLAGGED)]
    held_c = counts[(GroundTruth.COMPLIANT, Verdict.HELD)]
    total = len(cohort.cases)
    groups = len({case.group_id for case in cohort.cases})
    return CohortMeasurement(
        cohort_digest=cohort.digest,
        total=total,
        independent_groups=groups,
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        true_negative=tn,
        held_violation=held_v,
        held_compliant=held_c,
        coverage=_rate(total - held_v - held_c, total),
        false_positive_rate=_rate(fp, fp + tn),
        false_negative_rate=_rate(fn, fn + tp),
        false_negative_rate_worst_case=_rate(fn + held_v, fn + tp + held_v),
        digest=canonical_digest(
            {
                "cohort_digest": cohort.digest,
                "total": total,
                "independent_groups": groups,
                "counts": [tp, fp, fn, tn, held_v, held_c],
            }
        ),
    )


def _rate(numerator: int, denominator: int) -> Rate | None:
    if denominator <= 0:
        return None
    proportion = numerator / denominator
    z2 = _Z_95**2
    centre = (proportion + z2 / (2 * denominator)) / (1 + z2 / denominator)
    margin = (
        _Z_95
        * math.sqrt(proportion * (1 - proportion) / denominator + z2 / (4 * denominator**2))
        / (1 + z2 / denominator)
    )
    return Rate(
        numerator,
        denominator,
        proportion,
        max(0.0, centre - margin),
        min(1.0, centre + margin),
    )
