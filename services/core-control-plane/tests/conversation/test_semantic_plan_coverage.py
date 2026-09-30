"""A verified current-path plan must read what the question was read to ask."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fdai.core.conversation.semantic_plan_coverage import (
    narrower_plan_outcome,
    plan_answers_schema_for_instance,
    plan_reads_only_a_list,
    plan_uncovered_roles,
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
