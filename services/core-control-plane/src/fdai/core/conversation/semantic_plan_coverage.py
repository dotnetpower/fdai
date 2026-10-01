"""Check that a verified current-path plan reads what the question was read to ask.

The judgment's coverage review proves that the judgment quoted every stated constraint,
but the frame and plan built from that judgment can still drop one: a per-group count
planned as one ungrouped count, or a region question planned as a list of every Resource
of that kind. These checks compare closed structure only, never words. A plan that reads
only a filtered list has no function, metric, path, order, grouping, or predicate beyond
kind, name, and identity; a reading that asks more than such a list, or a blind reading
that states a grouping or a relation, is then not what the plan answers. A plan that reads
only ontology declarations answers what a type declares, never a state, value, location,
history, or cause of an instance that the blind reading says the question asks.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
)

from .semantic_operand_provenance import (
    IdentityBindingReceipt,
    ProvenanceScope,
    unproven_identity_operands,
)
from .semantic_planning_models import (
    SemanticPlanningDisposition,
    SemanticPlanningOutcome,
    hold_details,
)
from .semantic_planning_support import _outcome
from .semantic_reasoning_review import AnswerKind, ConstraintExtraction, ConstraintRole

_LOGGER = logging.getLogger(__name__)

PLAN_CONSTRAINT_UNCOVERED = "semantic_plan_constraint_uncovered"
PLAN_READING_UNVERIFIED = "semantic_reading_unverified"
PLAN_OPERAND_WITHOUT_SOURCE = "semantic_operand_without_source"
# Declaration reads answer what the ontology declares, never what an instance is or did.
_DECLARATION_READERS = frozenset(
    {"query.manifest", "query.ontology_declaration", "query.ontology_relationships"}
)
_DERIVED_KINDS = frozenset({QueryNodeKind.AGGREGATE, QueryNodeKind.UNION, QueryNodeKind.PROJECT})
# Kinds only an instance read answers; a declaration read answers a schema, list, count,
# or relation question.
_INSTANCE_ANSWERS = frozenset(
    {
        AnswerKind.STATE,
        AnswerKind.VALUE,
        AnswerKind.LOCATION,
        AnswerKind.HISTORY,
        AnswerKind.CAUSE,
    }
)
# Properties a filtered list reads: its kind, a name part, an identity, and its container.
_LIST_PROPERTIES = frozenset({"type", "name", "id", "parent_id"})
_CONTAINMENT = "contains"
_CONTAINER = "properties.parent_id"
# Node kinds that follow links or read a relation inside a reviewed function.
_RELATIONAL_KINDS = frozenset(
    {
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        QueryNodeKind.TYPED_PATH,
        QueryNodeKind.ONTOLOGY_INSTANCE_PATH,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.TOPOLOGY_AT,
        QueryNodeKind.TOPOLOGY_DIFF,
        QueryNodeKind.EVIDENCE_JOIN,
    }
)


class PlanVeto(Protocol):
    def veto(
        self,
        plan_source: str,
        *,
        manifest_digest: str,
        plan: OntologyQueryPlan | None = None,
    ) -> SemanticPlanningOutcome | None: ...


class BlindReading(Protocol):
    def settled_reading(self) -> ConstraintExtraction | None: ...


class SlotBearingFrame(Protocol):
    constraint_slots: tuple[Any, ...]


def narrower_plan_outcome(
    ticket: PlanVeto | None,
    coverage: BlindReading | None,
    plan_source: str,
    plan: OntologyQueryPlan,
    manifest_digest: str,
    utterance: str = "",
    context: Sequence[str] = (),
    enforce_when: object = True,
    identity_receipts: Sequence[IdentityBindingReceipt] = (),
    *,
    frame: SlotBearingFrame | None = None,
) -> SemanticPlanningOutcome | None:
    """Return the hold for a current-path plan that reads less than the question asks.

    The form path's veto runs first; then a grouping or relation the judgment's blind
    reading states must shape the plan, or the turn holds with that closed role.
    """

    vetoed = (
        ticket.veto(plan_source, manifest_digest=manifest_digest, plan=plan)
        if ticket is not None
        else None
    )
    if vetoed is not None:
        return vetoed
    output_ids = set(getattr(plan, "output_node_ids", tuple(node.node_id for node in plan.nodes)))
    scope = enforce_when if isinstance(enforce_when, ProvenanceScope) else None
    receipts = (*identity_receipts, *(scope.receipts if scope is not None else ()))
    if scope is not None:
        utterance, context = scope.utterance or utterance, scope.context or context
    if (
        (scope.enforced if scope is not None else enforce_when is not None)
        # Document evidence appended to a model plan renames its source, not its operands.
        and plan_source.split("+", 1)[0] == "proposed"
        and any(
            node.output_kind == "query.table" for node in plan.nodes if node.node_id in output_ids
        )
    ):
        unproven = unproven_identity_operands(
            plan, utterance=utterance, context=context, receipts=receipts
        )
        if unproven:
            return _outcome(
                SemanticPlanningDisposition.UNAVAILABLE,
                PLAN_OPERAND_WITHOUT_SOURCE,
                manifest_digest=manifest_digest,
                hold_details=hold_details(("identity:unproven",)),
            )
    reading = coverage.settled_reading() if coverage is not None else None
    asked = plan_answers_schema_for_instance(reading, plan)
    if asked is not None:
        _LOGGER.info(
            "semantic_plan_level_differs",
            extra={"plan_source": plan_source, "answer_kind": asked.value},
        )
        return _outcome(
            SemanticPlanningDisposition.UNAVAILABLE,
            PLAN_READING_UNVERIFIED,
            manifest_digest=manifest_digest,
            hold_details=hold_details((f"answer_kind:{asked.value}",)),
        )
    roles = (*plan_uncovered_roles(reading, plan), *plan_uncovered_slot_roles(frame, plan))
    if not roles:
        return None
    _LOGGER.info(
        "semantic_plan_constraint_uncovered",
        extra={"plan_source": plan_source, "roles": list(roles)},
    )
    return _outcome(
        SemanticPlanningDisposition.UNAVAILABLE,
        PLAN_CONSTRAINT_UNCOVERED,
        manifest_digest=manifest_digest,
        hold_details=hold_details(f"role:{role}" for role in roles),
    )


def plan_reads_only_a_list(plan: OntologyQueryPlan) -> bool:
    """Return whether the plan can only answer a filtered Resource list or its row count.

    Every node reads objects by kind, name part, identity, or container, unites such
    reads, projects their fields, or counts them without a grouping; nothing else.
    """

    return all(_list_node(node) for node in plan.nodes)


def plan_uncovered_roles(
    extraction: ConstraintExtraction | None, plan: OntologyQueryPlan
) -> tuple[str, ...]:
    """Return the closed roles a blind reading states that the plan's structure never reads.

    A stated grouping needs a grouped aggregate, and a stated relation needs a read that
    follows links or a container: a traversal, a typed path, a function, or a grouping or
    filter by container. Restrictions stay with the judgment's coverage review, because
    two readers may fairly disagree on whether a word restricts or names the kind read.
    """

    if extraction is None:
        return ()
    roles = {item.role for item in extraction.constraints}
    uncovered: list[str] = []
    if ConstraintRole.GROUPS in roles and not any(_grouped(node) for node in plan.nodes):
        uncovered.append(ConstraintRole.GROUPS.value)
    if ConstraintRole.RELATES in roles and not any(_relational(node) for node in plan.nodes):
        uncovered.append(ConstraintRole.RELATES.value)
    return tuple(uncovered)


def plan_uncovered_slot_roles(
    frame: SlotBearingFrame | None, plan: OntologyQueryPlan
) -> tuple[str, ...]:
    if frame is None:
        return ()
    uncovered: list[str] = []
    for slot in frame.constraint_slots:
        if not slot.grounded:
            continue
        role = slot.role.value
        if role == "group_by" and not any(_grouped(node) for node in plan.nodes):
            uncovered.append(role)
        elif role == "relation_path" and not any(_relational(node) for node in plan.nodes):
            uncovered.append(role)
        elif role == "time_window" and not any(_windowed(node.arguments) for node in plan.nodes):
            uncovered.append(role)
        elif role in _VALUE_SLOT_PROPERTIES and not any(
            _restricts(node, _VALUE_SLOT_PROPERTIES[role], str(slot.value)) for node in plan.nodes
        ):
            # A slot that covered a stated restriction must restrict the plan the same way.
            uncovered.append(role)
    return tuple(dict.fromkeys(uncovered))


# Properties a value slot restricts; an empty set accepts any property carrying the value.
_VALUE_SLOT_PROPERTIES: Mapping[str, frozenset[str]] = {
    "location": frozenset({"location"}),
    "lifecycle_status": frozenset({"status", "state"}),
    "property_predicate": frozenset(),
}
_WINDOW_ARGUMENTS = frozenset(
    {
        "lookback_seconds",
        "window_seconds",
        "start_at",
        "end_at",
        "start",
        "end",
        "before_as_of",
        "after_as_of",
        "as_of",
    }
)


def _windowed(arguments: Mapping[str, Any]) -> bool:
    nested = arguments.get("arguments")
    return bool(_WINDOW_ARGUMENTS & set(arguments)) or (
        isinstance(nested, Mapping) and bool(_WINDOW_ARGUMENTS & set(nested))
    )


def _restricts(node: OntologyQueryNode, properties: frozenset[str], value: str) -> bool:
    """Return whether the node restricts by ``value``, in a predicate or a function argument."""

    arguments = node.arguments
    definition = arguments.get("definition")
    predicates = [
        *(definition.get("predicates") or () if isinstance(definition, Mapping) else ()),
        *(arguments.get("endpoint_predicates") or ()),
    ]
    for item in predicates:
        if not isinstance(item, Mapping):
            continue
        if properties and item.get("property") not in properties:
            continue
        if _carries(item.get("equals"), value) or _carries(item.get("values"), value):
            return True
    nested = arguments.get("arguments")
    return (
        node.kind is QueryNodeKind.FUNCTION
        and isinstance(nested, Mapping)
        and any(_carries(item, value) for item in nested.values())
    )


def _carries(candidate: object, value: str) -> bool:
    if isinstance(candidate, str):
        return candidate.casefold() == value.casefold()
    if isinstance(candidate, list | tuple):
        return any(_carries(item, value) for item in candidate)
    return False


def plan_answers_schema_for_instance(
    extraction: ConstraintExtraction | None, plan: OntologyQueryPlan
) -> AnswerKind | None:
    """Return the instance answer kind a declaration-only plan cannot answer, if any.

    The blind reading names the kind of answer the question asks; a plan that reads only
    ontology declarations answers what a type declares, so a state, value, location,
    history, or cause question it would answer gets a schema answer to an instance target.
    """

    if extraction is None or extraction.answer_kind not in _INSTANCE_ANSWERS:
        return None
    functions = [node for node in plan.nodes if node.kind is QueryNodeKind.FUNCTION]
    declaration_only = bool(functions) and all(
        node.kind in _DERIVED_KINDS
        or (
            node.kind is QueryNodeKind.FUNCTION
            and node.arguments.get("function_name") in _DECLARATION_READERS
        )
        for node in plan.nodes
    )
    return extraction.answer_kind if declaration_only else None


def _list_node(node: OntologyQueryNode) -> bool:
    arguments = node.arguments
    if node.kind in {QueryNodeKind.UNION, QueryNodeKind.PROJECT}:
        return True
    if node.kind is QueryNodeKind.AGGREGATE:
        return arguments.get("operation") == "count" and not arguments.get("group_by")
    if node.kind is QueryNodeKind.OBJECT_SET:
        definition = arguments.get("definition")
        if not isinstance(definition, Mapping) or definition.get("traversal") is not None:
            return False
        return _list_predicates(definition.get("predicates", ()))
    if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL:
        # A containment read from a named container to its members only restates a scope;
        # a read from a member to what contains it answers where the member is.
        return (
            list(arguments.get("link_types", ())) == [_CONTAINMENT]
            and arguments.get("direction") == "outgoing"
            and _list_predicates(arguments.get("endpoint_predicates", ()))
        )
    return False


def _list_predicates(predicates: Any) -> bool:
    if not isinstance(predicates, Iterable) or isinstance(predicates, str | bytes | Mapping):
        return False
    return all(
        isinstance(item, Mapping) and item.get("property") in _LIST_PROPERTIES
        for item in predicates
    )


def _grouped(node: OntologyQueryNode) -> bool:
    return node.kind is QueryNodeKind.AGGREGATE and bool(node.arguments.get("group_by"))


def _relational(node: OntologyQueryNode) -> bool:
    """Return whether one node reads a relation: a link, a path, or a container."""

    if node.kind in _RELATIONAL_KINDS:
        return True
    arguments = node.arguments
    if node.kind is QueryNodeKind.AGGREGATE:
        return _CONTAINER in (arguments.get("group_by") or ())
    if node.kind is QueryNodeKind.OBJECT_SET:
        definition = arguments.get("definition")
        return isinstance(definition, Mapping) and (
            definition.get("traversal") is not None
            or any(
                isinstance(item, Mapping) and item.get("property") == "parent_id"
                for item in definition.get("predicates") or ()
            )
        )
    return False


__all__ = [
    "PLAN_CONSTRAINT_UNCOVERED",
    "PLAN_READING_UNVERIFIED",
    "BlindReading",
    "PlanVeto",
    "narrower_plan_outcome",
    "plan_answers_schema_for_instance",
    "plan_reads_only_a_list",
    "plan_uncovered_roles",
]
