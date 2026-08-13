from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fdai.delivery.persistence.postgres_ontology import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
    _object_from_row,
)
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyDeclarationKind,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release


def _async_context(value: object) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=value)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


async def test_sync_catalog_upserts_objects_before_links() -> None:
    object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="WorkflowDefinition",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    link_type = OntologyLinkType(
        schema_version="1.0.0",
        name="derived_from_workflow",
        version="1.0.0",
        from_type="WorkflowDefinition",
        to_type="WorkflowDefinition",
        cardinality=LinkCardinality.MANY_TO_ONE,
    )
    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=connection)
    connection.__aexit__ = AsyncMock(return_value=None)
    connection.transaction.return_value = _async_context(connection)
    connection.execute = AsyncMock()
    store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn="postgresql://example"),
        object_types=(object_type,),
        link_types=(link_type,),
    )
    store._connect = AsyncMock(return_value=connection)  # type: ignore[method-assign]

    await store.sync_catalog()

    release_query, release_parameters = connection.execute.await_args_list[1].args
    object_query, object_parameters = connection.execute.await_args_list[2].args
    link_query, link_parameters = connection.execute.await_args_list[3].args
    assert "INSERT INTO ontology_release" in release_query
    assert release_parameters[0].startswith("sha256:")
    assert "INSERT INTO ontology_object_type" in object_query
    assert "INSERT INTO ontology_link_type" in link_query
    assert object_parameters[:3] == ("WorkflowDefinition", "1.0.0", "id")
    assert '"required": true' in object_parameters[3]
    assert link_parameters == (
        "derived_from_workflow",
        "1.0.0",
        "WorkflowDefinition",
        "WorkflowDefinition",
        "many_to_one",
        False,
        False,
        False,
        None,
        None,
    )


async def test_sync_catalog_loads_historical_release_for_restart_reads() -> None:
    current_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
        description="current declaration",
    )
    historical_type = current_type.model_copy(update={"description": "historical declaration"})
    historical_release = build_ontology_release(object_types=(historical_type,))
    release_cursor = MagicMock()
    release_cursor.fetchall = AsyncMock(
        return_value=(
            {
                "digest": historical_release.digest,
                "manifest": historical_release.model_dump(mode="json"),
            },
        )
    )
    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=connection)
    connection.__aexit__ = AsyncMock(return_value=None)
    connection.transaction.return_value = _async_context(connection)
    connection.execute = AsyncMock(side_effect=[None, None, None, release_cursor])
    store = PostgresOntologyInstanceStore(
        config=PostgresOntologyInstanceStoreConfig(dsn="postgresql://example"),
        object_types=(current_type,),
        link_types=(),
    )
    store._connect = AsyncMock(return_value=connection)  # type: ignore[method-assign]

    await store.sync_catalog()

    assert store._releases[historical_release.digest] == historical_release
    restored = _object_from_row(
        {
            "id": "workload-1",
            "object_type": "Workload",
            "properties": {"id": "workload-1"},
            "revision": 1,
            "type_version": "1.0.0",
            "catalog_digest": historical_release.digest,
        },
        releases=store._releases,
    )
    assert restored.type_ref == historical_release.type_ref(
        kind=OntologyDeclarationKind.OBJECT,
        name="Workload",
    )
