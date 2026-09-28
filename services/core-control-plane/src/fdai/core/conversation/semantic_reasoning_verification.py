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
    GroupBy,
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
    (GoalLevel.SCHEMA, GoalOperation.SELECT): frozenset(
        {"query.manifest", "query.ontology_relationships"}
    ),
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
    violations.extend(
        _coverage_violations(
            goal, plans, allowed, descriptors, admission, anchors or AnchorBindingReceipt()
        )
    )
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
        self.type_sets: list[frozenset[str]] = []
        self.object_types: set[str] = set()
        self.declaration_kinds: set[str] = set()
        self.relation_object_type = False

    @property
    def required_types(self) -> frozenset[str]:
        """Return the intersection every stated kind restriction requires."""

        return frozenset.intersection(*self.type_sets) if self.type_sets else frozenset()


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
            if concept.values:
                allowed.type_sets.append(frozenset(concept.values))
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
            permitted = set(allowed.required_types)
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
    anchors: AnchorBindingReceipt,
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
    if goal.level is GoalLevel.SCHEMA:
        violations.extend(_schema_violations(goal, functions, admission))
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
        expected_anchor = _expected_anchor_id(goal, anchors)
        if expected_anchor is None or _traversal_roots(plans) != {expected_anchor}:
            violations.append("sem_relation_anchor_differs")
    elif goal.level is GoalLevel.INSTANCE and any(
        item.role is FilterRole.SCOPE for item in goal.filters
    ):
        scope = next(item.mention for item in goal.filters if item.role is FilterRole.SCOPE)
        compiled_scope = {
            (
                str(node.arguments["link_types"][0]),
                str(node.arguments["direction"]),
                node.arguments.get("max_depth"),
            )
            for plan in plans
            for node in plan.nodes
            if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL
        }
        if compiled_scope != _containment_scope_sides(descriptors):
            violations.append("sem_scope_containment_differs")
        binding = anchors.binding(scope)
        scope_id = binding.object_id if binding is not None else None
        if scope_id is None or _traversal_roots(plans) != {scope_id}:
            violations.append("sem_scope_anchor_differs")
    return violations


def _schema_violations(goal: FormGoal, functions: set[str], admission: FormAdmission) -> list[str]:
    """Return the stated schema relation or grouping that no declaration read answers.

    A schema relation is answered only by the one-hop relationship read of the subject
    ObjectType's own LinkTypes, and a manifest count groups only by declaration kind.
    """

    violations: list[str] = []
    relation = goal.relation
    if relation is not None:
        subject = admission.form.mention(goal.subject) if goal.subject is not None else None
        if (
            subject is None
            or subject.domain is not MentionDomain.OBJECT_TYPE
            or relation.scope is not RelationScope.ALL_KINDS
            or relation.reach is not RelationReach.ONE_HOP
            or relation.anchor not in {None, goal.subject}
            or "query.ontology_relationships" not in functions
        ):
            violations.append("sem_schema_relation_unread")
    if goal.measure is not None and goal.measure.group_by not in {GroupBy.NONE, GroupBy.TYPE}:
        violations.append("sem_schema_group_by_unread")
    return violations


def _expected_anchor_id(goal: FormGoal, anchors: AnchorBindingReceipt) -> str | None:
    relation = goal.relation
    mention = relation.anchor if relation is not None and relation.anchor else goal.subject
    binding = anchors.binding(mention) if mention is not None else None
    if binding is None or binding.outcome is not AnchorOutcome.BOUND:
        return None
    return binding.object_id


def _traversal_roots(plans: Sequence[OntologyQueryPlan]) -> set[str]:
    """Return the exact anchor identity each traversal of the goal starts from."""

    roots: set[str] = set()
    for plan in plans:
        by_id = {node.node_id: node for node in plan.nodes}
        for node in plan.nodes:
            if node.kind is not QueryNodeKind.RELATIONSHIP_TRAVERSAL:
                continue
            source = by_id.get(node.depends_on[0]) if node.depends_on else None
            definition = (
                (source.arguments.get("definition") or {})
                if source is not None and source.kind is QueryNodeKind.OBJECT_SET
                else {}
            )
            identities = [
                item.get("equals")
                for item in definition.get("predicates") or ()
                if item.get("property") == "id" and item.get("operator") == "equals"
            ]
            roots.add(str(identities[0]) if len(identities) == 1 else "<unbound>")
    return roots


def _containment_scope_sides(
    descriptors: Sequence[Mapping[str, Any]],
) -> set[tuple[str, str, Any]]:
    trait = SENSE_TRAITS[RelationSense.CONTAINMENT]
    return {
        (str(item.get("name")), "outgoing", _TRANSITIVE_DEPTH)
        for item in descriptors
        if item.get("kind") == "link"
        and trait in set(item.get("semantic_traits") or ())
        and item.get("is_transitive") is True
        and item.get("from_type") == item.get("to_type") == "Resource"
    }


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
        if allowed.type_sets and not any(
            item.get("property") == "type"
            and item.get("operator") in {"equals", "in"}
            and frozenset(item.get("values") or [item.get("equals")]) == allowed.required_types
            for item in predicates
        ):
            violations.append("sem_type_filter_missing")
        for fragment in allowed.fragments:
            if {"property": "name", "operator": "contains", "equals": fragment} not in predicates:
                violations.append("sem_name_fragment_missing")
    return violations


def _is_result_read(node: OntologyQueryNode, plan: OntologyQueryPlan) -> bool:
    if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL:
        return True
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
    restrictive = bool(allowed.type_sets)
    wanted = next(iter(allowed.object_types), None) if allowed.relation_object_type else None
    wanted = wanted or ("Resource" if restrictive else None)
    named = {
        str(item.get("name"))
        for item in descriptors
        if item.get("kind") == "object" and "name" in (item.get("properties") or {})
    }

    def fits(endpoint: object) -> bool:
        return (wanted is None or endpoint == wanted) and (
            not allowed.fragments or endpoint in named
        )

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
            source == "Resource" and fits(target)
        ):
            expected.add((name, "outgoing"))
        if position in {SubjectPosition.TARGET, SubjectPosition.EITHER} and (
            target == "Resource" and fits(source)
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
