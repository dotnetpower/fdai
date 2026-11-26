"""Deterministic severity from verified facts, with an explicit range for unknown facts.

Severity describes intrinsic technical impact only. Threat intelligence and runtime exposure are
priority inputs and never appear here. For each instance the rubric evaluates a floor (unknown
facts at their least severe value) and a ceiling (unknown facts at their most severe value):

- equal bands produce that band as the single label;
- different bands produce ``undetermined`` plus the facts whose verification would move a bound.

An issue aggregates its instances: its floor is the highest instance floor, its ceiling the
highest instance ceiling, and its governing instance is the one that sets the ceiling. The same
facts and rubric version always yield the same result.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from fdai.core.security.code_findings.models import (
    UNDETERMINED,
    Instance,
    InstanceFacts,
    SeverityAssessment,
    SeverityMethod,
)
from fdai.rule_catalog.code_security import (
    BAND_ORDER,
    AttackComplexity,
    AttackVector,
    Impact,
    PrivilegesRequired,
    SeverityBand,
    SeverityRubric,
    UserInteraction,
)

_FACT_NAMES = (
    "impact",
    "attack_vector",
    "attack_complexity",
    "privileges_required",
    "user_interaction",
)


def band_for_points(points: float, rubric: SeverityRubric) -> SeverityBand:
    for threshold in rubric.bands:
        if points >= threshold.min_points:
            return threshold.band
    return SeverityBand.LOW


def band_for_score(score: float, rubric: SeverityRubric) -> SeverityBand:
    for threshold in rubric.advisory_score_bands:
        if score >= threshold.min_score:
            return threshold.band
    return SeverityBand.LOW


def _points(facts: InstanceFacts, rubric: SeverityRubric) -> float:
    """Score fully resolved facts; callers pass only facts filled by :func:`_resolve`."""
    if (
        facts.impact is None
        or facts.attack_vector is None
        or facts.attack_complexity is None
        or facts.privileges_required is None
        or facts.user_interaction is None
    ):
        raise ValueError("rubric points require fully resolved facts")
    return round(
        rubric.impact_points[facts.impact]
        - rubric.attack_vector_penalty[facts.attack_vector]
        - rubric.attack_complexity_penalty[facts.attack_complexity]
        - rubric.privileges_required_penalty[facts.privileges_required]
        - rubric.user_interaction_penalty[facts.user_interaction],
        2,
    )


def _extreme[T](values: Sequence[T], weight: Callable[[T], float], *, most_severe: bool) -> T:
    ranked = sorted(values, key=lambda value: (weight(value), str(value)))
    return ranked[-1] if most_severe else ranked[0]


def _resolve(
    facts: InstanceFacts,
    impact_range: Sequence[Impact],
    rubric: SeverityRubric,
    *,
    most_severe: bool,
) -> InstanceFacts:
    """Fill unknown facts with their least or most severe rubric value."""
    return InstanceFacts(
        impact=facts.impact
        or _extreme(impact_range, lambda v: rubric.impact_points[v], most_severe=most_severe),
        attack_vector=facts.attack_vector
        or _extreme(
            list(AttackVector),
            lambda v: -rubric.attack_vector_penalty[v],
            most_severe=most_severe,
        ),
        attack_complexity=facts.attack_complexity
        or _extreme(
            list(AttackComplexity),
            lambda v: -rubric.attack_complexity_penalty[v],
            most_severe=most_severe,
        ),
        privileges_required=facts.privileges_required
        or _extreme(
            list(PrivilegesRequired),
            lambda v: -rubric.privileges_required_penalty[v],
            most_severe=most_severe,
        ),
        user_interaction=facts.user_interaction
        or _extreme(
            list(UserInteraction),
            lambda v: -rubric.user_interaction_penalty[v],
            most_severe=most_severe,
        ),
        evidence_refs=facts.evidence_refs,
    )


def assess_facts(
    facts: InstanceFacts, impact_range: Sequence[Impact], rubric: SeverityRubric
) -> SeverityAssessment:
    """Assess one instance from its verified facts and its weakness class impact range."""
    if not impact_range:
        raise ValueError("impact_range must not be empty")
    floor_facts = _resolve(facts, impact_range, rubric, most_severe=False)
    ceiling_facts = _resolve(facts, impact_range, rubric, most_severe=True)
    floor_points = _points(floor_facts, rubric)
    ceiling_points = _points(ceiling_facts, rubric)
    floor = band_for_points(floor_points, rubric)
    ceiling = band_for_points(ceiling_points, rubric)
    unknown = tuple(name for name in _FACT_NAMES if getattr(facts, name) is None)
    deciding: list[str] = []
    for name in unknown:
        raised_floor = replace(floor_facts, **{name: getattr(ceiling_facts, name)})
        lowered_ceiling = replace(ceiling_facts, **{name: getattr(floor_facts, name)})
        if (
            band_for_points(_points(raised_floor, rubric), rubric) != floor
            or band_for_points(_points(lowered_ceiling, rubric), rubric) != ceiling
        ):
            deciding.append(name)
    described = ", ".join(
        f"{name}={getattr(facts, name).value}"
        if getattr(facts, name) is not None
        else f"{name}=unknown"
        for name in _FACT_NAMES
    )
    return SeverityAssessment(
        label=floor.value if floor == ceiling else UNDETERMINED,
        floor=floor,
        ceiling=ceiling,
        method=SeverityMethod.FACT_RUBRIC,
        floor_points=floor_points,
        ceiling_points=ceiling_points,
        unknown_facts=unknown,
        deciding_facts=tuple(deciding),
        rationale=(
            f"severity rubric {rubric.version}: {described}; "
            f"floor {floor_points} ({floor.value}), ceiling {ceiling_points} ({ceiling.value})"
        ),
        rubric_version=rubric.version,
    )


def assess_advisory(
    scores: Sequence[tuple[str, float]], rubric: SeverityRubric
) -> SeverityAssessment:
    """Assess a dependency advisory from producer-reported CVSS base scores.

    Different producers can report different scores (for example CVSS v3.1 and v4.0). The range
    stays visible as ``undetermined`` instead of picking one silently.
    """
    if not scores:
        raise ValueError("scores must not be empty")
    values = [score for _, score in scores]
    low, high = min(values), max(values)
    floor, ceiling = band_for_score(low, rubric), band_for_score(high, rubric)
    reported = ", ".join(f"{producer}={score}" for producer, score in sorted(scores))
    return SeverityAssessment(
        label=floor.value if floor == ceiling else UNDETERMINED,
        floor=floor,
        ceiling=ceiling,
        method=SeverityMethod.ADVISORY_SCORE,
        floor_points=low,
        ceiling_points=high,
        unknown_facts=(),
        deciding_facts=() if floor == ceiling else ("advisory_score_disagreement",),
        rationale=f"advisory CVSS base score reported by producers: {reported}",
        rubric_version=rubric.version,
    )


def aggregate_issue_severity(instances: Sequence[Instance]) -> tuple[SeverityAssessment, str]:
    """Return the single issue severity and the id of its governing instance."""
    if not instances:
        raise ValueError("an issue needs at least one instance")
    # Sorting by id first makes max() pick the smallest id on a full tie.
    ordered = sorted(instances, key=lambda item: item.instance_id)
    governing = max(
        ordered,
        key=lambda item: (
            BAND_ORDER[item.severity.ceiling],
            item.severity.ceiling_points,
            BAND_ORDER[item.severity.floor],
            item.severity.floor_points,
        ),
    )
    floor_instance = max(
        ordered, key=lambda item: (BAND_ORDER[item.severity.floor], item.severity.floor_points)
    )
    floor = floor_instance.severity.floor
    ceiling = governing.severity.ceiling
    base = governing.severity
    return (
        replace(
            base,
            label=floor.value if floor == ceiling else UNDETERMINED,
            floor=floor,
            floor_points=floor_instance.severity.floor_points,
            deciding_facts=base.deciding_facts if floor != ceiling else (),
        ),
        governing.instance_id,
    )


__all__ = [
    "aggregate_issue_severity",
    "assess_advisory",
    "assess_facts",
    "band_for_points",
    "band_for_score",
]
