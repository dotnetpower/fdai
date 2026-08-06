from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.delivery.persistence import postgres_ontology
from fdai.shared.contracts.models import (
    OntologyDeclarationKind,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyInstanceValidationError


def test_projection_revision_fence_rejects_unpinned_overwrite() -> None:
    with pytest.raises(OntologyInstanceValidationError, match="revision fence"):
        postgres_ontology._require_projection_revision(  # noqa: SLF001 - persistence boundary
            object_id="review-1",
            expected=0,
            current=1,
        )


def test_object_row_decode_normalizes_datetime() -> None:
    record = postgres_ontology._object_from_row(  # noqa: SLF001 - persistence boundary
        {
            "id": "resource-example",
            "object_type": "Resource",
            "properties": {"observed_at": datetime(2026, 7, 31, tzinfo=UTC)},
            "revision": 1,
        }
    )

    assert record.properties["observed_at"] == "2026-07-31T00:00:00Z"


def test_link_row_decode_rejects_excessive_nesting() -> None:
    nested: object = "leaf"
    for _ in range(34):
        nested = {"next": nested}

    with pytest.raises(OntologyInstanceValidationError, match="nesting depth"):
        postgres_ontology._link_from_row(  # noqa: SLF001 - persistence boundary
            {
                "link_type": "implemented_by",
                "from_id": "service-example",
                "to_id": "workload-example",
                "properties": {"nested": nested},
            }
        )


def test_object_row_decode_resolves_pinned_historical_release() -> None:
    version_one = OntologyObjectType(
        schema_version="1.0.0",
        name="ReviewCase",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    historical = build_ontology_release(object_types=(version_one,))
    latest = build_ontology_release(
        object_types=(version_one.model_copy(update={"version": "2.0.0"}),)
    )

    record = postgres_ontology._object_from_row(  # noqa: SLF001 - persistence boundary
        {
            "id": "review-1",
            "object_type": "ReviewCase",
            "properties": {"id": "review-1"},
            "revision": 1,
            "type_version": "1.0.0",
            "catalog_digest": historical.digest,
        },
        releases={latest.digest: latest, historical.digest: historical},
    )

    assert record.type_ref == historical.type_ref(
        OntologyDeclarationKind.OBJECT,
        "ReviewCase",
    )


def test_object_row_decode_rejects_unavailable_pinned_release() -> None:
    version_one = OntologyObjectType(
        schema_version="1.0.0",
        name="ReviewCase",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    historical = build_ontology_release(object_types=(version_one,))
    latest = build_ontology_release(
        object_types=(version_one.model_copy(update={"version": "2.0.0"}),)
    )

    with pytest.raises(RuntimeError, match="release .* is unavailable"):
        postgres_ontology._object_from_row(  # noqa: SLF001 - persistence boundary
            {
                "id": "review-1",
                "object_type": "ReviewCase",
                "properties": {"id": "review-1"},
                "revision": 1,
                "type_version": "1.0.0",
                "catalog_digest": historical.digest,
            },
            releases={latest.digest: latest},
        )
