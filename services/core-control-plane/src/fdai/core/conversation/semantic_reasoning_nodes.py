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
    MAX_INTENT_GOAL_DEPENDENCIES,
    OntologyQueryNode,
    QueryNodeKind,
    SemanticOperation,
    canonical_json,
)

from fdai.core.ontology_platform import QueryManifest
from fdai.core.ontology_platform.resource_state_queries import RESOURCE_STATE_FUNCTION_NAME

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
    SubjectScope,
)
from .semantic_reasoning_handles import ReferenceReceipt, restricting_rows
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
    references: ReferenceReceipt = ReferenceReceipt()

    @property
    def as_of(self) -> str:
        return self.evaluation_time.astimezone(UTC).isoformat()

    def text(self, mention_id: str) -> str:
        return self.admission.mention_text[mention_id]

    def mention(self, mention_id: str) -> FormMention:
        return self.admission.form.mention(mention_id)

    def prior_rows(self, goal: FormGoal) -> tuple[str, ...] | None:
        """Return the rows an earlier answer showed that restrict this goal's results."""

        return restricting_rows(self.admission, self.references, goal)


@dataclass(frozen=True, slots=True)
class PlanSpec:
    """One verified-plan candidate before frame and digest binding."""

    nodes: tuple[OntologyQueryNode, ...]
    output_node_ids: tuple[str, ...]
    # A reviewed compiler-only shape, such as causal context, is a plain string the frame
    # model's enum never offers, so the legacy frame path cannot propose it.
    output_shape: SemanticOutputShape | str
    operation: SemanticOperation
    subject_constraints: tuple[str, ...]
    measure_concepts: tuple[str, ...]
    # Reviewed limitations the answer states as catalog notices, such as the applied window.
    evidence_requirements: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OperatorResult:
    specs: tuple[PlanSpec, ...] = ()
    unsupported: tuple[str, ...] = ()
    clarify: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


def subject_selection(
    goal: FormGoal, ctx: CompileContext, *, state_stage: bool = False
) -> tuple[str, list[dict[str, Any]], OperatorResult | None]:
    selector = RESOURCE_OBJECT_TYPE
    type_values: tuple[str, ...] = ()
    if goal.subject_scope is SubjectScope.PRIOR_RESULT:
        # The earlier rows are the subject; endpoint predicates restrict to them.
        pass
    elif goal.subject is not None and not goal.restated_subject:
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
    predicates, failure = endpoint_predicates(
        goal, ctx, extra_types=type_values, selector=selector, state_stage=state_stage
    )
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
    selector: str = RESOURCE_OBJECT_TYPE,
    state_stage: bool = False,
) -> tuple[list[dict[str, Any]], OperatorResult | None]:
    """Return the endpoint predicates every stated restriction requires.

    Each stated kind restriction narrows the others, so the subject kind and every
    type filter intersect; an empty intersection clarifies instead of widening. An
    empty value set is the explicit resources-in-general root and restricts nothing.
    """

    type_sets: list[frozenset[str]] = [frozenset(extra_types)] if extra_types else []
    predicates: list[dict[str, Any]] = []
    for item in goal.filters:
        # A state restriction is read by the state inventory stage that follows this read.
        if item.role is FilterRole.SCOPE or (state_stage and item.role is FilterRole.STATE):
            continue
        if item.role is FilterRole.TYPE:
            values, failure = concept_values(item.mention, ctx)
            if failure is not None:
                return [], failure
            if ctx.mention(item.mention).domain not in RESOURCE_TYPE_DOMAINS:
                return [], OperatorResult(unsupported=("type_filter_domain_unsupported",))
            if values:
                type_sets.append(frozenset(values))
        elif item.role is FilterRole.NAME_FRAGMENT:
            predicates.append(
                {"property": "name", "operator": "contains", "equals": ctx.text(item.mention)}
            )
        elif item.role is FilterRole.REGION:
            regions, failure = concept_values(item.mention, ctx)
            if failure is not None:
                return [], failure
            if ctx.mention(item.mention).domain is not MentionDomain.REGION or not regions:
                return [], OperatorResult(unsupported=("region_filter_domain_unsupported",))
            predicates.append(
                {"property": "location", "operator": "equals", "equals": regions[0]}
                if len(regions) == 1
                else {"property": "location", "operator": "in", "values": sorted(regions)}
            )
        else:
            return [], OperatorResult(unsupported=(f"filter_unsupported:{item.role.value}",))
    required = sorted(frozenset.intersection(*type_sets)) if type_sets else []
    if type_sets and not required:
        return [], OperatorResult(clarify=("type_restrictions_disjoint",))
    prior = ctx.prior_rows(goal)
    if prior is not None:
        # A reference keeps only rows the operator saw; the gateway still reauthorizes each.
        predicates.append({"property": "id", "operator": "in", "values": sorted(prior)})
    if len(required) == 1:
        predicates.insert(0, {"property": "type", "operator": "equals", "equals": required[0]})
    elif required:
        predicates.insert(0, {"property": "type", "operator": "in", "values": required})
    if selector == RESOURCE_OBJECT_TYPE:
        declared = _declared_types(ctx)
        for excluded in OPERATIONAL_RESOURCE_EXCLUDED_TYPES:
            if excluded in declared and excluded not in required:
                predicates.append(
                    {"property": "type", "operator": "not_equals", "equals": excluded}
                )
    return predicates, None


def union_tree(root_id: str, members: Sequence[str]) -> tuple[OntologyQueryNode, ...]:
    """Unite two or more member outputs under ``root_id``, the returned last node.

    Each union reads at most the dependencies one Console intent goal can show, so a
    wider fan-in becomes parts united again; every member is still read exactly once.
    """

    if len(members) < 2:
        raise ValueError("a union needs at least two members")
    created: list[OntologyQueryNode] = []
    level = list(members)
    while len(level) > MAX_INTENT_GOAL_DEPENDENCIES:
        chunks = [
            level[start : start + MAX_INTENT_GOAL_DEPENDENCIES]
            for start in range(0, len(level), MAX_INTENT_GOAL_DEPENDENCIES)
        ]
        level = []
        for chunk in chunks:
            if len(chunk) == 1:
                level.append(chunk[0])
                continue
            part = OntologyQueryNode(
                node_id=f"{root_id}-part-{len(created) + 1}",
                kind=QueryNodeKind.UNION,
                depends_on=tuple(chunk),
                output_kind="query.table",
            )
            created.append(part)
            level.append(part.node_id)
    root = OntologyQueryNode(
        node_id=root_id,
        kind=QueryNodeKind.UNION,
        depends_on=tuple(level),
        output_kind="query.table",
    )
    return (*created, root)


def declared_maximum(ctx: CompileContext, function_name: str, argument: str) -> int | None:
    """Return the maximum a declared FunctionType admits for one integer input, if any.

    Bounds come from the reviewed declaration in the manifest, so a builder never states
    its own copy of a reader's limit.
    """

    for descriptor in ctx.manifest.descriptors:
        if descriptor.get("kind") != "function" or descriptor.get("name") != function_name:
            continue
        schema = descriptor.get("input_schema") or {}
        properties = schema.get("properties") if isinstance(schema, Mapping) else None
        spec = properties.get(argument) if isinstance(properties, Mapping) else None
        maximum = spec.get("maximum") if isinstance(spec, Mapping) else None
        if isinstance(maximum, int) and not isinstance(maximum, bool) and maximum > 0:
            return maximum
        return None
    return None


def declared_measures(ctx: CompileContext, function_name: str) -> tuple[str, ...]:
    """Return the measure fields a declared FunctionType's output names, in declared order."""

    for descriptor in ctx.manifest.descriptors:
        if descriptor.get("kind") == "function" and descriptor.get("name") == function_name:
            schema = descriptor.get("output_schema") or {}
            measures = (
                schema.get("x-fdai-measure-concepts") if isinstance(schema, Mapping) else None
            )
            if isinstance(measures, list) and all(isinstance(item, str) for item in measures):
                return tuple(measures)
            return ()
    return ()


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
    # A reference anchors like a name only when it is bound to one row of an earlier
    # answer; any other reference has no anchor binding and fails below.
    anchor_forms = _ANCHOR_FORMS | {MentionForm.ORDINAL, MentionForm.ANAPHOR}
    if mention.domain is not MentionDomain.INSTANCE or mention.form not in anchor_forms:
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
        # The typed read reason, such as read_incomplete, tells data state from a reading.
        suffix = f":{binding.reason}" if binding.reason else ""
        return OperatorResult(unsupported=(f"anchor_resolution_incomplete{suffix}",))
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


def state_filter_node(
    node_id: str, source_id: str, state_concepts: tuple[str, ...]
) -> OntologyQueryNode:
    """Filter one Resource read to the reviewed state concepts the goal states."""

    return OntologyQueryNode(
        node_id=node_id,
        kind=QueryNodeKind.FUNCTION,
        depends_on=(source_id,),
        arguments_json=canonical_json(
            {
                "function_name": RESOURCE_STATE_FUNCTION_NAME,
                "arguments": {"state_concepts": list(state_concepts)},
                "dependency_arguments": {source_id: "query_result"},
            }
        ),
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


# A Resource's container is its direct parent, the `from` end of its `contains` link.
GROUP_BY_FIELDS = {GroupBy.TYPE: "properties.type", GroupBy.CONTAINER: "properties.parent_id"}


def group_by(goal: FormGoal) -> list[str] | OperatorResult:
    if goal.measure is None or goal.measure.group_by is GroupBy.NONE:
        return []
    field = GROUP_BY_FIELDS.get(goal.measure.group_by)
    if field is not None:
        return [field]
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
    output_shape: SemanticOutputShape | str | None = None,
    measure_concepts: tuple[str, ...] = (),
    evidence_requirements: tuple[str, ...] = (),
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
        measure_concepts=measure_concepts or (f"reasoning.{goal.effective_operation.value}",),
        evidence_requirements=evidence_requirements,
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
    "GROUP_BY_FIELDS",
    "state_filter_node",
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
