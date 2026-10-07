"""Concept provenance for collection-member state and health listings."""

from __future__ import annotations

from typing import Protocol

from fdai.core.ontology_platform.resource_state_queries import RESOURCE_STATE_OBSERVED_CONCEPT

from .semantic_reasoning_form import (
    FormGoal,
    GoalOperation,
    MeasureKind,
    SubjectScope,
)


class AllowedMeasureConcepts(Protocol):
    state_concepts: set[str]
    health_concepts: set[str]


def allow_listed_measure(
    goal: FormGoal,
    allowed: AllowedMeasureConcepts,
    health_concepts: tuple[str, ...],
) -> None:
    """Re-derive concepts read when a collection lists each member's measure."""

    measure = goal.measure
    if (
        measure is None
        or goal.effective_operation is not GoalOperation.SELECT
        or goal.subject_scope is not SubjectScope.COLLECTION
    ):
        return
    if measure.kind is MeasureKind.STATE and not allowed.state_concepts:
        allowed.state_concepts.add(RESOURCE_STATE_OBSERVED_CONCEPT)
    elif measure.kind is MeasureKind.HEALTH and not allowed.health_concepts:
        allowed.health_concepts.update(health_concepts)
