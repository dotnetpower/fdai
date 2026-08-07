"""PostgreSQL ontology type-reference decoding regressions."""

from __future__ import annotations

import pytest

from fdai.delivery.persistence.postgres_ontology import _object_from_row
from fdai.shared.contracts.models import OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release


def _release():
    object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    return build_ontology_release(object_types=(object_type,))


def test_object_row_preserves_persisted_historical_type_ref() -> None:
    release = _release()
    record = _object_from_row(
        {
            "id": "workload-a",
            "object_type": "Workload",
            "properties": {"id": "workload-a"},
            "revision": 3,
            "type_version": "1.0.0",
            "catalog_digest": release.digest,
        },
        releases={release.digest: release},
    )

    assert record.type_ref is not None
    assert record.type_ref.version == "1.0.0"
    assert record.type_ref.catalog_digest == release.digest


def test_object_row_rejects_partial_type_ref() -> None:
    release = _release()
    with pytest.raises(RuntimeError, match="type reference is incomplete"):
        _object_from_row(
            {
                "id": "workload-a",
                "object_type": "Workload",
                "properties": {"id": "workload-a"},
                "revision": 3,
                "type_version": "1.0.0",
                "catalog_digest": None,
            },
            releases={release.digest: release},
        )


def test_object_row_keeps_pre_migration_type_ref_unknown() -> None:
    release = _release()
    record = _object_from_row(
        {
            "id": "workload-a",
            "object_type": "Workload",
            "properties": {"id": "workload-a"},
            "revision": 3,
            "type_version": None,
            "catalog_digest": None,
        },
        releases={release.digest: release},
    )

    assert record.type_ref is None
