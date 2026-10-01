"""A verified current-path plan must read what the question was read to ask."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fdai.core.conversation.semantic_operand_provenance import (
    IdentityBindingReceipt,
    provenance_scope,
)
from fdai.core.conversation.semantic_plan_coverage import (
    narrower_plan_outcome,
    plan_answers_schema_for_instance,
    plan_reads_only_a_list,
    plan_uncovered_roles,
    plan_uncovered_slot_roles,
)
from fdai.core.conversation.semantic_planning_models import SemanticPlanningDisposition
from fdai.core.conversation.semantic_reasoning_form import SourceSpan
from fdai.core.conversation.semantic_reasoning_review import (
    AnswerKind,
    ConstraintExtraction,
    ConstraintRole,
    ExtractedConstraint,
)
from fdai_service_contracts.ontology_query import OntologyQueryNode, QueryNodeKind, canonical_json
from fdai_service_contracts.semantic_slots import SemanticConstraintSlot


def _node(node_id: str, kind: QueryNodeKind, arguments: dict[str, Any]) -> OntologyQueryNode:
    return OntologyQueryNode(
        node_id=node_id,
        kind=kind,
        arguments_json=canonical_json(arguments),
        output_kind="query.table",
    )


def _objects(*predicates: dict[str, Any]) -> OntologyQueryNode:
    definition = {"selector": {"kind": "object_type", "name": "Resource"}, "predicates": predicates}
    return _node("objects", QueryNodeKind.OBJECT_SET, {"definition": definition})


def _plan(*nodes: OntologyQueryNode) -> Any:
    return cast(Any, SimpleNamespace(nodes=nodes))


_TYPE = {"property": "type", "operator": "in", "values": ["compute.vm"]}
_NAME = {"property": "name", "operator": "contains", "equals": "web"}
_REGION = {"property": "location", "operator": "equals", "equals": "koreacentral"}


@pytest.mark.parametrize(
    ("nodes", "only_list"),
    (
        ((_objects(_TYPE, _NAME),), True),
        ((_objects(_TYPE), _node("count", QueryNodeKind.AGGREGATE, {"operation": "count"})), True),
        (
            (
                _objects(_TYPE),
                _node(
                    "members",
                    QueryNodeKind.RELATIONSHIP_TRAVERSAL,
                    {
                        "link_types": ["contains"],
                        "direction": "outgoing",
                        "endpoint_predicates": [_TYPE],
                    },
                ),
            ),
            True,
        ),
        (
            (
                _objects(_TYPE),
                _node(
                    "container",
                    QueryNodeKind.RELATIONSHIP_TRAVERSAL,
                    {"link_types": ["contains"], "direction": "incoming"},
                ),
            ),
            False,
        ),
        ((_objects(_TYPE, _REGION),), False),
        (
            (
                _objects(_TYPE),
                _node(
                    "count",
                    QueryNodeKind.AGGREGATE,
                    {"operation": "count", "group_by": ["properties.type"]},
                ),
            ),
            False,
        ),
        (
            (
                _objects(_TYPE),
                _node(
                    "depends", QueryNodeKind.RELATIONSHIP_TRAVERSAL, {"link_types": ["depends_on"]}
                ),
            ),
            False,
        ),
        ((_node("state", QueryNodeKind.FUNCTION, {"function_name": "query.x"}),), False),
    ),
)
def test_a_list_plan_reads_only_kind_name_identity_and_container(
    nodes: tuple[OntologyQueryNode, ...], only_list: bool
) -> None:
    assert plan_reads_only_a_list(_plan(*nodes)) is only_list


def _reading(*roles: ConstraintRole) -> ConstraintExtraction:
    return ConstraintExtraction(
        constraints=tuple(
            ExtractedConstraint(quote=SourceSpan(start=0, end=1), role=role) for role in roles
        )
    )


def test_a_stated_grouping_or_relation_must_shape_the_plan() -> None:
    listed = _plan(_objects(_TYPE))
    grouped = _plan(
        _objects(_TYPE),
        _node("count", QueryNodeKind.AGGREGATE, {"operation": "count", "group_by": ["x"]}),
    )
    related = _plan(
        _objects(_TYPE),
        _node("depends", QueryNodeKind.RELATIONSHIP_TRAVERSAL, {"link_types": ["depends_on"]}),
    )
    both = _reading(ConstraintRole.GROUPS, ConstraintRole.RELATES, ConstraintRole.RESTRICTS)

    members = _plan(
        _objects(_TYPE),
        _node("members", QueryNodeKind.RELATIONSHIP_TRAVERSAL, {"link_types": ["contains"]}),
    )
    by_container = _plan(
        _objects(_TYPE),
        _node(
            "count",
            QueryNodeKind.AGGREGATE,
            {"operation": "count", "group_by": ["properties.parent_id"]},
        ),
    )

    assert plan_uncovered_roles(both, listed) == ("groups", "relates")
    # A grouping by type reads no relation, while one by container reads containment.
    assert plan_uncovered_roles(both, grouped) == ("relates",)
    assert plan_uncovered_roles(both, by_container) == ()
    assert plan_uncovered_roles(both, related) == ("groups",)
    # A container's members read the inside relation, as in the VMs inside a group.
    assert plan_uncovered_roles(_reading(ConstraintRole.RELATES), members) == ()
    # Without a blind reading, or with only a restriction, nothing is held here.
    assert plan_uncovered_roles(None, listed) == ()
    assert plan_uncovered_roles(_reading(ConstraintRole.RESTRICTS), listed) == ()


def test_frame_slots_must_shape_the_verified_plan() -> None:
    frame = SimpleNamespace(
        constraint_slots=(
            SemanticConstraintSlot(
                role="group_by",
                source_start=0,
                source_end=5,
                grounded=True,
                value="ObjectType",
            ),
            SemanticConstraintSlot(
                role="relation_path",
                source_start=6,
                source_end=13,
                grounded=True,
                value="depends_on",
            ),
        )
    )

    assert plan_uncovered_slot_roles(frame, _plan(_objects(_TYPE))) == (
        "group_by",
        "relation_path",
    )
    assert (
        plan_uncovered_slot_roles(
            frame,
            _plan(
                _objects(_TYPE),
                _node(
                    "grouped", QueryNodeKind.AGGREGATE, {"operation": "count", "group_by": ["x"]}
                ),
                _node(
                    "depends", QueryNodeKind.RELATIONSHIP_TRAVERSAL, {"link_types": ["depends_on"]}
                ),
            ),
        )
        == ()
    )


def _asking(kind: AnswerKind | None) -> ConstraintExtraction:
    return ConstraintExtraction(
        constraints=(
            ExtractedConstraint(quote=SourceSpan(start=0, end=1), role=ConstraintRole.NAMES),
        ),
        answer_kind=kind,
    )


def _declaration() -> OntologyQueryNode:
    return _node(
        "declaration",
        QueryNodeKind.FUNCTION,
        {"function_name": "query.ontology_declaration", "arguments": {"name": "Resource"}},
    )


@pytest.mark.parametrize(
    ("kind", "held"),
    (
        (AnswerKind.STATE, True),
        (AnswerKind.VALUE, True),
        (AnswerKind.LOCATION, True),
        (AnswerKind.HISTORY, True),
        (AnswerKind.CAUSE, True),
        (AnswerKind.SCHEMA, False),
        (AnswerKind.LIST, False),
        (AnswerKind.COUNT, False),
        (AnswerKind.RELATION, False),
        (AnswerKind.OTHER, False),
        (None, False),
    ),
)
def test_a_declaration_read_never_answers_what_an_instance_is(
    kind: AnswerKind | None, held: bool
) -> None:
    declared = _plan(_declaration())
    counted = _plan(_declaration(), _node("count", QueryNodeKind.AGGREGATE, {"operation": "count"}))
    instances = _plan(_objects(_TYPE), _declaration())

    expected = kind if held else None
    assert plan_answers_schema_for_instance(_asking(kind), declared) == expected
    assert plan_answers_schema_for_instance(_asking(kind), counted) == expected
    # A plan that also reads instances is judged by the other checks, never this one.
    assert plan_answers_schema_for_instance(_asking(kind), instances) is None


def test_a_schema_answer_to_an_instance_question_holds_as_an_unverified_reading() -> None:
    coverage = SimpleNamespace(settled_reading=lambda: _asking(AnswerKind.STATE))

    outcome = narrower_plan_outcome(
        None, cast(Any, coverage), "model_plan", _plan(_declaration()), "sha256:" + "a" * 64
    )

    assert outcome is not None
    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_reading_unverified"
    assert outcome.hold_details == ("answer_kind:state",)


def test_a_model_plan_with_an_invented_identity_literal_holds() -> None:
    plan = _plan(_objects({"property": "id", "operator": "equals", "equals": "invented-id"}))

    outcome = narrower_plan_outcome(
        None,
        None,
        "proposed",
        plan,
        "sha256:" + "a" * 64,
        utterance="What is the state of app-prod?",
    )

    assert outcome is not None
    assert outcome.reason == "semantic_operand_without_source"

    named = _plan(_objects({"property": "name", "operator": "equals", "equals": "other-app"}))
    named_outcome = narrower_plan_outcome(
        None,
        None,
        "proposed",
        named,
        "sha256:" + "a" * 64,
        utterance="What is the state of app-prod?",
    )
    assert named_outcome is not None
    assert named_outcome.reason == "semantic_operand_without_source"


def test_identity_operands_may_come_from_receipts_context_or_prior_turns() -> None:
    plan = _plan(_objects({"property": "id", "operator": "equals", "equals": "server-id"}))
    receipt = IdentityBindingReceipt(
        source="server_binding",
        lookup="exact_resource_name",
        identity="server-id",
        span=(21, 29),
    )

    assert (
        narrower_plan_outcome(
            None,
            None,
            "proposed",
            plan,
            "sha256:" + "a" * 64,
            utterance="What is the state of app-prod?",
            identity_receipts=(receipt,),
        )
        is None
    )
    assert (
        narrower_plan_outcome(
            None,
            None,
            "proposed",
            plan,
            "sha256:" + "a" * 64,
            identity_receipts=(IdentityBindingReceipt("result_handle", "handle_row", "server-id"),),
        )
        is None
    )
    assert (
        narrower_plan_outcome(
            None,
            None,
            "proposed",
            plan,
            "sha256:" + "a" * 64,
            context=("server-id was shown in the prior turn",),
        )
        is None
    )


@pytest.mark.parametrize(
    ("operand", "utterance"),
    [
        # A Korean particle written right after a name still quotes the name.
        ("vm-app-01", "vm-app-01의 상태는?"),
        ("vm-app-01", "VM-APP-01에서 무슨 일이 있었어?"),
        # A multi-word name is quoted as written.
        ("prod storage", "show the prod storage account"),
    ],
)
def test_an_identity_quoted_with_particles_or_spaces_is_not_invented(
    operand: str, utterance: str
) -> None:
    plan = _plan(_objects({"property": "name", "operator": "equals", "equals": operand}))

    assert (
        narrower_plan_outcome(
            None, None, "proposed", plan, "sha256:" + "a" * 64, utterance=utterance
        )
        is None
    )


@pytest.mark.parametrize(
    ("operand", "utterance"),
    [
        # Part of a longer identifier is not that identifier.
        ("vm-app-0", "vm-app-01의 상태는?"),
        ("app", "show app-prod"),
        ("prod", "show app.prod.example"),
    ],
)
def test_part_of_a_longer_identifier_is_still_invented(operand: str, utterance: str) -> None:
    plan = _plan(_objects({"property": "name", "operator": "equals", "equals": operand}))

    outcome = narrower_plan_outcome(
        None, None, "proposed", plan, "sha256:" + "a" * 64, utterance=utterance
    )

    assert outcome is not None and outcome.reason == "semantic_operand_without_source"


def test_a_bound_console_resource_grounds_its_own_identities() -> None:
    plan = _plan(_objects({"property": "id", "operator": "equals", "equals": "/sub/vm-1"}))
    bound = SimpleNamespace(resource_ids=("/sub/vm-1",), resource_group_id=None)
    coverage = SimpleNamespace(settled_reading=lambda: None)

    held = narrower_plan_outcome(
        None,
        cast(Any, coverage),
        "proposed",
        plan,
        "sha256:" + "a" * 64,
        "what is its state?",
        (),
        provenance_scope(coverage, None),
    )
    grounded = narrower_plan_outcome(
        None,
        cast(Any, coverage),
        "proposed",
        plan,
        "sha256:" + "a" * 64,
        "what is its state?",
        (),
        provenance_scope(coverage, bound),
    )

    assert held is not None and held.reason == "semantic_operand_without_source"
    assert grounded is None


def _slot(role: str, value: str, **extra: Any) -> SemanticConstraintSlot:
    return SemanticConstraintSlot(
        role=role, source_start=0, source_end=5, grounded=True, value=value, **extra
    )


@pytest.mark.parametrize(
    ("slot", "applied", "ignored"),
    [
        (_slot("location", "koreacentral"), _objects(_TYPE, _REGION), _objects(_TYPE)),
        (
            _slot("lifecycle_status", "resolved", object_type="Incident"),
            _objects({"property": "status", "operator": "equals", "equals": "resolved"}),
            _objects(_TYPE),
        ),
        (
            _slot("property_predicate", "Standard"),
            _objects({"property": "sku", "operator": "equals", "equals": "standard"}),
            _objects(_TYPE),
        ),
        (
            _slot("time_window", "PT24H"),
            _node(
                "changes",
                QueryNodeKind.FUNCTION,
                {
                    "function_name": "query.recent_resource_changes",
                    "arguments": {"lookback_seconds": 86400},
                },
            ),
            _objects(_TYPE),
        ),
    ],
)
def test_a_slot_that_covered_a_restriction_must_restrict_the_plan(
    slot: SemanticConstraintSlot, applied: OntologyQueryNode, ignored: OntologyQueryNode
) -> None:
    frame = SimpleNamespace(constraint_slots=(slot,))

    assert plan_uncovered_slot_roles(frame, _plan(applied)) == ()
    assert plan_uncovered_slot_roles(frame, _plan(ignored)) == (slot.role.value,)


def test_a_model_plan_renamed_by_document_evidence_still_needs_sourced_identities() -> None:
    plan = _plan(_objects({"property": "id", "operator": "equals", "equals": "vm-invented-07"}))

    outcome = narrower_plan_outcome(
        None,
        None,
        "proposed+governed_documents",
        plan,
        "sha256:" + "a" * 64,
        utterance="What is the state of app-prod?",
    )

    assert outcome is not None and outcome.reason == "semantic_operand_without_source"


def test_a_case_insensitive_identity_match_is_still_an_identity() -> None:
    plan = _plan(
        _objects({"property": "name", "operator": "equals_ignore_case", "equals": "prod-db-07"})
    )

    outcome = narrower_plan_outcome(
        None, None, "proposed", plan, "sha256:" + "a" * 64, utterance="show app-prod"
    )

    assert outcome is not None and outcome.reason == "semantic_operand_without_source"


_AT_BEFORE = "2026-10-01T00:00:00Z"
_AT_AFTER = "2026-10-01T01:00:00Z"


def _snapshot(node_id: str, as_of: str) -> OntologyQueryNode:
    return _node(
        node_id,
        QueryNodeKind.FUNCTION,
        {
            "function_name": "query.resource_configuration_snapshot",
            "arguments": {"as_of": as_of, "known_at": _AT_AFTER},
        },
    )


@pytest.mark.parametrize(
    "nodes",
    [
        (
            _node(
                "diff",
                QueryNodeKind.FUNCTION,
                {
                    "function_name": "query.resource_configuration_changes",
                    "arguments": {"before_as_of": _AT_BEFORE, "after_as_of": _AT_AFTER},
                },
            ),
        ),
        (_snapshot("before", _AT_BEFORE), _snapshot("after", _AT_AFTER)),
        (
            _node("then", QueryNodeKind.TOPOLOGY_AT, {"as_of": _AT_BEFORE, "known_at": _AT_AFTER}),
            _node("now", QueryNodeKind.TOPOLOGY_AT, {"as_of": _AT_AFTER, "known_at": _AT_AFTER}),
        ),
    ],
)
def test_a_point_in_time_pair_applies_a_time_slot(nodes: tuple[OntologyQueryNode, ...]) -> None:
    frame = SimpleNamespace(constraint_slots=(_slot("time_window", "PT1H"),))

    assert plan_uncovered_slot_roles(frame, _plan(*nodes)) == ()


@pytest.mark.parametrize(
    "nodes",
    [
        (_snapshot("now", _AT_AFTER),),
        (_snapshot("a", _AT_AFTER), _snapshot("b", _AT_AFTER)),
        (
            _node(
                "objects",
                QueryNodeKind.OBJECT_SET,
                {"definition": {"selector": {"kind": "object_type", "name": "Resource"}}},
            ),
            _node(
                "deps",
                QueryNodeKind.RELATIONSHIP_TRAVERSAL,
                {"link_type": "depends_on", "as_of": _AT_AFTER},
            ),
            _node("path", QueryNodeKind.TYPED_PATH, {"as_of": _AT_BEFORE}),
        ),
    ],
)
def test_a_single_cutoff_does_not_apply_a_time_slot(nodes: tuple[OntologyQueryNode, ...]) -> None:
    """The server stamps a current cutoff on traversals and paths; that is no window."""

    frame = SimpleNamespace(constraint_slots=(_slot("time_window", "PT24H"),))

    assert plan_uncovered_slot_roles(frame, _plan(*nodes)) == ("time_window",)


def test_an_invented_identity_in_a_traversal_endpoint_or_metric_read_is_held() -> None:
    traversal = _node(
        "deps",
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        {
            "endpoint_predicates": [
                {"property": "name", "operator": "equals", "equals": "prod-db-07"}
            ]
        },
    )
    metric = _node("cpu", QueryNodeKind.METRIC_SCOPE_SERIES, {"resource_id": "vm-invented-9"})

    for node in (traversal, metric):
        outcome = narrower_plan_outcome(
            None, None, "proposed", _plan(node), "sha256:" + "a" * 64, utterance="show app-prod"
        )
        assert outcome is not None and outcome.reason == "semantic_operand_without_source"
