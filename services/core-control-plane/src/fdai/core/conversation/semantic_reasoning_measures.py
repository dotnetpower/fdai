"""Resolve a goal's stated state or health restriction into one reviewed reader stage.

A state restriction reads the Resource state inventory; a health restriction reads the
Resource Health inventory. Each reader filters the Resource rows an earlier node read.
The health reader also returns rows for unknown coverage and for other unavailable
states, so its rows are listed with their concept and never counted as matches. The
health reader unions the state rows it is given, while stated restrictions intersect,
so one goal that restricts both is typed unsupported instead of widened.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    QueryNodeKind,
    canonical_json,
)

from fdai.core.ontology_platform.resource_health_queries import RESOURCE_HEALTH_FUNCTION_NAME
from fdai.core.ontology_platform.resource_state_queries import RESOURCE_STATE_FUNCTION_NAME

from .semantic_planning_models import SemanticOutputShape
from .semantic_reasoning_form import (
    FilterRole,
    FormGoal,
    GoalOperation,
    MentionDomain,
)
from .semantic_reasoning_lifecycle import parse_lifecycle
from .semantic_reasoning_nodes import (
    RESOURCE_OBJECT_TYPE,
    CompileContext,
    OperatorResult,
    concept_values,
    function_declared,
)


@dataclass(frozen=True, slots=True)
class _MeasureReader:
    role: FilterRole
    domain: MentionDomain
    function_name: str
    output_shape: SemanticOutputShape


_READERS = (
    _MeasureReader(
        FilterRole.STATE,
        MentionDomain.STATE,
        RESOURCE_STATE_FUNCTION_NAME,
        SemanticOutputShape.RESOURCE_STATE_LIST,
    ),
    _MeasureReader(
        FilterRole.HEALTH,
        MentionDomain.HEALTH,
        RESOURCE_HEALTH_FUNCTION_NAME,
        SemanticOutputShape.RESOURCE_HEALTH_LIST,
    ),
)


@dataclass(frozen=True, slots=True)
class MeasureRestriction:
    """The reviewed concepts one reader stage keeps, for the role that states them."""

    role: FilterRole
    function_name: str
    output_shape: SemanticOutputShape
    concepts: tuple[str, ...]

    def node(self, node_id: str, source_id: str) -> OntologyQueryNode:
        arguments: dict[str, list[str]] = (
            {"health_concepts": list(self.concepts), "state_concepts": []}
            if self.role is FilterRole.HEALTH
            else {"state_concepts": list(self.concepts)}
        )
        return OntologyQueryNode(
            node_id=node_id,
            kind=QueryNodeKind.FUNCTION,
            depends_on=(source_id,),
            arguments_json=canonical_json(
                {
                    "function_name": self.function_name,
                    "arguments": arguments,
                    "dependency_arguments": {source_id: "query_result"},
                }
            ),
            output_kind="query.table",
        )


def stated_measure(
    goal: FormGoal, ctx: CompileContext
) -> MeasureRestriction | OperatorResult | None:
    """Return the one reader stage the goal's state or health filters require."""

    found: list[MeasureRestriction] = []
    for reader in _READERS:
        concepts = _stated_concepts(goal, ctx, reader)
        if isinstance(concepts, OperatorResult):
            return concepts
        if concepts:
            found.append(
                MeasureRestriction(reader.role, reader.function_name, reader.output_shape, concepts)
            )
    if len(found) > 1:
        return OperatorResult(unsupported=("state_and_health_filter_unsupported",))
    if not found:
        return None
    restriction = found[0]
    if restriction.role is FilterRole.HEALTH and goal.effective_operation is GoalOperation.COUNT:
        return OperatorResult(unsupported=("health_count_unsupported",))
    return restriction


def _stated_concepts(
    goal: FormGoal, ctx: CompileContext, reader: _MeasureReader
) -> tuple[str, ...] | OperatorResult:
    """Return the reviewed concepts every filter of ``reader.role`` binds, in stable order."""

    concepts: list[str] = []
    # A lifecycle state of another ObjectType is an exact predicate, never a reader stage.
    stated = [
        item
        for item in goal.filters
        if item.role is reader.role
        and not (reader.role is FilterRole.STATE and _names_lifecycle(item.mention, ctx))
    ]
    if stated and goal.subject is not None:
        # Reviewed states and health describe Resources; another ObjectType has no reader here.
        subject = ctx.mention(goal.subject)
        values, _failure = concept_values(goal.subject, ctx)
        if subject.domain is MentionDomain.OBJECT_TYPE and values != (RESOURCE_OBJECT_TYPE,):
            return OperatorResult(unsupported=(f"filter_unsupported:{reader.role.value}",))
    for item in stated:
        if ctx.mention(item.mention).domain is not reader.domain:
            return OperatorResult(unsupported=(f"{reader.role.value}_filter_domain_unsupported",))
        values, failure = concept_values(item.mention, ctx)
        if failure is not None:
            return failure
        concepts.extend(values)
    if concepts and not function_declared(ctx, reader.function_name):
        return OperatorResult(unsupported=(f"function_unavailable:{reader.function_name}",))
    return tuple(sorted(set(concepts)))


def _names_lifecycle(mention_id: str, ctx: CompileContext) -> bool:
    """Return whether a mention grounds in another ObjectType's lifecycle values."""

    values, _failure = concept_values(mention_id, ctx)
    return any(parse_lifecycle(item) is not None for item in values)


__all__ = ["MeasureRestriction", "stated_measure"]
