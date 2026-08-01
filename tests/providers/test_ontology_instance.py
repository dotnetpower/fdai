"""Runtime ontology instance validation and bounded graph queries."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
    normalize_json_value,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore


def test_normalize_json_value_rejects_excessive_nesting() -> None:
    nested: object = "leaf"
    for _ in range(34):
        nested = {"next": nested}

    with pytest.raises(OntologyInstanceValidationError, match="nesting depth"):
        normalize_json_value(nested)


def _object_type(name: str) -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "status": PropertyDecl(type=PropertyType.STRING, required=True),
        },
    )


def _link_type() -> OntologyLinkType:
    return OntologyLinkType(
        schema_version="1.0.0",
        name="contains_check",
        version="1.0.0",
        from_type="ReviewCase",
        to_type="ReviewCheck",
        cardinality=LinkCardinality.ONE_TO_MANY,
    )


def _store() -> InMemoryOntologyInstanceStore:
    return InMemoryOntologyInstanceStore(
        object_types=(_object_type("ReviewCase"), _object_type("ReviewCheck")),
        link_types=(_link_type(),),
    )


async def _upsert(
    store: InMemoryOntologyInstanceStore,
    identifier: str,
    kind: str,
    status: str,
) -> OntologyObjectRecord:
    return await store.upsert_object(
        OntologyObjectRecord(
            id=identifier,
            object_type=kind,
            properties={"id": identifier, "status": status},
        )
    )


async def test_upsert_validates_and_increments_revision() -> None:
    store = _store()
    first = await _upsert(store, "review-1", "ReviewCase", "open")
    second = await store.upsert_object(
        OntologyObjectRecord(
            id="review-1",
            object_type="ReviewCase",
            properties={"id": "review-1", "status": "in_review"},
        ),
        expected_revision=1,
    )
    assert first.revision == 1
    assert second.revision == 2
    assert second.properties["status"] == "in_review"
    assert first.type_ref is not None
    assert first.type_ref.name == "ReviewCase"
    assert first.type_ref.version == "1.0.0"


async def test_upsert_rejects_type_ref_from_another_release() -> None:
    store = _store()
    other_store = InMemoryOntologyInstanceStore(
        object_types=(
            _object_type("ReviewCase").model_copy(update={"version": "2.0.0"}),
            _object_type("ReviewCheck"),
        ),
        link_types=(_link_type(),),
    )
    record = await other_store.upsert_object(
        OntologyObjectRecord(
            id="review-1",
            object_type="ReviewCase",
            properties={"id": "review-1", "status": "open"},
        )
    )

    with pytest.raises(OntologyInstanceValidationError, match="active ontology release"):
        await store.upsert_object(record)


async def test_upsert_rejects_unknown_missing_and_bad_key() -> None:
    store = _store()
    with pytest.raises(OntologyInstanceValidationError, match="undeclared properties"):
        await store.upsert_object(
            OntologyObjectRecord(
                id="review-1",
                object_type="ReviewCase",
                properties={"id": "review-1", "status": "open", "layout": {}},
            )
        )
    with pytest.raises(OntologyInstanceValidationError, match="missing required"):
        await store.upsert_object(
            OntologyObjectRecord(
                id="review-1",
                object_type="ReviewCase",
                properties={"id": "review-1"},
            )
        )
    with pytest.raises(OntologyInstanceValidationError, match="MUST equal instance id"):
        await store.upsert_object(
            OntologyObjectRecord(
                id="review-1",
                object_type="ReviewCase",
                properties={"id": "other", "status": "open"},
            )
        )


async def test_revision_mismatch_fails_closed() -> None:
    store = _store()
    await _upsert(store, "review-1", "ReviewCase", "open")
    with pytest.raises(OntologyInstanceValidationError, match="revision mismatch"):
        await store.upsert_object(
            OntologyObjectRecord(
                id="review-1",
                object_type="ReviewCase",
                properties={"id": "review-1", "status": "approved"},
            ),
            expected_revision=0,
        )


async def test_link_validation_query_and_traversal() -> None:
    store = _store()
    await _upsert(store, "review-1", "ReviewCase", "open")
    await _upsert(store, "check-1", "ReviewCheck", "blocked")
    await _upsert(store, "check-2", "ReviewCheck", "ready")
    await store.upsert_link(
        OntologyLinkRecord(
            link_type="contains_check",
            from_id="review-1",
            to_id="check-1",
        )
    )
    await store.upsert_link(
        OntologyLinkRecord(
            link_type="contains_check",
            from_id="review-1",
            to_id="check-2",
        )
    )

    blocked = await store.query_objects(
        object_types=("ReviewCheck",), property_equals={"status": "blocked"}
    )
    graph = await store.traverse(root_ids=("review-1",), max_depth=1)

    assert [item.id for item in blocked.objects] == ["check-1"]
    assert {item.id for item in graph.objects} == {"review-1", "check-1", "check-2"}
    assert len(graph.links) == 2


async def test_link_rejects_wrong_endpoint_types() -> None:
    store = _store()
    await _upsert(store, "check-1", "ReviewCheck", "blocked")
    await _upsert(store, "review-1", "ReviewCase", "open")
    with pytest.raises(OntologyInstanceValidationError, match="requires ReviewCase->ReviewCheck"):
        await store.upsert_link(
            OntologyLinkRecord(
                link_type="contains_check",
                from_id="check-1",
                to_id="review-1",
            )
        )


async def test_query_and_traversal_are_bounded() -> None:
    store = _store()
    await _upsert(store, "review-1", "ReviewCase", "open")
    await _upsert(store, "review-2", "ReviewCase", "open")
    result = await store.query_objects(object_types=("ReviewCase",), limit=1)
    assert len(result.objects) == 1
    assert result.truncated is True
    with pytest.raises(ValueError, match="max_depth"):
        await store.traverse(root_ids=("review-1",), max_depth=6)


async def test_link_cardinality_is_enforced() -> None:
    store = _store()
    await _upsert(store, "review-1", "ReviewCase", "open")
    await _upsert(store, "review-2", "ReviewCase", "open")
    await _upsert(store, "check-1", "ReviewCheck", "ready")
    await store.upsert_link(
        OntologyLinkRecord(link_type="contains_check", from_id="review-1", to_id="check-1")
    )
    with pytest.raises(OntologyInstanceValidationError, match="one_to_many cardinality"):
        await store.upsert_link(
            OntologyLinkRecord(
                link_type="contains_check",
                from_id="review-2",
                to_id="check-1",
            )
        )


@pytest.mark.parametrize(
    ("cardinality", "second_edge", "allowed"),
    [
        (LinkCardinality.ONE_TO_ONE, ("node-1", "node-3"), False),
        (LinkCardinality.ONE_TO_ONE, ("node-3", "node-2"), False),
        (LinkCardinality.ONE_TO_MANY, ("node-1", "node-3"), True),
        (LinkCardinality.ONE_TO_MANY, ("node-3", "node-2"), False),
        (LinkCardinality.MANY_TO_ONE, ("node-1", "node-3"), False),
        (LinkCardinality.MANY_TO_ONE, ("node-3", "node-2"), True),
        (LinkCardinality.MANY_TO_MANY, ("node-1", "node-3"), True),
        (LinkCardinality.MANY_TO_MANY, ("node-3", "node-2"), True),
    ],
)
async def test_link_cardinality_matrix(
    cardinality: LinkCardinality,
    second_edge: tuple[str, str],
    allowed: bool,
) -> None:
    node = _object_type("ReviewCase")
    link = OntologyLinkType(
        schema_version="1.0.0",
        name="related_case",
        version="1.0.0",
        from_type="ReviewCase",
        to_type="ReviewCase",
        cardinality=cardinality,
    )
    store = InMemoryOntologyInstanceStore(object_types=(node,), link_types=(link,))
    for identifier in ("node-1", "node-2", "node-3"):
        await _upsert(store, identifier, "ReviewCase", "open")
    await store.upsert_link(
        OntologyLinkRecord(link_type="related_case", from_id="node-1", to_id="node-2")
    )
    candidate = OntologyLinkRecord(
        link_type="related_case",
        from_id=second_edge[0],
        to_id=second_edge[1],
    )
    if allowed:
        await store.upsert_link(candidate)
    else:
        with pytest.raises(OntologyInstanceValidationError, match="cardinality"):
            await store.upsert_link(candidate)


async def test_non_transitive_link_does_not_repeat_during_traversal() -> None:
    node = _object_type("ReviewCase")
    link = OntologyLinkType(
        schema_version="1.0.0",
        name="next_case",
        version="1.0.0",
        from_type="ReviewCase",
        to_type="ReviewCase",
        cardinality=LinkCardinality.MANY_TO_MANY,
        is_transitive=False,
    )
    store = InMemoryOntologyInstanceStore(object_types=(node,), link_types=(link,))
    for identifier in ("case-1", "case-2", "case-3"):
        await _upsert(store, identifier, "ReviewCase", "open")
    await store.upsert_link(
        OntologyLinkRecord(link_type="next_case", from_id="case-1", to_id="case-2")
    )
    await store.upsert_link(
        OntologyLinkRecord(link_type="next_case", from_id="case-2", to_id="case-3")
    )

    graph = await store.traverse(root_ids=("case-1",), max_depth=2)

    assert {item.id for item in graph.objects} == {"case-1", "case-2"}


async def test_transitive_link_repeats_during_traversal() -> None:
    node = _object_type("ReviewCase")
    link = OntologyLinkType(
        schema_version="1.0.0",
        name="ancestor_case",
        version="1.0.0",
        from_type="ReviewCase",
        to_type="ReviewCase",
        cardinality=LinkCardinality.MANY_TO_MANY,
        is_transitive=True,
    )
    store = InMemoryOntologyInstanceStore(object_types=(node,), link_types=(link,))
    for identifier in ("case-1", "case-2", "case-3"):
        await _upsert(store, identifier, "ReviewCase", "open")
    await store.upsert_link(
        OntologyLinkRecord(link_type="ancestor_case", from_id="case-1", to_id="case-2")
    )
    await store.upsert_link(
        OntologyLinkRecord(link_type="ancestor_case", from_id="case-2", to_id="case-3")
    )

    graph = await store.traverse(root_ids=("case-1",), max_depth=2)

    assert {item.id for item in graph.objects} == {"case-1", "case-2", "case-3"}


async def test_temporal_links_are_ordered_by_target_property() -> None:
    case = _object_type("ReviewCase")
    check = OntologyObjectType(
        schema_version="1.0.0",
        name="ReviewCheck",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "status": PropertyDecl(type=PropertyType.STRING, required=True),
            "position": PropertyDecl(type=PropertyType.INTEGER, required=True),
        },
    )
    link = OntologyLinkType(
        schema_version="1.0.0",
        name="ordered_check",
        version="1.0.0",
        from_type="ReviewCase",
        to_type="ReviewCheck",
        cardinality=LinkCardinality.ONE_TO_MANY,
        temporal_order=True,
        order_by_property="position",
    )
    store = InMemoryOntologyInstanceStore(object_types=(case, check), link_types=(link,))
    await _upsert(store, "review-1", "ReviewCase", "open")
    for identifier, position in (("check-late", 20), ("check-early", 3)):
        await store.upsert_object(
            OntologyObjectRecord(
                id=identifier,
                object_type="ReviewCheck",
                properties={"id": identifier, "status": "ready", "position": position},
            )
        )
        await store.upsert_link(
            OntologyLinkRecord(
                link_type="ordered_check",
                from_id="review-1",
                to_id=identifier,
            )
        )

    graph = await store.traverse(root_ids=("review-1",), max_depth=1)

    assert [item.to_id for item in graph.links] == ["check-early", "check-late"]


async def test_properties_are_normalized_to_canonical_json() -> None:
    timed = OntologyObjectType(
        schema_version="1.0.0",
        name="ReviewCase",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "status": PropertyDecl(type=PropertyType.STRING, required=True),
            "observed_at": PropertyDecl(type=PropertyType.DATETIME, required=True),
        },
    )
    store = InMemoryOntologyInstanceStore(object_types=(timed,), link_types=())
    stored = await store.upsert_object(
        OntologyObjectRecord(
            id="review-1",
            object_type="ReviewCase",
            properties={
                "id": "review-1",
                "status": "open",
                "observed_at": datetime(2026, 7, 29, 1, 2, 3, tzinfo=UTC),
            },
        )
    )
    assert stored.properties["observed_at"] == "2026-07-29T01:02:03Z"

    with pytest.raises(OntologyInstanceValidationError, match="finite numbers"):
        await store.upsert_object(
            OntologyObjectRecord(
                id="review-2",
                object_type="ReviewCase",
                properties={
                    "id": "review-2",
                    "status": "open",
                    "observed_at": "2026-07-29T01:02:03Z",
                    "extra": float("nan"),
                },
            )
        )
