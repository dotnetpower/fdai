from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fdai.delivery.persistence.postgres_ontology import (
    PostgresOntologyInstanceStore,
    PostgresOntologyInstanceStoreConfig,
)
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)


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

    object_query, object_parameters = connection.execute.await_args_list[1].args
    link_query, link_parameters = connection.execute.await_args_list[2].args
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
        None,
    )
