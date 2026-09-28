"""Independent semantic, provenance, and level verification for compiled goals.

The verifier never trusts the compiler. It recomputes the reads each admitted
goal requires from the form, the accepted concept bindings, the reviewed
manifest, and server policy, then rejects any plan that adds, drops, broadens,
or invents an operand.

- V-SEM: every relation side, filter, operation, and measure atom maps to the
  node pattern its rule requires, across every plan batch of the goal.
- V-PROV: every identity or literal operand cites an exact mention span, an
  accepted concept binding, or a reviewed server policy value.
- V-LEVEL: an instance goal never reads schema-only functions, and a schema goal
  never reads instances.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
)

from .semantic_reasoning_admission import FormAdmission
from .semantic_reasoning_binding import AnchorBindingReceipt, AnchorOutcome
from .semantic_reasoning_concepts import ConceptOutcome, ConceptSelectionReceipt
from .semantic_reasoning_form import (
    SENSE_ROLES,
    DurationUnit,
    FilterRole,
    FormGoal,
    GoalLevel,
    GoalOperation,
    MentionDomain,
    RelationReach,
    RelationScope,
    RelationSense,
    SubjectPosition,
    SubjectRole,
    TimeKind,
)
from .semantic_reasoning_relations import SENSE_TRAITS
from .semantic_resource_visibility import OPERATIONAL_RESOURCE_EXCLUDED_TYPES

_SCHEMA_ONLY_FUNCTIONS = frozenset(
    {
        "query.manifest",
        "query.ontology_declaration",
        "query.ontology_relationships",
        "query.ontology_evidence_health",
        "query.ontology_release_diff",
    }
)
_INSTANCE_READ_KINDS = frozenset(
    {
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        QueryNodeKind.TYPED_PATH,
        QueryNodeKind.ONTOLOGY_INSTANCE_PATH,
    }
)
_SECONDS = {
    DurationUnit.MINUTE: 60,
    DurationUnit.HOUR: 3_600,
    DurationUnit.DAY: 86_400,
    DurationUnit.WEEK: 604_800,
}
_TRANSITIVE_DEPTH = 5
_REQUIRED_FUNCTIONS: Mapping[tuple[GoalLevel, GoalOperation], frozenset[str]] = {
    (GoalLevel.INSTANCE, GoalOperation.LOOKUP): frozenset({"query.resource_current_state"}),
    (GoalLevel.INSTANCE, GoalOperation.HISTORY): frozenset({"query.resource_change_activity"}),
    (GoalLevel.SCHEMA, GoalOperation.DESCRIBE_SCHEMA): frozenset(
        {"query.ontology_declaration", "query.ontology_relationships"}
    ),
    (GoalLevel.SCHEMA, GoalOperation.TRAVERSE): frozenset({"query.ontology_relationships"}),
    (GoalLevel.SCHEMA, GoalOperation.SELECT): frozenset({"query.manifest"}),
    (GoalLevel.SCHEMA, GoalOperation.COUNT): frozenset({"query.manifest"}),
}


def verify_goal_semantics(
    goal: FormGoal,
    *,
    admission: FormAdmission,
    concepts: ConceptSelectionReceipt,
    descriptors: Sequence[Mapping[str, Any]],
    plans: Sequence[OntologyQueryPlan],
    default_lookback_seconds: int,
    anchors: AnchorBindingReceipt | None = None,
) -> tuple[str, ...]:
    """Return every V-SEM, V-PROV, and V-LEVEL violation for one goal."""

    if not plans:
        return ("sem_no_plan",)
    nodes = tuple(node for plan in plans for node in plan.nodes)
    violations = [*_level_violations(goal, nodes)]
    allowed = _allowed_operands(
        goal, admission=admission, concepts=concepts, anchors=anchors or AnchorBindingReceipt()
    )
    for node in nodes:
        violations.extend(_operand_violations(node, allowed, goal, default_lookback_seconds))
    violations.extend(_coverage_violations(goal, plans, allowed, descriptors, admission))
    return tuple(dict.fromkeys(violations))


def _level_violations(goal: FormGoal, nodes: Iterable[OntologyQueryNode]) -> list[str]:
    violations: list[str] = []
    for node in nodes:
        function = _function_name(node)
        if goal.level is GoalLevel.SCHEMA:
            if node.kind in _INSTANCE_READ_KINDS or (
                function is not None and function not in _SCHEMA_ONLY_FUNCTIONS
            ):
                violations.append(f"level_schema_reads_instances:{node.node_id}")
        elif function in _SCHEMA_ONLY_FUNCTIONS:
            violations.append(f"level_instance_reads_schema:{node.node_id}")
    return violations


class _Allowed:
    """Operand provenance sets derived from the admitted goal alone."""

    def __init__(self) -> None:
        self.anchor_ids: set[str] = set()
        self.fragments: set[str] = set()
        self.type_values: set[str] = set()
        self.object_types: set[str] = set()
        self.declaration_kinds: set[str] = set()
        self.relation_object_type = False


def _allowed_operands(
    goal: FormGoal,
    *,
    admission: FormAdmission,
    concepts: ConceptSelectionReceipt,
    anchors: AnchorBindingReceipt,
) -> _Allowed:
    allowed = _Allowed()
    cited = [goal.subject] if goal.subject is not None else []
    cited.extend(item.mention for item in goal.filters)
    if goal.relation is not None and goal.relation.anchor is not None:
        cited.append(goal.relation.anchor)
        subject = admission.form.mention(goal.subject) if goal.subject is not None else None
        allowed.relation_object_type = (
            subject is not None
            and subject.domain is MentionDomain.OBJECT_TYPE
            and not goal.restated_subject
        )
    for mention_id in cited:
        mention = admission.form.mention(mention_id)
        text = admission.mention_text[mention_id]
        role = next((item.role for item in goal.filters if item.mention == mention_id), None)
        if mention.domain is MentionDomain.INSTANCE:
            if role is FilterRole.NAME_FRAGMENT:
                allowed.fragments.add(text)
                continue
            anchor = anchors.binding(mention_id)
            if anchor is not None and anchor.outcome is AnchorOutcome.BOUND:
                allowed.anchor_ids.add(str(anchor.object_id))
            continue
        concept = concepts.binding(mention_id)
        if concept is None or concept.outcome is not ConceptOutcome.ACCEPTED:
            continue
        if mention.domain in {MentionDomain.RESOURCE_TYPE, MentionDomain.RESOURCE_CLASS}:
            allowed.type_values.update(concept.values)
        elif mention.domain is MentionDomain.OBJECT_TYPE:
            allowed.object_types.update(concept.values)
        elif mention.domain is MentionDomain.DECLARATION_KIND:
            allowed.declaration_kinds.update(concept.values)
    return allowed


def _operand_violations(
    node: OntologyQueryNode,
    allowed: _Allowed,
    goal: FormGoal,
    default_lookback_seconds: int,
) -> list[str]:
    arguments = node.arguments
    if node.kind is QueryNodeKind.OBJECT_SET:
        definition = arguments.get("definition") or {}
        if definition.get("object_ids") is not None or definition.get("root_ids"):
            return [f"prov_explicit_identity:{node.node_id}"]
        return _predicate_violations(node.node_id, definition.get("predicates") or (), allowed)
    if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL:
        return _predicate_violations(
            node.node_id, arguments.get("endpoint_predicates") or (), allowed
        )
    if node.kind is QueryNodeKind.FUNCTION:
        return _function_violations(node, allowed, goal, default_lookback_seconds)
    if node.kind in {QueryNodeKind.AGGREGATE, QueryNodeKind.UNION}:
        return []
    return [f"prov_unexpected_node:{node.node_id}:{node.kind.value}"]


def _predicate_violations(
    node_id: str,
    predicates: Iterable[Mapping[str, Any]],
    allowed: _Allowed,
) -> list[str]:
    violations: list[str] = []
    for predicate in predicates:
        prop = predicate.get("property")
        operator = predicate.get("operator")
        operands = (
            list(predicate.get("values") or ()) if operator == "in" else [predicate.get("equals")]
        )
        if any(_all_zero(item) for item in operands):
            violations.append(f"prov_all_zero_identifier:{node_id}")
            continue
        if prop == "id" and operator == "equals":
            permitted: set[str] = allowed.anchor_ids
        elif prop == "name" and operator == "contains":
            permitted = allowed.fragments
        elif prop == "type" and operator in {"equals", "in"}:
            permitted = allowed.type_values
        elif prop == "type" and operator == "not_equals":
            permitted = set(OPERATIONAL_RESOURCE_EXCLUDED_TYPES)
        else:
            violations.append(f"prov_unexpected_predicate:{node_id}:{prop}:{operator}")
            continue
        if any(not isinstance(item, str) or item not in permitted for item in operands):
            violations.append(f"prov_operand_without_source:{node_id}:{prop}")
    return violations


def _function_violations(
    node: OntologyQueryNode,
    allowed: _Allowed,
    goal: FormGoal,
    default_lookback_seconds: int,
) -> list[str]:
    name = _function_name(node)
    static = node.arguments.get("arguments") or {}
    expected: Mapping[str, Any] | None
    if name == "query.resource_current_state":
        expected = {}
    elif name == "query.resource_change_activity":
        expected = {"lookback_seconds": _expected_lookback(goal, default_lookback_seconds)}
    elif name == "query.ontology_declaration":
        names = sorted(allowed.object_types)
        expected = (
            {"kind": "object", "name": names[0], "section": "detail", "limit": 100}
            if len(names) == 1
            else None
        )
    elif name == "query.ontology_relationships":
        expected = {"object_types": sorted(allowed.object_types), "limit": 100}
    elif name == "query.manifest":
        expected = {"kinds": sorted(allowed.declaration_kinds), "limit": 1000}
    else:
        return [f"prov_unexpected_function:{node.node_id}:{name}"]
    if expected is None or dict(static) != dict(expected):
        return [f"prov_function_arguments:{node.node_id}"]
    return []


def _coverage_violations(
    goal: FormGoal,
    plans: Sequence[OntologyQueryPlan],
    allowed: _Allowed,
    descriptors: Sequence[Mapping[str, Any]],
    admission: FormAdmission,
) -> list[str]:
    violations: list[str] = []
    outputs = [
        node for plan in plans for node in plan.nodes if node.node_id in plan.output_node_ids
    ]
    if goal.effective_operation is GoalOperation.COUNT and not all(
        node.kind is QueryNodeKind.AGGREGATE and node.arguments.get("operation") == "count"
        for node in outputs
    ):
        violations.append("sem_count_not_aggregated")
    functions = {
        name for plan in plans for node in plan.nodes if (name := _function_name(node)) is not None
    }
    required = _REQUIRED_FUNCTIONS.get((goal.level, goal.effective_operation))
    if required is not None and functions.isdisjoint(required):
        violations.append("sem_operation_read_missing")
    if goal.level is GoalLevel.INSTANCE:
        violations.extend(_filter_coverage(goal, plans, allowed))
    if goal.level is GoalLevel.INSTANCE and (
        goal.relation is not None or goal.effective_operation is GoalOperation.IMPACT
    ):
        expected = _expected_sides(goal, descriptors, allowed, admission)
        compiled = {
            (str(node.arguments["link_types"][0]), str(node.arguments["direction"]))
            for plan in plans
            for node in plan.nodes
            if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL
        }
        if compiled != expected:
            violations.append("sem_relation_sides_differ")
        reach = (
            goal.relation.reach
            if goal.relation is not None and goal.effective_operation is not GoalOperation.IMPACT
            else RelationReach.ONE_HOP
        )
        depth = _TRANSITIVE_DEPTH if reach is RelationReach.TRANSITIVE else 1
        if any(
            node.arguments.get("max_depth") != depth
            for plan in plans
            for node in plan.nodes
            if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL
        ):
            violations.append("sem_relation_reach_differs")
    return violations


def _filter_coverage(
    goal: FormGoal,
    plans: Sequence[OntologyQueryPlan],
    allowed: _Allowed,
) -> list[str]:
    """Require every restrictive filter on every result read of the goal."""

    violations: list[str] = []
    reads = [
        _result_predicates(node)
        for plan in plans
        for node in plan.nodes
        if _is_result_read(node, plan)
    ]
    for predicates in reads:
        if allowed.type_values and not any(
            item.get("property") == "type"
            and item.get("operator") in {"equals", "in"}
            and set(item.get("values") or [item.get("equals")]) == allowed.type_values
            for item in predicates
        ):
            violations.append("sem_type_filter_missing")
        for fragment in allowed.fragments:
            if {"property": "name", "operator": "contains", "equals": fragment} not in predicates:
                violations.append("sem_name_fragment_missing")
    return violations


def _is_result_read(node: OntologyQueryNode, plan: OntologyQueryPlan) -> bool:
    if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL:
        return bool(node.arguments.get("selector", {}).get("name") == "Resource")
    if node.kind is not QueryNodeKind.OBJECT_SET:
        return False
    dependents = [item for item in plan.nodes if node.node_id in item.depends_on]
    return not any(item.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL for item in dependents) and (
        not any(item.kind is QueryNodeKind.FUNCTION for item in dependents)
    )


def _result_predicates(node: OntologyQueryNode) -> list[Mapping[str, Any]]:
    if node.kind is QueryNodeKind.OBJECT_SET:
        return list((node.arguments.get("definition") or {}).get("predicates") or ())
    return list(node.arguments.get("endpoint_predicates") or ())


def _expected_sides(
    goal: FormGoal,
    descriptors: Sequence[Mapping[str, Any]],
    allowed: _Allowed,
    admission: FormAdmission,
) -> set[tuple[str, str]] | None:
    """Recompute every stored side the anchored relation of ``goal`` requires."""

    anchored = _anchor_end(goal, admission)
    if anchored is None:
        return None
    position, sense, scope, reach = anchored
    trait = SENSE_TRAITS[sense] if sense is not None else None
    restrictive = bool(allowed.type_values or allowed.fragments)
    wanted = next(iter(allowed.object_types), None) if allowed.relation_object_type else None
    wanted = wanted or ("Resource" if restrictive else None)
    expected: set[tuple[str, str]] = set()
    for descriptor in descriptors:
        if descriptor.get("kind") != "link":
            continue
        source, target = descriptor.get("from_type"), descriptor.get("to_type")
        traits = set(descriptor.get("semantic_traits") or ())
        if scope is RelationScope.ONE_SENSE and (trait is None or trait not in traits):
            continue
        if reach is RelationReach.TRANSITIVE and not (
            descriptor.get("is_transitive") is True and source == target
        ):
            continue
        name = str(descriptor.get("name"))
        if position in {SubjectPosition.SOURCE, SubjectPosition.EITHER} and (
            source == "Resource" and (wanted is None or target == wanted)
        ):
            expected.add((name, "outgoing"))
        if position in {SubjectPosition.TARGET, SubjectPosition.EITHER} and (
            target == "Resource" and (wanted is None or source == wanted)
        ):
            expected.add((name, "incoming"))
    return expected


def _anchor_end(
    goal: FormGoal, admission: FormAdmission
) -> tuple[SubjectPosition, RelationSense | None, RelationScope, RelationReach] | None:
    relation = goal.relation
    if goal.effective_operation is GoalOperation.IMPACT:
        return (
            SubjectPosition.TARGET,
            RelationSense.DEPENDENCY,
            RelationScope.ONE_SENSE,
            RelationReach.ONE_HOP,
        )
    if relation is None:
        return None
    source_role, target_role = SENSE_ROLES[relation.sense]
    if relation.anchor_role is SubjectRole.EITHER and relation.result_role is SubjectRole.EITHER:
        position = SubjectPosition.EITHER
    elif (relation.anchor_role, relation.result_role) == (source_role, target_role):
        position = SubjectPosition.SOURCE
    elif (relation.anchor_role, relation.result_role) == (target_role, source_role):
        position = SubjectPosition.TARGET
    else:
        return None
    sense = relation.sense if relation.scope is RelationScope.ONE_SENSE else None
    return position, sense, relation.scope, relation.reach


def _expected_lookback(goal: FormGoal, default_seconds: int) -> int | None:
    if goal.time.kind in {TimeKind.CURRENT, TimeKind.UNSPECIFIED}:
        return default_seconds
    value = goal.time.value
    if goal.time.kind is not TimeKind.WINDOW or value is None or value.duration is None:
        return None
    return value.duration.amount * _SECONDS[value.duration.unit]


def _function_name(node: OntologyQueryNode) -> str | None:
    if node.kind is not QueryNodeKind.FUNCTION:
        return None
    name = node.arguments.get("function_name")
    return name if isinstance(name, str) else None


def _all_zero(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    stripped = value.replace("-", "").replace("0", "")
    return not stripped and "0" in value


__all__ = ["verify_goal_semantics"]
