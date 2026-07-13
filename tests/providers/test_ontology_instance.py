"""Runtime ontology instance validation and bounded graph queries."""

from __future__ import annotations

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
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore


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