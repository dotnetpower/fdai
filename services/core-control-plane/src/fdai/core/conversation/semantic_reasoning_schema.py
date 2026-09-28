"""Compile schema-level question-form goals into declaration reads.

Schema goals read only release declarations; they never read instances.
"""

from __future__ import annotations

from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    QueryNodeKind,
    SemanticOperation,
    canonical_json,
)

from .semantic_planning_models import SemanticOutputShape
from .semantic_reasoning_form import (
    FilterRole,
    FormGoal,
    GoalLevel,
    GoalOperation,
    GroupBy,
    MentionDomain,
    RelationReach,
    RelationScope,
    SubjectRole,
)
from .semantic_reasoning_nodes import (
    CompileContext,
    OperatorResult,
    PlanSpec,
    concept_values,
    count_node,
    function_declared,
)

_SUBJECT_KINDS = {MentionDomain.OBJECT_TYPE: "object"}
_MANIFEST_GROUPS = frozenset({GroupBy.NONE, GroupBy.TYPE})
_OUTPUT_KINDS = {
    "query.ontology_declaration": "query.table",
    "query.ontology_relationships": "ontology.relationships",
}
SCHEMA_FUNCTIONS = frozenset(
    {
        "query.manifest",
        "query.ontology_declaration",
        "query.ontology_relationships",
        "query.ontology_evidence_health",
        "query.ontology_release_diff",
    }
)


def schema_goal(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    if goal.subject is None:
        return OperatorResult(unsupported=("schema_subject_missing",))
    values, failure = concept_values(goal.subject, ctx)
    if failure is not None:
        return failure
    domain = ctx.mention(goal.subject).domain
    stated = _SUBJECT_KINDS.get(domain)
    linked = False
    if any(item.role is not FilterRole.TYPE for item in goal.filters):
        return OperatorResult(clarify=("schema_filter_conflict",))
    for mention_id in _declared_kinds(goal, ctx):
        # A declaration-kind mention either restates the subject's own kind, as in the
        # Resource ObjectType, or asks for the LinkTypes of an ObjectType subject.
        kinds, kind_failure = concept_values(mention_id, ctx)
        # A stated kind that does not ground is never dropped, cited or not.
        if kind_failure is not None:
            return kind_failure
        if stated == "object" and set(kinds) == {"link"}:
            linked = True
            continue
        if stated is None or set(kinds) != {stated}:
            return OperatorResult(clarify=("schema_filter_conflict",))
    if domain is MentionDomain.DECLARATION_KIND and goal.effective_operation in {
        GoalOperation.SELECT,
        GoalOperation.COUNT,
    }:
        if goal.relation is not None:
            # A manifest listing reads every declaration of the kind and never narrows it to
            # the declarations related to a stated side.
            return OperatorResult(unsupported=("schema_relation_unsupported:declaration_kind",))
        return _manifest_goal(goal, ctx, values)
    if domain is not MentionDomain.OBJECT_TYPE or len(values) != 1:
        return OperatorResult(unsupported=(f"schema_subject_unsupported:{domain.value}",))
    name = values[0]
    relation_failure = _relation_failure(goal)
    if relation_failure is not None:
        return OperatorResult(unsupported=(relation_failure,))
    if linked or goal.relation is not None or goal.effective_operation is GoalOperation.TRAVERSE:
        function_name = "query.ontology_relationships"
        arguments: dict[str, Any] = {"object_types": [name], "limit": 100}
        shape = SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        measures: tuple[str, ...] = ("incoming_relationships", "outgoing_relationships")
    elif goal.effective_operation is GoalOperation.DESCRIBE_SCHEMA:
        function_name = "query.ontology_declaration"
        arguments = {"kind": "object", "name": name, "section": "detail", "limit": 100}
        shape = SemanticOutputShape.ONTOLOGY_DECLARATION
        measures = ("declaration_detail",)
    else:
        return OperatorResult(
            unsupported=(f"schema_operation_unsupported:{goal.effective_operation.value}",)
        )
    if not function_declared(ctx, function_name):
        return OperatorResult(unsupported=(f"function_unavailable:{function_name}",))
    node = OntologyQueryNode(
        node_id=f"{goal.id}-schema",
        kind=QueryNodeKind.FUNCTION,
        arguments_json=canonical_json(
            {"function_name": function_name, "arguments": arguments, "dependency_arguments": {}}
        ),
        output_kind=_OUTPUT_KINDS[function_name],
    )
    return OperatorResult(
        specs=(
            PlanSpec(
                nodes=(node,),
                output_node_ids=(node.node_id,),
                output_shape=shape,
                operation=SemanticOperation.SELECT,
                subject_constraints=(name,),
                measure_concepts=measures,
            ),
        )
    )


def _relation_failure(goal: FormGoal) -> str | None:
    """Return why an ObjectType relation is not the one-hop read of its own LinkTypes.

    The relationship read lists every LinkType one hop from the subject ObjectType in
    both directions, so a single stated sense, a transitive reach, a direction, a
    counterpart, or an anchor other than the subject would be silently widened or
    dropped.
    """

    relation = goal.relation
    if relation is None:
        return None
    if relation.scope is not RelationScope.ALL_KINDS:
        return "schema_relation_sense_unsupported"
    if relation.reach is not RelationReach.ONE_HOP:
        return f"schema_relation_reach_unsupported:{relation.reach.value}"
    if relation.anchor is not None and relation.anchor != goal.subject:
        return "schema_relation_anchor_unsupported"
    if relation.counterpart is not None:
        return "schema_relation_counterpart_unsupported"
    if (
        relation.anchor_role is not SubjectRole.EITHER
        or relation.result_role is not SubjectRole.EITHER
    ):
        # The read lists incoming and outgoing LinkTypes together; one direction is not narrowed.
        return "schema_relation_roles_unsupported"
    return None


def _declared_kinds(goal: FormGoal, ctx: CompileContext) -> tuple[str, ...]:
    """Return the goal's declaration-kind filters and the uncited kinds it alone consumes.

    Admission lets an uncited declaration-kind mention stand only when exactly one schema
    goal can consume it, so no other goal ever receives that mention.
    """

    form = ctx.admission.form
    cited = form.cited_mentions()
    filters = tuple(item.mention for item in goal.filters)
    schema_goals = [item for item in form.goals if item.level is GoalLevel.SCHEMA]
    uncited = (
        tuple(
            mention.id
            for mention in form.mentions
            if mention.domain is MentionDomain.DECLARATION_KIND
            and mention.id not in cited
            and mention.id != goal.subject
        )
        if len(schema_goals) == 1 and schema_goals[0].id == goal.id
        else ()
    )
    return tuple(dict.fromkeys((*filters, *uncited)))


def _manifest_goal(goal: FormGoal, ctx: CompileContext, kinds: tuple[str, ...]) -> OperatorResult:
    measure = goal.measure
    if measure is not None and measure.group_by not in _MANIFEST_GROUPS:
        # A manifest count groups only by declaration kind; no other grouping is substituted.
        return OperatorResult(
            unsupported=(f"schema_group_by_unsupported:{measure.group_by.value}",)
        )
    if not function_declared(ctx, "query.manifest"):
        return OperatorResult(unsupported=("function_unavailable:query.manifest",))
    listing = OntologyQueryNode(
        node_id=f"{goal.id}-manifest",
        kind=QueryNodeKind.FUNCTION,
        arguments_json=canonical_json(
            {
                "function_name": "query.manifest",
                "arguments": {"kinds": sorted(kinds), "limit": 1000},
                "dependency_arguments": {},
            }
        ),
        output_kind="query.table",
    )
    if goal.effective_operation is GoalOperation.SELECT:
        return OperatorResult(
            specs=(
                PlanSpec(
                    nodes=(listing,),
                    output_node_ids=(listing.node_id,),
                    output_shape=SemanticOutputShape.ONTOLOGY_MANIFEST,
                    operation=SemanticOperation.SELECT,
                    subject_constraints=tuple(sorted(kinds)),
                    measure_concepts=("declaration_list",),
                ),
            )
        )
    count = count_node(f"{goal.id}-count", listing.node_id, ["kind"])
    return OperatorResult(
        specs=(
            PlanSpec(
                nodes=(listing, count),
                output_node_ids=(count.node_id,),
                output_shape=SemanticOutputShape.AGGREGATION_TABLE,
                operation=SemanticOperation.AGGREGATE,
                subject_constraints=tuple(sorted(kinds)),
                measure_concepts=("count",),
            ),
        )
    )


__all__ = ["SCHEMA_FUNCTIONS", "schema_goal"]
