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
from datetime import datetime
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
)

from fdai.core.ontology_platform import ReviewedPropertyRead
from fdai.core.ontology_platform.resource_event_queries import RESOURCE_EVENT_MEASURE_CONCEPTS
from fdai.core.ontology_platform.resource_health_queries import RESOURCE_HEALTH_FUNCTION_NAME
from fdai.core.ontology_platform.resource_state_queries import RESOURCE_STATE_FUNCTION_NAME
from fdai.core.ontology_platform.state_transitions import RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME

from . import semantic_reasoning_comparison_checks as comparison_checks
from . import semantic_reasoning_property_reads as property_read_helpers
from .semantic_reasoning_admission import FormAdmission, relation_reach, restated_relation
from .semantic_reasoning_binding import AnchorBindingReceipt, AnchorOutcome
from .semantic_reasoning_concepts import ConceptOutcome, ConceptSelectionReceipt
from .semantic_reasoning_filter_coverage import (
    StatedRestrictions,
    filter_coverage,
    function_name,
)
from .semantic_reasoning_form import (
    SENSE_ROLES,
    DurationUnit,
    FilterRole,
    FormGoal,
    GoalLevel,
    GoalOperation,
    GroupBy,
    MeasureKind,
    MentionDomain,
    RelationReach,
    RelationScope,
    RelationSense,
    SubjectPosition,
    SubjectRole,
    SubjectScope,
    TimeKind,
)
from .semantic_reasoning_handles import ReferenceReceipt, reference_mention
from .semantic_reasoning_lifecycle import parse_lifecycle
from .semantic_reasoning_measure_checks import (
    expected_measure_arguments,
    is_health_lookup,
    is_state_history,
    metric_scope_violations,
)
from .semantic_reasoning_nodes import GROUP_BY_FIELDS
from .semantic_reasoning_relations import SENSE_TRAITS
from .semantic_resource_visibility import OPERATIONAL_RESOURCE_EXCLUDED_TYPES
from .semantic_target_health import TARGET_HEALTH_FUNCTIONS

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
METRIC_READER = "query.resource_metric_inventory"
# The reviewed default window a current metric question reads, and the reader's lower bound.
_DEFAULT_METRIC_WINDOW_SECONDS = 900
_MIN_METRIC_WINDOW_SECONDS = 300
_REQUIRED_FUNCTIONS: Mapping[tuple[GoalLevel, GoalOperation], frozenset[str]] = {
    (GoalLevel.INSTANCE, GoalOperation.LOOKUP): frozenset({"query.resource_current_state"}),
    (GoalLevel.INSTANCE, GoalOperation.HISTORY): frozenset({"query.resource_change_activity"}),
    (GoalLevel.INSTANCE, GoalOperation.EXPLAIN_CAUSE): frozenset(
        {"query.resource_current_state", "query.resource_change_activity"}
    ),
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
    references: ReferenceReceipt | None = None,
    evaluation_time: datetime | None = None,
    property_reads: tuple[ReviewedPropertyRead, ...] = (),
) -> tuple[str, ...]:
    """Return every V-SEM, V-PROV, and V-LEVEL violation for one goal.

    ``evaluation_time`` is the trusted compile clock; an absolute read window must end there.
    """

    if not plans:
        return ("sem_no_plan",)
    nodes = tuple(node for plan in plans for node in plan.nodes)
    violations = [*_level_violations(goal, nodes)]
    allowed = _allowed_operands(
        goal, admission=admission, concepts=concepts, anchors=anchors or AnchorBindingReceipt()
    )
    readable_properties = property_read_helpers.readable_resource_properties(
        tuple(dict(item) for item in descriptors)
    )
    allowed.property_fields = property_read_helpers.expected_property_fields(
        goal,
        admission=admission,
        concepts=concepts,
        anchors=anchors or AnchorBindingReceipt(),
        reads=property_reads,
        readable=readable_properties,
    )
    reference_id = reference_mention(admission, goal.id)
    reference = (references or ReferenceReceipt()).binding(reference_id)
    if reference is not None and reference.bound:
        if not (_read_starts_at(goal, reference.mention_id) and len(reference.row_ids) == 1):
            allowed.prior_rows = reference.row_ids
    for node in nodes:
        violations.extend(
            _operand_violations(
                node, allowed, goal, default_lookback_seconds, descriptors, evaluation_time
            )
        )
    violations.extend(
        _coverage_violations(
            goal, plans, allowed, descriptors, admission, anchors or AnchorBindingReceipt()
        )
    )
    violations.extend(comparison_checks.comparison_coverage_violations(goal, plans))
    return tuple(dict.fromkeys(violations))


def _read_starts_at(goal: FormGoal, mention_id: str) -> bool:
    if goal.relation is not None:
        anchor = goal.relation.anchor if goal.relation.anchor is not None else goal.subject
        return anchor == mention_id
    return goal.effective_operation in {
        GoalOperation.LOOKUP,
        GoalOperation.HISTORY,
        GoalOperation.IMPACT,
    }


def _level_violations(goal: FormGoal, nodes: Iterable[OntologyQueryNode]) -> list[str]:
    violations: list[str] = []
    for node in nodes:
        function = function_name(node)
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
        self.state_concepts: set[str] = set()
        # Another ObjectType's grounded lifecycle values, by (ObjectType, property).
        self.lifecycle: dict[tuple[str, str], set[str]] = {}
        self.health_concepts: set[str] = set()
        self.metric_concepts: set[str] = set()
        self.regions: set[str] = set()
        # The exact projection a property lookup must read, recomputed from its bindings.
        self.property_fields: tuple[str, ...] | None = None
        self.relation_object_type = False
        # The rows an earlier answer showed, when an anaphor makes them the goal's subject.
        self.prior_rows: tuple[str, ...] = ()

    @property
    def required_types(self) -> frozenset[str]:
        """Return the intersection every stated kind restriction requires."""

        return frozenset.intersection(*self.type_sets) if self.type_sets else frozenset()

    def stated(self) -> StatedRestrictions:
        return StatedRestrictions(
            kinds_stated=bool(self.type_sets),
            required_types=self.required_types,
            fragments=frozenset(self.fragments),
            prior_rows=self.prior_rows,
            regions=frozenset(self.regions),
            lifecycle={key: frozenset(values) for key, values in self.lifecycle.items()},
            state_concepts=tuple(sorted(self.state_concepts)),
            health_concepts=tuple(sorted(self.health_concepts)),
        )


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
        elif mention.domain is MentionDomain.STATE and role is FilterRole.STATE:
            for value in concept.values:
                lifecycle = parse_lifecycle(value)
                if lifecycle is None:
                    allowed.state_concepts.add(value)
                else:
                    key = (lifecycle.object_type, lifecycle.property_name)
                    allowed.lifecycle.setdefault(key, set()).add(lifecycle.value)
        elif mention.domain is MentionDomain.HEALTH and role is FilterRole.HEALTH:
            allowed.health_concepts.update(concept.values)
        elif mention.domain is MentionDomain.REGION and role is FilterRole.REGION:
            allowed.regions.update(concept.values)
    measure = goal.measure
    if measure is not None and measure.kind is MeasureKind.METRIC and measure.mention is not None:
        mention = admission.form.mention(measure.mention)
        concept = concepts.binding(measure.mention)
        if (
            mention.domain is MentionDomain.METRIC
            and concept is not None
            and concept.outcome is ConceptOutcome.ACCEPTED
        ):
            allowed.metric_concepts.update(concept.values)
    return allowed


def _operand_violations(
    node: OntologyQueryNode,
    allowed: _Allowed,
    goal: FormGoal,
    default_lookback_seconds: int,
    descriptors: Sequence[Mapping[str, Any]] = (),
    evaluation_time: datetime | None = None,
) -> list[str]:
    arguments = node.arguments
    if node.kind is QueryNodeKind.OBJECT_SET:
        definition = arguments.get("definition") or {}
        if definition.get("object_ids") is not None or definition.get("root_ids"):
            return [f"prov_explicit_identity:{node.node_id}"]
        selector = (definition.get("selector") or {}).get("name")
        return _predicate_violations(
            node.node_id, definition.get("predicates") or (), allowed, selector
        )
    if node.kind is QueryNodeKind.RELATIONSHIP_TRAVERSAL:
        return _predicate_violations(
            node.node_id, arguments.get("endpoint_predicates") or (), allowed
        )
    if node.kind is QueryNodeKind.FUNCTION:
        return _function_violations(
            node, allowed, goal, default_lookback_seconds, descriptors, evaluation_time
        )
    if node.kind in {QueryNodeKind.AGGREGATE, QueryNodeKind.UNION}:
        return []
    if node.kind is QueryNodeKind.METRIC_SCOPE_SERIES:
        if goal.effective_operation is GoalOperation.COMPARE_WINDOWS:
            return comparison_checks.comparison_operand_violations(node, goal)
        return metric_scope_violations(node, goal, evaluation_time)
    if node.kind is QueryNodeKind.METRIC_COMPARISON:
        return comparison_checks.comparison_operand_violations(node, goal)
    if node.kind is QueryNodeKind.PROJECT:
        fields = list(allowed.property_fields or ()) or None
        return [] if arguments.get("fields") == fields else [f"prov_property:{node.node_id}"]
    return [f"prov_unexpected_node:{node.node_id}:{node.kind.value}"]


def _predicate_violations(
    node_id: str,
    predicates: Iterable[Mapping[str, Any]],
    allowed: _Allowed,
    selector: object = None,
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
        elif prop == "id" and operator == "in":
            permitted = set(allowed.prior_rows)
        elif prop == "name" and operator == "contains":
            permitted = allowed.fragments
        elif prop == "type" and operator in {"equals", "in"}:
            permitted = set(allowed.required_types)
        elif prop == "location" and operator in {"equals", "in"}:
            permitted = allowed.regions
        elif prop == "type" and operator == "not_equals":
            permitted = set(OPERATIONAL_RESOURCE_EXCLUDED_TYPES)
        elif operator in {"equals", "in"} and any(key[1] == prop for key in allowed.lifecycle):
            # A lifecycle value restricts only its own ObjectType's read.
            permitted = allowed.lifecycle.get((str(selector), str(prop)), set())
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
    descriptors: Sequence[Mapping[str, Any]] = (),
    evaluation_time: datetime | None = None,
) -> list[str]:
    name = function_name(node)
    static = node.arguments.get("arguments") or {}
    measured = expected_measure_arguments(
        name, goal, _expected_lookback(goal, default_lookback_seconds), evaluation_time
    )
    if measured is not None:
        return [] if dict(static) == measured else [f"prov_function_arguments:{node.node_id}"]
    expected: Mapping[str, Any] | None
    if name == "query.resource_current_state":
        expected = {}
    elif name == "query.resource_change_activity":
        expected = {"lookback_seconds": _expected_lookback(goal, default_lookback_seconds)}
    elif name == "query.resource_event_history":
        expected = {
            "event_families": sorted(RESOURCE_EVENT_MEASURE_CONCEPTS),
            "lookback_seconds": _expected_lookback(goal, default_lookback_seconds),
        }
    elif name == "query.recent_resource_changes":
        lookback = _expected_lookback(goal, default_lookback_seconds)
        limit = _declared_maximum(descriptors, name, "limit")
        if (
            lookback is None
            or limit is None
            or evaluation_time is None
            or not _window_matches(static, lookback, limit, evaluation_time)
        ):
            return [f"prov_function_arguments:{node.node_id}"]
        return []
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
    elif name == RESOURCE_STATE_FUNCTION_NAME:
        expected = {"state_concepts": sorted(allowed.state_concepts)}
    elif name == RESOURCE_HEALTH_FUNCTION_NAME:
        health = sorted(allowed.health_concepts)
        expected = {"health_concepts": health, "state_concepts": []} if health else None
    elif name == METRIC_READER:
        window = _expected_metric_window(goal, descriptors)
        expected = (
            {"metric_concepts": sorted(allowed.metric_concepts), "window_seconds": window}
            if allowed.metric_concepts and window is not None
            else None
        )
    else:
        return [f"prov_unexpected_function:{node.node_id}:{name}"]
    if expected is None or dict(static) != dict(expected):
        return [f"prov_function_arguments:{node.node_id}"]
    return []


def _window_matches(
    arguments: Mapping[str, Any], lookback: int, limit: int, evaluation_time: datetime
) -> bool:
    """Return whether an absolute window ends at the trusted clock and spans the lookback."""

    if set(arguments) != {"start_at", "end_at", "known_at", "limit"} or arguments["limit"] != limit:
        return False
    try:
        start, end, known = (
            datetime.fromisoformat(str(arguments[key]))
            for key in ("start_at", "end_at", "known_at")
        )
    except ValueError:
        return False
    if any(item.tzinfo is None for item in (start, end, known)):
        return False
    return end == known == evaluation_time and (end - start).total_seconds() == lookback


def _declared_maximum(
    descriptors: Sequence[Mapping[str, Any]], function_name: str, argument: str
) -> int | None:
    for descriptor in descriptors:
        if descriptor.get("kind") == "function" and descriptor.get("name") == function_name:
            properties = (descriptor.get("input_schema") or {}).get("properties") or {}
            maximum = (properties.get(argument) or {}).get("maximum")
            return maximum if isinstance(maximum, int) and not isinstance(maximum, bool) else None
    return None


def _expected_metric_window(goal: FormGoal, descriptors: Sequence[Mapping[str, Any]]) -> int | None:
    """Re-derive the metric window from the form and the reader's declared bounds."""

    maximum = _declared_maximum(descriptors, METRIC_READER, "window_seconds")
    seconds = _expected_lookback(goal, _DEFAULT_METRIC_WINDOW_SECONDS)
    if maximum is None or seconds is None or not _MIN_METRIC_WINDOW_SECONDS <= seconds <= maximum:
        return None
    return seconds


def _history_reads(goal: FormGoal) -> frozenset[str]:
    """Return the one read a history goal requires: collection changes, events, or activity."""

    if goal.subject_scope is SubjectScope.COLLECTION:
        return frozenset({"query.recent_resource_changes"})
    if goal.measure is not None and goal.measure.kind is MeasureKind.EVENT:
        return frozenset({"query.resource_event_history"})
    if is_state_history(goal):
        return frozenset({RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME})
    return frozenset({"query.resource_change_activity"})


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
        node.kind is QueryNodeKind.AGGREGATE
        and node.arguments.get("operation") in {"count", "count_by_nearest_container"}
        for node in outputs
    ):
        violations.append("sem_count_not_aggregated")
    lineage_group = (
        goal.measure is not None
        and goal.measure.group_by is GroupBy.CONTAINER
        and goal.measure.mention is not None
    )
    grouped = (
        None
        if lineage_group
        else GROUP_BY_FIELDS.get(goal.measure.group_by)
        if goal.measure is not None
        else None
    )
    if (
        goal.level is GoalLevel.INSTANCE
        and goal.effective_operation is GoalOperation.COUNT
        and any(
            (
                node.arguments.get("operation") != "count_by_nearest_container"
                if lineage_group
                else node.arguments.get("group_by", []) != ([grouped] if grouped else [])
            )
            for node in outputs
        )
    ):
        violations.append("sem_group_by_mismatch")
    functions = {
        name for plan in plans for node in plan.nodes if (name := function_name(node)) is not None
    }
    required = _REQUIRED_FUNCTIONS.get((goal.level, goal.effective_operation))
    if (goal.level, goal.effective_operation) == (GoalLevel.INSTANCE, GoalOperation.HISTORY):
        required = _history_reads(goal)
        if functions != required:
            violations.append("sem_history_read_differs")
    if (
        (goal.level, goal.effective_operation) == (GoalLevel.INSTANCE, GoalOperation.LOOKUP)
        and goal.measure is not None
        and goal.measure.kind is MeasureKind.METRIC
    ):
        # A metric is read only by the metric reader, never answered as a current state.
        required = frozenset({METRIC_READER})
        if functions != required:
            violations.append("sem_metric_read_differs")
    if property_read_helpers.is_property_lookup(goal):
        required = None
        violations.extend(
            property_read_helpers.property_read_violations(
                plans, _expected_anchor_id(goal, anchors)
            )
        )
    if is_health_lookup(goal) and functions != TARGET_HEALTH_FUNCTIONS:
        violations.append("sem_health_read_differs")
    if required is not None and functions.isdisjoint(required):
        violations.append("sem_operation_read_missing")
    if goal.level is GoalLevel.SCHEMA:
        violations.extend(_schema_violations(goal, functions, admission))
    if goal.level is GoalLevel.INSTANCE:
        violations.extend(filter_coverage(plans, allowed.stated()))
    if goal.level is GoalLevel.INSTANCE and (
        (goal.relation is not None and not restated_relation(goal))
        or goal.effective_operation is GoalOperation.IMPACT
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
            relation_reach(goal)
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
    ObjectType's own LinkTypes in both directions, and a manifest count groups only by
    declaration kind.
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
            or relation.counterpart is not None
            or relation.anchor_role is not SubjectRole.EITHER
            or relation.result_role is not SubjectRole.EITHER
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
        # Re-derived here: a reciprocal LinkType has no direction to narrow it by.
        side = SubjectPosition.EITHER if "reciprocal" in traits else position
        if side in {SubjectPosition.SOURCE, SubjectPosition.EITHER} and (
            source == "Resource" and fits(target)
        ):
            expected.add((name, "outgoing"))
        if side in {SubjectPosition.TARGET, SubjectPosition.EITHER} and (
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
    return position, sense, relation.scope, relation_reach(goal)


def _expected_lookback(goal: FormGoal, default_seconds: int) -> int | None:
    if goal.time.kind in {TimeKind.CURRENT, TimeKind.UNSPECIFIED}:
        return default_seconds
    value = goal.time.value
    if goal.time.kind is not TimeKind.WINDOW or value is None or value.duration is None:
        return None
    return value.duration.amount * _SECONDS[value.duration.unit]


def _all_zero(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    stripped = value.replace("-", "").replace("0", "")
    return not stripped and "0" in value


__all__ = ["verify_goal_semantics"]
