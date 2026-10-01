"""Compile a lookup of one reviewed property of one bound Resource.

A property measure grounds by closed choice to a declared value domain of Resource or to a
reviewed Property semantic. The read projects only the reviewed provider path for the bound
Resource's type, so no unreviewed provider field reaches an answer, and the answer states
where the value came from and how fresh it must be.
"""

from __future__ import annotations

from collections.abc import Sequence

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    canonical_json,
)

from fdai.core.ontology_platform import ReviewedPropertyRead

from .semantic_planning_models import SemanticOutputShape
from .semantic_reasoning_admission import FormAdmission
from .semantic_reasoning_binding import AnchorBindingReceipt
from .semantic_reasoning_concepts import ConceptOutcome, ConceptSelectionReceipt
from .semantic_reasoning_form import FormGoal, GoalOperation, MeasureKind, MentionDomain
from .semantic_reasoning_nodes import (
    FUNCTION_ANCHOR_LIMIT,
    RESOURCE_OBJECT_TYPE,
    CompileContext,
    OperatorResult,
    anchor_node,
    plan_spec,
)

PROPERTY_SOURCE_LIMITATION = "property_source_inventory"
# Inventory configuration reads carry this default freshness ceiling
# (`FDAI_INVENTORY_FRESHNESS_SECONDS`). A semantic that needs fresher evidence holds
# instead of answering from an inventory record that may be up to this old.
INVENTORY_FRESHNESS_SECONDS = 86_400
_DECLARED_PREFIX = f"{RESOURCE_OBJECT_TYPE}."
_PROVIDER_BAG = "properties"
_IDENTITY_FIELDS = ("id", "properties.name", "properties.type")


def is_property_lookup(goal: FormGoal) -> bool:
    return (
        goal.effective_operation is GoalOperation.LOOKUP
        and goal.measure is not None
        and goal.measure.kind is MeasureKind.PROPERTY
    )


def property_lookup(goal: FormGoal, ctx: CompileContext) -> OperatorResult:
    """Project the measure's one reviewed property from the goal's bound anchor."""

    measure = goal.measure
    if measure is None or measure.mention is None:
        return OperatorResult(unsupported=("property_mention_required",))
    if goal.subject is None:
        return OperatorResult(unsupported=("anchor_missing",))
    domain = ctx.mention(measure.mention).domain
    if domain is not MentionDomain.PROPERTY:
        return OperatorResult(unsupported=(f"property_mention_domain:{domain.value}",))
    binding = ctx.concepts.binding(measure.mention)
    if binding is None:
        return OperatorResult(unsupported=(f"concept_unbound:{measure.mention}",))
    # A property outside the reviewed catalog holds with a typed reason, never a raw field.
    if binding.outcome is ConceptOutcome.NOT_FOUND:
        return OperatorResult(unsupported=("property_unreviewed",))
    if binding.outcome is ConceptOutcome.AMBIGUOUS:
        return OperatorResult(clarify=(binding.reason or "concept_ambiguous",))
    if binding.outcome is not ConceptOutcome.ACCEPTED:
        return OperatorResult(unsupported=(binding.reason or "property_unreadable",))
    if len(binding.values) != 1:
        return OperatorResult(unsupported=("property_count_unsupported",))
    # A missing or ambiguous name clarifies before any provider path is chosen.
    anchor = anchor_node(f"{goal.id}-anchor", goal.subject, ctx, FUNCTION_ANCHOR_LIMIT)
    if isinstance(anchor, OperatorResult):
        return anchor
    anchor_binding = ctx.anchors.binding(goal.subject)
    resource_type = anchor_binding.resource_type if anchor_binding is not None else None
    readable = _readable_properties(ctx)
    field = property_field(binding.values[0], ctx.manifest.property_reads, resource_type, readable)
    if not field.startswith("properties."):
        return OperatorResult(unsupported=(field,))
    project = OntologyQueryNode(
        node_id=f"{goal.id}-read",
        kind=QueryNodeKind.PROJECT,
        depends_on=(anchor.node_id,),
        arguments_json=canonical_json({"fields": list(projected_fields(field, readable))}),
        output_kind="query.table",
    )
    seconds = property_freshness(binding.values[0], ctx.manifest.property_reads)
    spec = plan_spec(
        goal,
        (anchor, project),
        (project.node_id,),
        ctx,
        subjects=(RESOURCE_OBJECT_TYPE,),
        output_shape=SemanticOutputShape.TARGET_PROPERTY_VALUE,
        # The grounded identity labels the value, and the projected field says which one it is.
        measure_concepts=(binding.values[0], field),
        evidence_requirements=(f"property.inventory.{seconds}",),
    )
    return OperatorResult(specs=(spec,), limitations=(f"{PROPERTY_SOURCE_LIMITATION}:{seconds}",))


def property_field(
    value: str,
    reads: tuple[ReviewedPropertyRead, ...],
    resource_type: str | None,
    readable: frozenset[str],
) -> str:
    """Return the one projected field for a grounded property, or why none applies."""

    if value.startswith(_DECLARED_PREFIX):
        name = value.removeprefix(_DECLARED_PREFIX)
        return f"properties.{name}" if name in readable else "property_unreadable"
    read = next((item for item in reads if item.semantic_id == value), None)
    if read is None or _PROVIDER_BAG not in readable:
        return "property_unreviewed" if read is None else "property_unreadable"
    if read.max_age_seconds < INVENTORY_FRESHNESS_SECONDS:
        return "property_freshness_unestablished"
    if resource_type is None:
        return "property_type_unbound"
    path = dict(read.paths).get(resource_type)
    if path is None:
        return "property_type_unsupported"
    return f"properties.{_PROVIDER_BAG}.{path}"


def property_freshness(value: str, reads: tuple[ReviewedPropertyRead, ...]) -> int:
    read = next((item for item in reads if item.semantic_id == value), None)
    return read.max_age_seconds if read is not None else INVENTORY_FRESHNESS_SECONDS


def projected_fields(field: str, readable: frozenset[str]) -> tuple[str, ...]:
    identity = tuple(
        item
        for item in _IDENTITY_FIELDS
        if item == "id" or item.removeprefix("properties.") in readable
    )
    return tuple(dict.fromkeys((*identity, field)))


def expected_property_fields(
    goal: FormGoal,
    *,
    admission: FormAdmission,
    concepts: ConceptSelectionReceipt,
    anchors: AnchorBindingReceipt,
    reads: tuple[ReviewedPropertyRead, ...],
    readable: frozenset[str],
) -> tuple[str, ...] | None:
    """Recompute the projection a property lookup must read, from bindings alone."""

    measure = goal.measure
    if not is_property_lookup(goal) or measure is None or measure.mention is None:
        return None
    if admission.form.mention(measure.mention).domain is not MentionDomain.PROPERTY:
        return None
    binding = concepts.binding(measure.mention)
    if binding is None or binding.outcome is not ConceptOutcome.ACCEPTED:
        return None
    if len(binding.values) != 1 or goal.subject is None:
        return None
    anchor = anchors.binding(goal.subject)
    resource_type = anchor.resource_type if anchor is not None else None
    field = property_field(binding.values[0], reads, resource_type, readable)
    return projected_fields(field, readable) if field.startswith("properties.") else None


def property_read_violations(
    plans: Sequence[OntologyQueryPlan], expected_anchor: str | None
) -> list[str]:
    """V-SEM: a property lookup reads only one projection over its exact anchor read."""

    nodes = {node.node_id: node for plan in plans for node in plan.nodes}
    outputs = [nodes[item] for plan in plans for item in plan.output_node_ids if item in nodes]
    project = outputs[0] if len(outputs) == 1 else None
    source = (
        nodes.get(project.depends_on[0])
        if project is not None
        and project.kind is QueryNodeKind.PROJECT
        and len(project.depends_on) == 1
        else None
    )
    predicates = (
        (source.arguments.get("definition") or {}).get("predicates")
        if source is not None and source.kind is QueryNodeKind.OBJECT_SET
        else None
    )
    anchored = expected_anchor is not None and predicates == [
        {"property": "id", "operator": "equals", "equals": expected_anchor}
    ]
    return [] if anchored and len(nodes) == 2 else ["sem_property_read_missing"]


def _readable_properties(ctx: CompileContext) -> frozenset[str]:
    return readable_resource_properties(ctx.manifest.descriptors)


def readable_resource_properties(descriptors: tuple[dict[str, object], ...]) -> frozenset[str]:
    resource = next(
        (
            item
            for item in descriptors
            if item.get("kind") == "object" and item.get("name") == RESOURCE_OBJECT_TYPE
        ),
        None,
    )
    properties = resource.get("properties") if resource is not None else None
    return frozenset(properties) if isinstance(properties, dict) else frozenset()


__all__ = [
    "INVENTORY_FRESHNESS_SECONDS",
    "PROPERTY_SOURCE_LIMITATION",
    "expected_property_fields",
    "is_property_lookup",
    "projected_fields",
    "property_field",
    "property_freshness",
    "property_lookup",
    "property_read_violations",
    "readable_resource_properties",
]
