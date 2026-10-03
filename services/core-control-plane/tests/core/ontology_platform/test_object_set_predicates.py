"""ObjectSet predicate validation and execution tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetService,
    ObjectSetTruncationReason,
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
    MAX_ONTOLOGY_OBJECT_SCAN,
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from pydantic import ValidationError


class _RecordingStore(InMemoryOntologyInstanceStore):
    def __init__(self, *, object_types: Sequence[OntologyObjectType]) -> None:
        super().__init__(object_types=object_types, link_types=())
        self.last_property_equals: Mapping[str, Any] | None = None
        self.property_equals_calls: list[Mapping[str, Any] | None] = []
        self.last_property_text_in: Mapping[str, Sequence[str]] | None = None
        self.last_limit: int | None = None
        self.scan_calls = 0
        self.force_scan_truncated = False
        self.force_truncated = False

    async def query_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        property_text_in: Mapping[str, Sequence[str]] | None = None,
        limit: int = 100,
        include_relationships: bool = True,
    ) -> OntologyGraphSnapshot:
        self.last_property_equals = property_equals
        self.property_equals_calls.append(property_equals)
        self.last_property_text_in = property_text_in
        self.last_limit = limit
        graph = await super().query_objects(
            object_types=object_types,
            property_equals=property_equals,
            property_text_in=property_text_in,
            limit=limit,
            include_relationships=include_relationships,
        )
        if self.force_truncated:
            return OntologyGraphSnapshot(
                objects=graph.objects,
                links=graph.links,
                truncated=True,
            )
        return graph

    async def scan_objects(
        self,
        *,
        object_types: Sequence[str] = (),
        property_equals: Mapping[str, Any] | None = None,
        property_text_in: Mapping[str, Sequence[str]] | None = None,
        candidate_limit: int = MAX_ONTOLOGY_OBJECT_SCAN,
    ) -> OntologyGraphSnapshot:
        self.scan_calls += 1
        self.last_property_equals = property_equals
        self.property_equals_calls.append(property_equals)
        self.last_property_text_in = property_text_in
        graph = await super().scan_objects(
            object_types=object_types,
            property_equals=property_equals,
            property_text_in=property_text_in,
            candidate_limit=candidate_limit,
        )
        if self.force_scan_truncated:
            return OntologyGraphSnapshot(
                objects=graph.objects,
                links=graph.links,
                truncated=True,
                source_complete=graph.source_complete,
                source_generation=graph.source_generation,
            )
        return graph


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
    assert member_of.values == ("ready", "blocked")
    for predicate in (legacy, member_of, exists):
        assert ObjectPredicate.model_validate(predicate.model_dump()) == predicate
        assert ObjectPredicate.model_validate(predicate.model_dump(exclude_none=True)) == predicate
        assert ObjectPredicate.model_validate_json(predicate.model_dump_json()) == predicate

    invalid = (
        {"property": "status"},
        {"property": "status", "operator": "in", "equals": "ready"},
        {"property": "status", "operator": "in", "values": ()},
        {"property": "status", "operator": "exists", "equals": "ready"},
        {"property": "status", "operator": "not_equals", "values": ("ready",)},
        {"property": "status", "equals": None},
    )
    for payload in invalid:
        with pytest.raises(ValidationError, match="object predicate"):
            ObjectPredicate.model_validate(payload)


def test_object_predicate_rejects_noncanonical_or_unbounded_operands() -> None:
    invalid = (
        {"property": "score", "equals": float("nan")},
        {"property": "status", "operator": "in", "values": tuple(range(1001))},
        {"property": "x" * 257, "equals": "value"},
        {"property": "metadata", "equals": "x" * 65_537},
    )
    for payload in invalid:
        with pytest.raises(ValidationError):
            ObjectPredicate.model_validate(payload)


def test_object_set_rejects_unbounded_or_ignored_query_inputs() -> None:
    with pytest.raises(ValidationError):
        _definition(*[ObjectPredicate(property="status", equals="ready")] * 33)
    with pytest.raises(ValidationError, match="root_ids require traversal"):
        ObjectSetDefinition.model_validate(
            {**_definition().model_dump(), "root_ids": ("resource-a",)}
        )
    with pytest.raises(ValidationError):
        ObjectTraversal(link_types=())


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


@pytest.mark.parametrize(
    ("actual", "operand", "equal"),
    (
        (True, 1, False),
        (1, True, False),
        (False, 0, False),
        (0, False, False),
        ({"enabled": True}, {"enabled": 1}, False),
        ({"enabled": 0}, {"enabled": False}, False),
        ([True], [1], False),
        ([{"enabled": [False]}], [{"enabled": [0]}], False),
        (1, 1.0, True),
        ({"count": [1]}, {"count": [1.0]}, True),
        ({"a": 1, "b": False}, {"b": False, "a": 1}, True),
        ([1, 2], [2, 1], False),
        ([1, 1], [1], False),
        ({"a": 1, "b": 2}, {"a": 1}, False),
        ({"a": None}, {"b": None}, False),
        ({"a": None}, {"a": None}, True),
        ({"a": []}, {"a": {}}, False),
        ({"a": True}, {"a": True}, True),
    ),
)
@pytest.mark.parametrize(
    "operator",
    (
        ObjectPredicateOperator.EQUALS,
        ObjectPredicateOperator.NOT_EQUALS,
        ObjectPredicateOperator.IN,
        ObjectPredicateOperator.CONTAINS,
    ),
)
async def test_structured_predicates_preserve_json_types_and_structure(
    actual: Any,
    operand: Any,
    equal: bool,
    operator: ObjectPredicateOperator,
) -> None:
    object_type = _object_type()
    store = InMemoryOntologyInstanceStore(object_types=(object_type,), link_types=())
    await store.upsert_object(
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={"id": "resource-a", "labels": [actual]},
        )
    )
    if operator is ObjectPredicateOperator.IN:
        predicate = ObjectPredicate(property="labels", operator=operator, values=([operand],))
    else:
        predicate = ObjectPredicate(
            property="labels",
            operator=operator,
            equals=operand if operator is ObjectPredicateOperator.CONTAINS else [operand],
        )
    expected = not equal if operator is ObjectPredicateOperator.NOT_EQUALS else equal
    result = await _service(store, object_type).materialize(_definition(predicate))

    assert [item.id for item in result.graph.objects] == (["resource-a"] if expected else [])
    assert result.truncated is False
    if operator is ObjectPredicateOperator.EQUALS:
        stored = await store.query_objects(property_equals={"labels": [operand]})
        assert [item.id for item in stored.objects] == (["resource-a"] if equal else [])


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
    assert result.truncation_reason is ObjectSetTruncationReason.RESULT_LIMIT


async def test_query_pushes_one_text_in_predicate_before_memory_filtering() -> None:
    object_type = _object_type()
    store = _RecordingStore(object_types=(object_type,))
    await _seed(store)

    definition = _definition(
        ObjectPredicate(
            property="status",
            operator=ObjectPredicateOperator.IN,
            values=("ready", "blocked"),
        ),
        ObjectPredicate(property="score", operator=ObjectPredicateOperator.AT_LEAST, equals=3),
    ).model_copy(update={"include_relationships": False})
    result = await _service(store, object_type).materialize(definition)

    assert store.property_equals_calls == [{}]
    assert store.last_property_text_in == {"status": ("ready", "blocked")}
    assert [item.id for item in result.graph.objects] == [
        "resource-a",
        "resource-b",
        "resource-c",
    ]
    assert result.truncated is False


async def test_query_reports_candidate_limit_before_memory_filtering() -> None:
    object_type = _object_type()
    store = _RecordingStore(object_types=(object_type,))
    await _seed(store)
    store.force_truncated = True

    result = await _service(store, object_type).materialize(
        _definition(
            ObjectPredicate(
                property="score", operator=ObjectPredicateOperator.AT_LEAST, equals=100
            ),
            limit=10,
        )
    )

    assert result.graph.objects == ()
    assert result.truncated is True
    assert result.truncation_reason is ObjectSetTruncationReason.CANDIDATE_LIMIT


async def test_object_only_memory_filter_scans_past_first_store_page() -> None:
    object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "properties": PropertyDecl(type=PropertyType.OBJECT),
        },
    )
    store = _RecordingStore(object_types=(object_type,))
    for index in range(1001):
        await store.upsert_object(
            OntologyObjectRecord(
                id=f"resource-{index:04d}",
                object_type="Resource",
                properties={"id": f"resource-{index:04d}", "properties": {}},
            )
        )
    expected = OntologyObjectRecord(
        id="resource-state",
        object_type="Resource",
        properties={
            "id": "resource-state",
            "properties": {"state_fact_metadata": {"state": "observed"}},
        },
    )
    await store.upsert_object(expected)

    result = await _service(store, object_type).materialize(
        ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
            predicates=(
                ObjectPredicate(
                    property="properties",
                    operator=ObjectPredicateOperator.CONTAINS,
                    equals="state_fact_metadata",
                ),
            ),
            as_of=datetime(2026, 8, 1, tzinfo=UTC),
            purpose="operations-review",
            include_relationships=False,
            limit=10,
        )
    )

    assert [item.id for item in result.graph.objects] == [expected.id]
    assert result.graph.objects[0].properties == expected.properties
    assert store.scan_calls == 1
    assert result.truncated is False
    assert result.truncation_reason is None


async def test_object_only_memory_filter_distinguishes_result_limit() -> None:
    object_type = _object_type()
    store = _RecordingStore(object_types=(object_type,))
    await _seed(store)
    store.force_truncated = True

    definition = _definition(
        ObjectPredicate(
            property="score",
            operator=ObjectPredicateOperator.AT_LEAST,
            equals=3,
        ),
        limit=1,
    ).model_copy(update={"include_relationships": False})
    result = await _service(store, object_type).materialize(definition)

    assert store.scan_calls == 0
    assert [item.id for item in result.graph.objects] == ["resource-a"]
    assert result.truncated is True
    assert result.truncation_reason is ObjectSetTruncationReason.RESULT_LIMIT


async def test_object_only_memory_filter_preserves_candidate_limit() -> None:
    object_type = _object_type()
    store = _RecordingStore(object_types=(object_type,))
    await _seed(store)
    store.force_truncated = True
    store.force_scan_truncated = True

    definition = _definition(
        ObjectPredicate(
            property="score",
            operator=ObjectPredicateOperator.AT_LEAST,
            equals=100,
        ),
        limit=10,
    ).model_copy(update={"include_relationships": False})
    result = await _service(store, object_type).materialize(definition)

    assert store.scan_calls == 1
    assert result.graph.objects == ()
    assert result.truncated is True
    assert result.truncation_reason is ObjectSetTruncationReason.CANDIDATE_LIMIT


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


async def test_traversal_reports_its_own_limit() -> None:
    object_type = _object_type()
    store = InMemoryOntologyInstanceStore(object_types=(object_type,), link_types=())
    await _seed(store)
    result = await _service(store, object_type).materialize(
        _definition(limit=1).model_copy(
            update={
                "traversal": ObjectTraversal(link_types=("depends_on",)),
                "root_ids": ("resource-a", "resource-b"),
            }
        )
    )

    assert result.truncated is True
    assert result.truncation_reason is ObjectSetTruncationReason.TRAVERSAL_LIMIT
