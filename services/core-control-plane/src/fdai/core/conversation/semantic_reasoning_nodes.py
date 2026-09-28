"""Shared context, plan specs, and node builders for the reasoning compiler.

Every builder reads only the admitted form, exact mention text, accepted concept
bindings, reviewed manifest metadata, and server defaults.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    QueryNodeKind,
    SemanticOperation,
    canonical_json,
)

from fdai.core.ontology_platform import QueryManifest

from .semantic_planning_models import SemanticOutputShape
from .semantic_reasoning_admission import FormAdmission
from .semantic_reasoning_binding import AnchorBindingReceipt, AnchorOutcome
from .semantic_reasoning_concepts import ConceptOutcome, ConceptSelectionReceipt
from .semantic_reasoning_form import (
    FilterRole,
    FormGoal,
    FormMention,
    GroupBy,
    MentionDomain,
    MentionForm,
    RelationReach,
    RelationScope,
    RelationSense,
    SubjectPosition,
)
from .semantic_reasoning_relations import RelationSide, select_relation_sides
from .semantic_resource_visibility import OPERATIONAL_RESOURCE_EXCLUDED_TYPES

RESOURCE_OBJECT_TYPE = "Resource"
TRAVERSAL_ANCHOR_LIMIT = 7
FUNCTION_ANCHOR_LIMIT = 2
COLLECTION_LIMIT = 1000
_ANCHOR_FORMS = frozenset({MentionForm.IDENTIFIER, MentionForm.NAME})
# A reviewed resource class grounds to Resource.type values until class closure binds.
RESOURCE_TYPE_DOMAINS = frozenset({MentionDomain.RESOURCE_TYPE, MentionDomain.RESOURCE_CLASS})


@dataclass(frozen=True, slots=True)
class CompileContext:
    """Immutable inputs shared by every builder for one admitted form."""

    manifest: QueryManifest
    admission: FormAdmission
    concepts: ConceptSelectionReceipt
    purpose: str
    evaluation_time: datetime
    default_lookback_seconds: int
    anchors: AnchorBindingReceipt = AnchorBindingReceipt()

    @property
    def as_of(self) -> str:
        return self.evaluation_time.astimezone(UTC).isoformat()

    def text(self, mention_id: str) -> str:
        return self.admission.mention_text[mention_id]

    def mention(self, mention_id: str) -> FormMention:
        return self.admission.form.mention(mention_id)


@dataclass(frozen=True, slots=True)
class PlanSpec:
    """One verified-plan candidate before frame and digest binding."""

    nodes: tuple[OntologyQueryNode, ...]
    output_node_ids: tuple[str, ...]
    output_shape: SemanticOutputShape
    operation: SemanticOperation
    subject_constraints: tuple[str, ...]
    measure_concepts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperatorResult:
    specs: tuple[PlanSpec, ...] = ()
    unsupported: tuple[str, ...] = ()
    clarify: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def subject_selection(
    goal: FormGoal, ctx: CompileContext
) -> tuple[str, list[dict[str, Any]], OperatorResult | None]:
    selector = RESOURCE_OBJECT_TYPE
    type_values: tuple[str, ...] = ()
    if goal.subject is not None and not goal.restated_subject:
        domain = ctx.mention(goal.subject).domain
        values, failure = concept_values(goal.subject, ctx)
        if failure is not None:
            return selector, [], failure
        if domain is MentionDomain.OBJECT_TYPE:
            selector = values[0]
        elif domain in RESOURCE_TYPE_DOMAINS:
            type_values = values
        else:
            unsupported = OperatorResult(unsupported=(f"subject_unsupported:{domain.value}",))
            return selector, [], unsupported
    predicates, failure = endpoint_predicates(goal, ctx, extra_types=type_values)
    if failure is not None:
        return selector, [], failure
    if selector != RESOURCE_OBJECT_TYPE and has_type_predicate(predicates):
        return selector, [], OperatorResult(unsupported=("type_filter_requires_resource",))
    if not readable(ctx, selector, predicates):
        return selector, [], OperatorResult(unsupported=("predicate_property_unreadable",))
    return selector, predicates, None


def endpoint_predicates(
    goal: FormGoal,
    ctx: CompileContext,
    *,
    extra_types: tuple[str, ...] = (),
) -> tuple[list[dict[str, Any]], OperatorResult | None]:
    type_values: list[str] = list(extra_types)
    predicates: list[dict[str, Any]] = []
    for item in goal.filters:
        if item.role is FilterRole.SCOPE:
            continue
        if item.role is FilterRole.TYPE:
            values, failure = concept_values(item.mention, ctx)
            if failure is not None:
                return [], failure
            if ctx.mention(item.mention).domain not in RESOURCE_TYPE_DOMAINS:
                return [], OperatorResult(unsupported=("type_filter_domain_unsupported",))
            type_values.extend(values)
        elif item.role is FilterRole.NAME_FRAGMENT:
            predicates.append(
                {"property": "name", "operator": "contains", "equals": ctx.text(item.mention)}
            )
        else:
            return [], OperatorResult(unsupported=(f"filter_unsupported:{item.role.value}",))
    unique_types = sorted(set(type_values))
    if len(unique_types) == 1:
        predicates.insert(0, {"property": "type", "operator": "equals", "equals": unique_types[0]})
    elif unique_types:
        predicates.insert(0, {"property": "type", "operator": "in", "values": unique_types})
    declared = _declared_types(ctx)
    for excluded in OPERATIONAL_RESOURCE_EXCLUDED_TYPES:
        if excluded in declared and excluded not in unique_types:
            predicates.append({"property": "type", "operator": "not_equals", "equals": excluded})
    return predicates, None


def concept_values(
    mention_id: str, ctx: CompileContext
) -> tuple[tuple[str, ...], OperatorResult | None]:
    binding = ctx.concepts.binding(mention_id)
    if binding is None:
        return (), OperatorResult(unsupported=(f"concept_unbound:{mention_id}",))
    if binding.outcome is ConceptOutcome.ACCEPTED:
        return binding.values, None
    reason = binding.reason or f"concept_{binding.outcome.value}"
    if binding.outcome in {ConceptOutcome.NOT_FOUND, ConceptOutcome.AMBIGUOUS}:
        return (), OperatorResult(clarify=(reason,))
    return (), OperatorResult(unsupported=(reason,))


def anchor_node(
    node_id: str, mention_id: str, ctx: CompileContext, limit: int
) -> OntologyQueryNode | OperatorResult:
    """Read the exact identity bound before compilation, never the quoted text."""

    mention = ctx.mention(mention_id)
    if mention.domain is not MentionDomain.INSTANCE or mention.form not in _ANCHOR_FORMS:
        return OperatorResult(unsupported=(f"anchor_form_unsupported:{mention.form.value}",))
    if mention.qualifier is not None:
        return OperatorResult(unsupported=("qualified_anchor_unsupported",))
    binding = ctx.anchors.binding(mention_id)
    if binding is None or binding.outcome is AnchorOutcome.UNAVAILABLE:
        return OperatorResult(unsupported=("anchor_binding_unavailable",))
    if binding.outcome is AnchorOutcome.ABSENT:
        return OperatorResult(clarify=(f"anchor_not_found:{mention_id}",))
    if binding.outcome is AnchorOutcome.AMBIGUOUS:
        return OperatorResult(clarify=(f"anchor_ambiguous:{mention_id}",))
    if binding.outcome is not AnchorOutcome.BOUND or binding.object_id is None:
        return OperatorResult(unsupported=("anchor_resolution_incomplete",))
    predicate = {"property": "id", "operator": "equals", "equals": binding.object_id}
    if not readable(ctx, RESOURCE_OBJECT_TYPE, [predicate]):
        return OperatorResult(unsupported=("anchor_property_unreadable",))
    return object_set_node(node_id, RESOURCE_OBJECT_TYPE, [predicate], ctx, limit=limit)


def object_set_node(
    node_id: str,
    selector: str,
    predicates: Sequence[Mapping[str, Any]],
    ctx: CompileContext,
    *,
    limit: int,
) -> OntologyQueryNode:
    definition = {
        "selector": {"kind": "object_type", "name": selector},
        "predicates": [dict(item) for item in predicates],
        "as_of": ctx.as_of,
        "purpose": ctx.purpose,
        "limit": limit,
        "include_relationships": False,
    }
    return OntologyQueryNode(
        node_id=node_id,
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json({"definition": definition}),
        output_kind="query.table",
    )


def traversal_node(
    node_id: str,
    anchor_id: str,
    side: RelationSide,
    predicates: Sequence[Mapping[str, Any]],
    ctx: CompileContext,
) -> OntologyQueryNode:
    arguments: dict[str, Any] = {
        "selector": {"kind": "object_type", "name": side.endpoint_type},
        "link_types": [side.link_type],
        "direction": side.direction,
        "max_depth": side.max_depth,
        "as_of": ctx.as_of,
        "purpose": ctx.purpose,
        "limit": COLLECTION_LIMIT,
    }
    if predicates:
        arguments["endpoint_predicates"] = [dict(item) for item in predicates]
    return OntologyQueryNode(
        node_id=node_id,
        kind=QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        depends_on=(anchor_id,),
        arguments_json=canonical_json(arguments),
        output_kind="query.table",
    )


def count_node(node_id: str, source_id: str, group: list[str]) -> OntologyQueryNode:
    arguments: dict[str, Any] = {"operation": "count"}
    if group:
        arguments["group_by"] = group
    return OntologyQueryNode(
        node_id=node_id,
        kind=QueryNodeKind.AGGREGATE,
        depends_on=(source_id,),
        arguments_json=canonical_json(arguments),
        output_kind="query.table",
    )


def group_by(goal: FormGoal) -> list[str] | OperatorResult:
    if goal.measure is None or goal.measure.group_by is GroupBy.NONE:
        return []
    if goal.measure.group_by is GroupBy.TYPE:
        return ["properties.type"]
    return OperatorResult(unsupported=(f"group_by_unsupported:{goal.measure.group_by.value}",))


def containment_side(ctx: CompileContext) -> RelationSide | None:
    selection = select_relation_sides(
        ctx.manifest.descriptors,
        anchor_type=RESOURCE_OBJECT_TYPE,
        sense=RelationSense.CONTAINMENT,
        scope=RelationScope.ONE_SENSE,
        position=SubjectPosition.SOURCE,
        reach=RelationReach.TRANSITIVE,
    )
    return selection.sides[0] if len(selection.sides) == 1 else None


def plan_spec(
    goal: FormGoal,
    nodes: tuple[OntologyQueryNode, ...],
    outputs: tuple[str, ...],
    ctx: CompileContext,
    *,
    subjects: tuple[str, ...],
    output_shape: SemanticOutputShape | None = None,
) -> PlanSpec:
    aggregate = any(node.kind is QueryNodeKind.AGGREGATE for node in nodes)
    shape = output_shape or (
        SemanticOutputShape.AGGREGATION_TABLE if aggregate else SemanticOutputShape.RESOURCE_LIST
    )
    return PlanSpec(
        nodes=nodes,
        output_node_ids=outputs,
        output_shape=shape,
        operation=SemanticOperation.AGGREGATE if aggregate else SemanticOperation.SELECT,
        subject_constraints=tuple(dict.fromkeys(subjects)),
        measure_concepts=(f"reasoning.{goal.effective_operation.value}",),
    )


def has_type_predicate(predicates: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        item.get("property") == "type" and item.get("operator") in {"equals", "in"}
        for item in predicates
    )


def is_restrictive(predicates: Sequence[Mapping[str, Any]]) -> bool:
    """Return whether a predicate set narrows endpoints beyond hidden-type policy."""

    return any(item.get("operator") != "not_equals" for item in predicates)


def readable(ctx: CompileContext, selector: str, predicates: Sequence[Mapping[str, Any]]) -> bool:
    properties = _object_properties(ctx, selector)
    return properties is not None and all(item["property"] in properties for item in predicates)


def _object_properties(ctx: CompileContext, name: str) -> Mapping[str, Any] | None:
    descriptor = next(
        (
            item
            for item in ctx.manifest.descriptors
            if item.get("kind") == "object" and item.get("name") == name
        ),
        None,
    )
    properties = descriptor.get("properties") if isinstance(descriptor, Mapping) else None
    return properties if isinstance(properties, Mapping) else None


def _declared_types(ctx: CompileContext) -> frozenset[str]:
    properties = _object_properties(ctx, RESOURCE_OBJECT_TYPE) or {}
    domain = properties.get("type")
    values = domain.get("values") if isinstance(domain, Mapping) else None
    return frozenset(str(item) for item in values) if isinstance(values, list) else frozenset()


def function_declared(ctx: CompileContext, name: str) -> bool:
    return any(
        item.get("kind") == "function" and item.get("name") == name
        for item in ctx.manifest.descriptors
    )


__all__ = [
    "COLLECTION_LIMIT",
    "FUNCTION_ANCHOR_LIMIT",
    "RESOURCE_OBJECT_TYPE",
    "RESOURCE_TYPE_DOMAINS",
    "TRAVERSAL_ANCHOR_LIMIT",
    "CompileContext",
    "OperatorResult",
    "PlanSpec",
    "anchor_node",
    "concept_values",
    "containment_side",
    "count_node",
    "endpoint_predicates",
    "function_declared",
    "group_by",
    "has_type_predicate",
    "is_restrictive",
    "object_set_node",
    "plan_spec",
    "readable",
    "subject_selection",
    "traversal_node",
]
