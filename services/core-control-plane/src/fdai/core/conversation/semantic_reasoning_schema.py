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
from .semantic_reasoning_form import FilterRole, FormGoal, GoalOperation, MentionDomain
from .semantic_reasoning_nodes import (
    CompileContext,
    OperatorResult,
    PlanSpec,
    concept_values,
    count_node,
    function_declared,
)

_SUBJECT_KINDS = {MentionDomain.OBJECT_TYPE: "object"}
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
    linked = False
    for item in goal.filters:
        # A declaration-kind filter either restates the subject's own kind, as in the
        # Resource ObjectType, or asks for the LinkTypes of an ObjectType subject.
        kinds, kind_failure = concept_values(item.mention, ctx)
        if kind_failure is not None:
            return kind_failure
        stated = _SUBJECT_KINDS.get(domain)
        if item.role is FilterRole.TYPE and stated == "object" and set(kinds) == {"link"}:
            linked = True
            continue
        if item.role is not FilterRole.TYPE or stated is None or set(kinds) != {stated}:
            return OperatorResult(clarify=("schema_filter_conflict",))
    if domain is MentionDomain.DECLARATION_KIND and goal.effective_operation in {
        GoalOperation.SELECT,
        GoalOperation.COUNT,
    }:
        return _manifest_goal(goal, ctx, values)
    if domain is not MentionDomain.OBJECT_TYPE or len(values) != 1:
        return OperatorResult(unsupported=(f"schema_subject_unsupported:{domain.value}",))
    name = values[0]
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


def _manifest_goal(goal: FormGoal, ctx: CompileContext, kinds: tuple[str, ...]) -> OperatorResult:
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
