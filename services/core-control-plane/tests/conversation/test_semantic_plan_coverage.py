"""A verified current-path plan must read what the question was read to ask."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fdai.core.conversation.semantic_plan_coverage import (
    plan_reads_only_a_list,
    plan_uncovered_roles,
)
from fdai.core.conversation.semantic_reasoning_form import SourceSpan
from fdai.core.conversation.semantic_reasoning_review import (
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
                    {"link_types": ["contains"], "endpoint_predicates": [_TYPE]},
                ),
            ),
            True,
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

    assert plan_uncovered_roles(both, listed) == ("groups", "relates")
    # A grouping by container reads containment, so only a plain list misses a relation.
    assert plan_uncovered_roles(both, grouped) == ()
    assert plan_uncovered_roles(both, related) == ("groups",)
    # Without a blind reading, or with only a restriction, nothing is held here.
    assert plan_uncovered_roles(None, listed) == ()
    assert plan_uncovered_roles(_reading(ConstraintRole.RESTRICTS), listed) == ()
