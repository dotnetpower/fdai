"""ObjectSet predicate validation and execution tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetService,
    ObjectTraversal,
    compile_interfaces,
)
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore


class _RecordingStore(InMemoryOntologyInstanceStore):
    def __init__(self, *, object_types: Sequence[OntologyObjectType]) -> None:
        super().__init__(object_types=object_types, link_types=())
        self.last_property_equals: Mapping[str, Any] | None = None
        self.last_limit: int | None = None

    async def query_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        limit: int = 100,
    ) -> OntologyGraphSnapshot:
        self.last_property_equals = property_equals
        self.last_limit = limit
        return await super().query_objects(
            object_types=object_types,
            property_equals=property_equals,
            limit=limit,
        )


def _object_type(name: str = "Resource") -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "status": PropertyDecl(type=PropertyType.STRING),
            "score": PropertyDecl(type=PropertyType.INTEGER),
            "labels": PropertyDecl(type=PropertyType.ARRAY),
            "note": PropertyDecl(type=PropertyType.STRING),
        },
    )


def _service(
    store: InMemoryOntologyInstanceStore,
    object_type: OntologyObjectType,
) -> ObjectSetService:
    return ObjectSetService(
        store=store,
        interfaces=compile_interfaces(
            interfaces=(), implementations=(), object_types=(object_type,)
        ),
        object_type_names=frozenset({object_type.name}),
    )


async def _seed(store: InMemoryOntologyInstanceStore) -> None:
    records = (
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={
                "id": "resource-a",
                "status": "ready",
                "score": 3,
                "labels": ["network", "prod"],
            },
        ),
        OntologyObjectRecord(
            id="resource-b",
            object_type="Resource",
            properties={
                "id": "resource-b",
                "status": "blocked",
                "score": 7,
                "labels": ["network"],
                "note": "firewall policy",
            },
        ),
        OntologyObjectRecord(
            id="resource-c",
            object_type="Resource",
            properties={
                "id": "resource-c",
                "status": "ready",
                "score": 10,
                "labels": ["otel", "prod"],
            },
        ),
        OntologyObjectRecord(
            id="resource-d",
            object_type="Resource",
            properties={"id": "resource-d", "score": 1, "labels": []},
        ),
    )
    for record in records:
        await store.upsert_object(record)


def _definition(*predicates: ObjectPredicate, limit: int = 100) -> ObjectSetDefinition:
    return ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=predicates,
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        purpose="predicate-test",
        limit=limit,
    )


def test_object_predicate_preserves_legacy_equals_and_validates_operands() -> None:
    legacy = ObjectPredicate(property="status", equals="ready")
    member_of = ObjectPredicate(
        property="status", operator=ObjectPredicateOperator.IN, values=("ready", "blocked")
    )
    exists = ObjectPredicate(property="note", operator=ObjectPredicateOperator.EXISTS)

    assert legacy.operator is ObjectPredicateOperator.EQUALS
    assert ObjectPredicate(property="status", equals=None).equals is None
    assert member_of.values == ("ready", "blocked")
    for predicate in (legacy, member_of, exists):
        assert ObjectPredicate.model_validate(predicate.model_dump()) == predicate

    invalid = (
        {"property": "status"},
        {"property": "status", "operator": "in", "equals": "ready"},
        {"property": "status", "operator": "in", "values": ()},
        {"property": "status", "operator": "exists", "equals": "ready"},
        {"property": "status", "operator": "not_equals", "values": ("ready",)},
    )
    for payload in invalid:
        with pytest.raises(ValidationError, match="object predicate"):
            ObjectPredicate.model_validate(payload)


@pytest.mark.parametrize(
    ("property_name", "operator", "operand", "expected_ids"),
    (
        (
            "status",
            ObjectPredicateOperator.EQUALS,
            {"equals": "ready"},
            ["resource-a", "resource-c"],
        ),
        ("status", ObjectPredicateOperator.NOT_EQUALS, {"equals": "ready"}, ["resource-b"]),
        (
            "status",
            ObjectPredicateOperator.IN,
            {"values": ("blocked", "ready")},
            ["resource-a", "resource-b", "resource-c"],
        ),
        ("note", ObjectPredicateOperator.EXISTS, {}, ["resource-b"]),
        (
            "note",
            ObjectPredicateOperator.ABSENT,
            {},
            ["resource-a", "resource-c", "resource-d"],
        ),
        ("score", ObjectPredicateOperator.AT_LEAST, {"equals": 7}, ["resource-b", "resource-c"]),
        ("score", ObjectPredicateOperator.AT_MOST, {"equals": 3}, ["resource-a", "resource-d"]),
        (
            "labels",
            ObjectPredicateOperator.CONTAINS,
            {"equals": "prod"},
            ["resource-a", "resource-c"],
        ),
        ("note", ObjectPredicateOperator.CONTAINS, {"equals": "wall"}, ["resource-b"]),
    ),
)
async def test_query_branch_applies_each_predicate_operator(
    property_name: str,
    operator: ObjectPredicateOperator,
    operand: dict[str, Any],
    expected_ids: list[str],
) -> None:
    object_type = _object_type()
    store = InMemoryOntologyInstanceStore(object_types=(object_type,), link_types=())
    await _seed(store)

    result = await _service(store, object_type).materialize(
        _definition(ObjectPredicate(property=property_name, operator=operator, **operand))
    )

    assert [item.id for item in result.graph.objects] == expected_ids


async def test_query_pushes_down_only_equals_and_reports_post_filter_truncation() -> None:
    object_type = _object_type()
    store = _RecordingStore(object_types=(object_type,))
    await _seed(store)

    result = await _service(store, object_type).materialize(
        _definition(
            ObjectPredicate(property="status", equals="ready"),
            ObjectPredicate(property="score", operator=ObjectPredicateOperator.AT_LEAST, equals=3),
            limit=1,
        )
    )

    assert store.last_property_equals == {"status": "ready"}
    assert store.last_limit == 1000
    assert [item.id for item in result.graph.objects] == ["resource-a"]
    assert result.truncated is True
    assert result.truncation_reason == "result_limit"


async def test_traversal_branch_applies_predicates_and_removes_dangling_links() -> None:
    object_type = _object_type()
    link_type = OntologyLinkType(
        schema_version="1.0.0",
        name="depends_on",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    store = InMemoryOntologyInstanceStore(object_types=(object_type,), link_types=(link_type,))
    await _seed(store)
    await store.upsert_link(
        OntologyLinkRecord(link_type="depends_on", from_id="resource-c", to_id="resource-a")
    )
    await store.upsert_link(
        OntologyLinkRecord(link_type="depends_on", from_id="resource-c", to_id="resource-b")
    )
    definition = _definition(
        ObjectPredicate(property="score", operator=ObjectPredicateOperator.AT_LEAST, equals=7)
    ).model_copy(
        update={
            "traversal": ObjectTraversal(link_types=("depends_on",), max_depth=1),
            "root_ids": ("resource-c",),
        }
    )

    result = await _service(store, object_type).materialize(definition)

    assert [item.id for item in result.graph.objects] == ["resource-b", "resource-c"]
    assert [(item.from_id, item.to_id) for item in result.graph.links] == [
        ("resource-c", "resource-b")
    ]
