"""Security tests for bounded ontology ObjectSet query projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.models import (
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
    ObjectTraversal,
)
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.query_gateway import (
    SecuredObjectSetQueryGateway,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.acl import (
    REDACTED_PLACEHOLDER,
    OntologyProjectionError,
    ProjectionRequest,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore
from pydantic import ValidationError


def _object_type(*, restricted_identity: bool = False) -> OntologyObjectType:
    return OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(
                type=PropertyType.STRING,
                required=True,
                access_scope=(CeilingRole.OWNER if restricted_identity else CeilingRole.READER),
                purpose_binding=(["identity-review"] if restricted_identity else []),
            ),
            "label": PropertyDecl(type=PropertyType.STRING),
            "operator_note": PropertyDecl(
                type=PropertyType.STRING,
                access_scope=CeilingRole.APPROVER,
            ),
            "incident_context": PropertyDecl(
                type=PropertyType.STRING,
                purpose_binding=["incident-response"],
            ),
            "metadata": PropertyDecl(type=PropertyType.OBJECT),
        },
    )


def _definition(*, limit: int = 100, purpose: str = "operations-review") -> ObjectSetDefinition:
    return ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        purpose=purpose,
        limit=limit,
    )


def _request(
    *,
    role: CeilingRole = CeilingRole.READER,
    purposes: frozenset[str] = frozenset({"operations-review"}),
    principal_scope_digest: str | None = None,
) -> ProjectionRequest:
    return ProjectionRequest(
        caller_role=role,
        declared_purposes=purposes,
        principal_scope_digest=principal_scope_digest,
    )


async def _gateway_with_records(
    object_type: OntologyObjectType,
    *records: OntologyObjectRecord,
    links: tuple[OntologyLinkRecord, ...] = (),
    source_complete: bool = True,
    snapshot_complete: bool = True,
    source_generation: str | None = None,
    transitive: bool = False,
) -> SecuredObjectSetQueryGateway:
    link_type = OntologyLinkType(
        schema_version="1.0.0",
        name="depends_on",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
        is_transitive=transitive,
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(object_type,),
        link_types=((link_type,) if links else ()),
        source_complete=snapshot_complete,
        source_generation=source_generation,
    )
    for record in records:
        await store.upsert_object(record)
    for link in links:
        await store.upsert_link(link)
    service = ObjectSetService(
        store=store,
        interfaces=compile_interfaces(
            interfaces=(), implementations=(), object_types=(object_type,)
        ),
        object_type_names=frozenset({object_type.name}),
    )
    return SecuredObjectSetQueryGateway(
        service=service,
        object_types={object_type.name: object_type},
        ontology_release=build_ontology_release(
            object_types=(object_type,),
            link_types=((link_type,) if links else ()),
        ),
        evaluation_cutoff=lambda: datetime(2026, 8, 8, tzinfo=UTC),
        graph_completeness=lambda: _async_bool(source_complete),
        max_as_of_skew=timedelta(seconds=1),
    )


async def _async_bool(value: bool) -> bool:
    return value


async def test_gateway_binds_authenticated_principal_scope_to_receipt() -> None:
    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={"id": "resource-a"},
        ),
    )

    result = await gateway.materialize(
        _definition(),
        projection_request=_request(principal_scope_digest="sha256:" + "a" * 64),
    )

    assert result.receipt.principal_scope_digest == "sha256:" + "a" * 64


@pytest.mark.parametrize(
    "count,limit,complete", [(1001, 1200, True), (1001, 1000, True), (2, 1200, False)]
)
async def test_secured_index_snapshot_preserves_atomic_completeness(
    count: int,
    limit: int,
    complete: bool,
) -> None:
    object_type = _object_type()
    records = tuple(
        OntologyObjectRecord(
            id=f"resource-{index}",
            object_type="Resource",
            properties={
                "id": f"resource-{index}",
                "operator_note": "private-marker",
            },
        )
        for index in range(count)
    )
    gateway = await _gateway_with_records(
        object_type,
        *records,
        snapshot_complete=complete,
        source_generation="snapshot-1",
    )
    scan = AsyncMock(wraps=gateway._service._store.scan_objects)
    gateway._service._store.scan_objects = scan
    operation = gateway.scan_snapshot(
        object_type_names=("Resource",),
        purpose="operations-review",
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        candidate_limit=limit,
        projection_request=_request(principal_scope_digest="sha256:" + "a" * 64),
    )
    if count > limit or not complete:
        with pytest.raises(ValueError, match="complete"):
            await operation
    else:
        result = await operation
        assert len(result.graph.objects) == count
        assert result.graph.source_generation == "snapshot-1"
        assert all(
            record.properties["operator_note"] == REDACTED_PLACEHOLDER
            for record in result.graph.objects
        )
        assert result.source_projection_digest.startswith("sha256:")
        assert result.principal_scope_digest == "sha256:" + "a" * 64
    scan.assert_awaited_once_with(object_types=("Resource",), candidate_limit=limit)


async def test_manifest_staging_reads_multiple_types_in_one_generation() -> None:
    from fdai.core.ontology_platform import build_query_manifest
    from fdai.delivery.catalog_search.ontology_snapshot_store import OntologyGenerationSnapshotStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    resource = _object_type()
    service_type = resource.model_copy(update={"name": "ExampleService"})
    declarations = (resource, service_type)
    store = InMemoryOntologyInstanceStore(
        object_types=declarations,
        link_types=(),
        source_generation="source-1",
    )
    for index in range(1002):
        await store.upsert_object(
            OntologyObjectRecord(
                id=f"example-{index}",
                object_type="Resource" if index < 1001 else "ExampleService",
                properties={"id": f"example-{index}", "operator_note": "private-marker"},
            )
        )
    release = build_ontology_release(object_types=declarations)
    manifest = build_query_manifest(
        release=release,
        object_types=declarations,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
    )
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=store,
            object_type_names=frozenset(item.name for item in declarations),
            interfaces=compile_interfaces(
                interfaces=(), implementations=(), object_types=declarations
            ),
        ),
        object_types={item.name: item for item in declarations},
        ontology_release=release,
        evaluation_cutoff=lambda: datetime(2026, 8, 8, tzinfo=UTC),
    )
    scan = AsyncMock(wraps=store.scan_objects)
    store.scan_objects = scan
    snapshots = OntologyGenerationSnapshotStore(InMemoryStateStore())
    staged = await snapshots.stage_manifest_from_gateway(
        gateway=gateway,
        manifest=manifest,
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        expected_source_generation="source-1",
        embedding_space_id="test-space",
        embedding_model_version="test-model",
        embedding_dimension=1,
    )
    restored = await snapshots.read(
        staged.snapshot_digest,
        manifest=manifest,
        source_generation="source-1",
        source_projection_digest=staged.source_projection_digest,
    )
    assert restored is not None and len(restored.documents) == 1004
    assert all("private-marker" not in item.text for item in restored.documents)
    scan.assert_awaited_once_with(
        object_types=("ExampleService", "Resource"), candidate_limit=19998
    )


@pytest.mark.parametrize("invalid", ["missing-ref", "old-ref", "identity-drift"])
async def test_index_snapshot_rejects_invalid_source_record_identity(invalid: str) -> None:
    from dataclasses import replace

    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a", object_type="Resource", properties={"id": "resource-a"}
        ),
        source_generation="source-1",
    )
    original = await gateway._service._store.scan_objects(object_types=("Resource",))
    record = original.objects[0]
    if invalid == "missing-ref":
        record = replace(record, type_ref=None)
    elif invalid == "old-ref":
        assert record.type_ref is not None
        record = replace(record, type_ref=record.type_ref.model_copy(update={"version": "0.1.0"}))
    else:
        record = replace(record, properties={"id": "another-resource"})
    gateway._service._store.scan_objects = AsyncMock(
        return_value=replace(original, objects=(record,))
    )
    with pytest.raises(ValueError, match="source record"):
        await gateway.scan_snapshot(
            object_type_names=("Resource",),
            purpose="operations-review",
            as_of=datetime(2026, 8, 8, tzinfo=UTC),
            candidate_limit=100,
            projection_request=_request(principal_scope_digest="sha256:" + "a" * 64),
        )


@pytest.mark.parametrize(
    "names,limit,scope",
    [
        ((), 100, "scoped"),
        (("Unknown",), 100, "scoped"),
        (("Resource",), 20001, "scoped"),
        (("Resource",), True, "scoped"),
        (("Resource",), 100, None),
    ],
)
async def test_index_snapshot_rejects_invalid_scope_before_store_io(names, limit, scope) -> None:
    gateway = await _gateway_with_records(_object_type(), source_generation="source-1")
    scan = AsyncMock(wraps=gateway._service._store.scan_objects)
    gateway._service._store.scan_objects = scan
    with pytest.raises(ValueError):
        await gateway.scan_snapshot(
            object_type_names=names,
            purpose="operations-review",
            as_of=datetime(2026, 8, 8, tzinfo=UTC),
            candidate_limit=limit,
            projection_request=_request(
                principal_scope_digest="sha256:" + "a" * 64 if scope else None
            ),
        )
    scan.assert_not_awaited()


@pytest.mark.parametrize(
    "drift", [None, "fabricated", "missing", "changed", "generation", "embedding", "vectors"]
)
async def test_snapshot_validation_reconstructs_runtime_objects_from_current_graph(
    drift: str | None,
) -> None:
    from dataclasses import replace

    from fdai.core.ontology_platform import build_query_manifest
    from fdai.delivery.catalog_search.generation import build_ontology_semantic_generation
    from fdai.delivery.catalog_search.ontology_snapshot_store import (
        OntologyGenerationSnapshotStore,
        OntologyStagedProjection,
    )
    from fdai.delivery.catalog_search.ontology_snapshot_validation import (
        validate_snapshot_against_current_graph,
    )
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    object_type = _object_type()
    record = OntologyObjectRecord(
        id="resource-a",
        object_type="Resource",
        properties={"id": "resource-a", "label": "original"},
    )
    gateway = await _gateway_with_records(
        object_type, record, source_generation="source-2" if drift == "generation" else "source-1"
    )
    manifest = build_query_manifest(
        release=build_ontology_release(object_types=(object_type,)),
        object_types=(object_type,),
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
    )
    objects = (record,)
    if drift == "fabricated":
        objects += (
            OntologyObjectRecord(
                id="invented", object_type="Resource", properties={"id": "invented"}
            ),
        )
    elif drift == "missing":
        objects = ()
    elif drift == "changed":
        objects = (
            OntologyObjectRecord(
                id=record.id,
                object_type=record.object_type,
                properties={"id": record.id, "label": "modified"},
            ),
        )
    build = build_ontology_semantic_generation(
        manifest=manifest,
        runtime_objects=objects,
        embedding_space_id="test-space",
        embedding_model_version="test-model",
        embedding_dimension=1,
    )
    if drift == "vectors":
        build = replace(
            build, documents=tuple(replace(item, embedding=(0.1,)) for item in build.documents)
        )
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    projection_digest = "sha256:" + "c" * 64
    snapshot_digest = await snapshots.stage(
        build=build,
        manifest=manifest,
        source_generation="source-1",
        source_projection_digest=projection_digest,
    )
    writes_before = len(state._state)
    operation = validate_snapshot_against_current_graph(
        snapshots=snapshots,
        staged=OntologyStagedProjection(snapshot_digest, projection_digest, "source-1"),
        gateway=gateway,
        manifest=manifest,
        as_of=datetime(2026, 8, 8, tzinfo=UTC),
        embedding_space_id="other-space" if drift == "embedding" else "test-space",
        embedding_model_version="test-model",
        embedding_dimension=1,
        validator_id="Heimdall-test",
    )
    if drift:
        with pytest.raises(ValueError, match="snapshot validation"):
            await operation
    else:
        validated = await operation
        assert validated.snapshot_digest == snapshot_digest
        assert validated.receipt_digest.startswith("sha256:")
        assert validated.generation_digest == build.metadata.generation_digest
    assert len(state._state) == writes_before


@pytest.mark.parametrize(
    "failure", [None, "incomplete", "generation", "missing", "truncated", "identity", "release"]
)
async def test_secured_semantic_staging_preserves_source_and_excludes_private_values(
    failure: str | None,
) -> None:
    from fdai.core.ontology_platform import build_query_manifest
    from fdai.delivery.catalog_search.ontology_snapshot_store import (
        OntologyGenerationSnapshotStore,
        OntologySnapshotCorruptionError,
    )
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    object_type = _object_type(restricted_identity=failure == "identity")
    records = tuple(
        OntologyObjectRecord(
            id=f"resource-{index}",
            object_type="Resource",
            properties={"id": f"resource-{index}", "operator_note": "synthetic-private-value"},
        )
        for index in range(2)
    )
    gateway = await _gateway_with_records(
        object_type,
        *records,
        source_complete=failure != "incomplete",
        snapshot_complete=failure != "incomplete",
        source_generation=None if failure == "missing" else "source-1",
    )
    manifest_type = (
        object_type.model_copy(update={"version": "2.0.0"}) if failure == "release" else object_type
    )
    manifest = build_query_manifest(
        release=build_ontology_release(object_types=(manifest_type,)),
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=(manifest_type,),
    )
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    definition = _definition(limit=1 if failure == "truncated" else 100).model_copy(
        update={"include_relationships": False}
    )

    async def stage():
        return await snapshots.stage_from_gateway(
            gateway=gateway,
            definition=definition,
            manifest=manifest,
            expected_source_generation="other-source" if failure == "generation" else "source-1",
            embedding_space_id="projection-test",
            embedding_model_version="projection-test",
            embedding_dimension=1,
        )

    if failure is not None:
        with pytest.raises(ValueError, match="source evidence"):
            await stage()
        assert state._state == {}
        return
    staged = await stage()
    restored = await snapshots.read(
        staged.snapshot_digest,
        manifest=manifest,
        source_generation=staged.source_generation,
        source_projection_digest=staged.source_projection_digest,
    )
    assert restored is not None
    object_documents = [
        item for item in restored.documents if item.document_kind == "ontology_object"
    ]
    assert len(object_documents) == 2
    assert all("synthetic-private-value" not in item.text for item in restored.documents)
    assert all("operator_note" not in item.text for item in object_documents)
    with pytest.raises(OntologySnapshotCorruptionError):
        await snapshots.read(
            staged.snapshot_digest,
            manifest=manifest,
            source_generation=staged.source_generation,
        )


@pytest.mark.parametrize("property_name", ["operator_note", "incident_context", "undeclared"])
async def test_secured_semantic_staging_rejects_partial_or_cross_purpose_selection_before_io(
    property_name: str,
) -> None:
    from fdai.core.ontology_platform import build_query_manifest
    from fdai.delivery.catalog_search.ontology_snapshot_store import OntologyGenerationSnapshotStore
    from fdai.shared.providers.testing.state_store import InMemoryStateStore

    object_type = _object_type()
    manifest = build_query_manifest(
        release=build_ontology_release(object_types=(object_type,)),
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=(object_type,),
    )
    definition = _definition().model_copy(
        update={
            "include_relationships": False,
            "predicates": (ObjectPredicate(property=property_name, equals="example"),),
        }
    )
    gateway = AsyncMock(spec=SecuredObjectSetQueryGateway)
    state = InMemoryStateStore()
    snapshots = OntologyGenerationSnapshotStore(state)
    for rejected in (
        definition,
        definition.model_copy(update={"predicates": (), "purpose": "incident-response"}),
        definition.model_copy(update={"predicates": (), "include_relationships": True}),
        definition.model_copy(update={"predicates": (), "object_ids": ("resource-a",)}),
    ):
        with pytest.raises(ValueError, match="single-purpose type selection"):
            await snapshots.stage_from_gateway(
                gateway=gateway,
                definition=rejected,
                manifest=manifest,
                expected_source_generation="source-1",
                embedding_space_id="projection-test",
                embedding_model_version="projection-test",
                embedding_dimension=1,
            )
    gateway.materialize.assert_not_awaited()
    assert state._state == {}


@pytest.mark.parametrize("property_name", ["operator_note", "incident_context", "undeclared"])
async def test_gateway_rejects_unreadable_predicates_before_store_access(
    property_name: str,
) -> None:
    gateway = await _gateway_with_records(_object_type())
    materialize = AsyncMock(wraps=gateway._service.materialize)
    gateway._service.materialize = materialize
    definition = _definition().model_copy(
        update={"predicates": (ObjectPredicate(property=property_name, equals="example"),)}
    )

    with pytest.raises(PermissionError, match="predicate property is not readable"):
        await gateway.materialize(definition, projection_request=_request())

    materialize.assert_not_awaited()


async def test_gateway_applies_role_redaction_to_every_returned_object() -> None:
    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={
                "id": "resource-a",
                "label": "API",
                "operator_note": "restricted-a",
            },
        ),
        OntologyObjectRecord(
            id="resource-b",
            object_type="Resource",
            properties={
                "id": "resource-b",
                "label": "Worker",
                "operator_note": "restricted-b",
            },
        ),
    )

    result = await gateway.materialize(_definition(), projection_request=_request())

    projected_notes = [
        record.properties["operator_note"] for record in result.materialization.graph.objects
    ]
    assert projected_notes == [
        REDACTED_PLACEHOLDER,
        REDACTED_PLACEHOLDER,
    ]
    assert result.receipt.redactions.access_scope_count == 2
    assert result.receipt.redactions.objects_with_redactions == 2


async def test_gateway_rejects_exact_selection_of_hidden_identity_before_materialization() -> None:
    gateway = await _gateway_with_records(_object_type(restricted_identity=True))
    materialize = AsyncMock(wraps=gateway._service.materialize)
    gateway._service.materialize = materialize
    with pytest.raises(PermissionError, match="not readable"):
        await gateway.materialize(
            _definition().model_copy(update={"object_ids": ("hidden",)}),
            projection_request=_request(),
        )
    materialize.assert_not_awaited()


async def test_gateway_rejects_hidden_traversal_root_before_expansion() -> None:
    gateway = await _gateway_with_records(
        _object_type(restricted_identity=True),
        OntologyObjectRecord(id="hidden", object_type="Resource", properties={"id": "hidden"}),
    )
    materialize = AsyncMock(wraps=gateway._service.materialize)
    gateway._service.materialize = materialize
    with pytest.raises(PermissionError, match="roots are not authorized"):
        await gateway.materialize(
            _definition().model_copy(
                update={
                    "root_ids": ("hidden",),
                    "traversal": ObjectTraversal(link_types=("depends_on",)),
                }
            ),
            projection_request=_request(),
        )
    materialize.assert_not_awaited()


async def test_resource_receipt_preserves_incomplete_source_without_query_truncation() -> None:
    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={"id": "resource-a", "label": "API"},
        ),
        source_complete=False,
    )

    result = await gateway.materialize(_definition(), projection_request=_request())

    assert result.materialization.truncated is False
    assert result.receipt.truncated is False
    assert result.receipt.source_complete is False
    assert result.receipt.schema_version == "1.2.0"
    assert result.receipt.complete is False

    legacy_payload = result.receipt.model_dump(mode="json")
    legacy_payload["schema_version"] = "1.1.0"
    legacy_payload.pop("source_complete")
    legacy_payload.pop("source_generation")
    legacy = SecuredObjectSetQueryReceipt.model_validate(legacy_payload)
    assert legacy.schema_version == "1.1.0"
    assert legacy.source_complete is True
    assert legacy.source_generation is None


async def test_object_only_resource_receipt_ignores_relationship_completeness() -> None:
    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={"id": "resource-a", "label": "API"},
        ),
        source_complete=False,
    )

    result = await gateway.materialize(
        ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
            as_of=datetime(2026, 8, 8, tzinfo=UTC),
            purpose="operations-review",
            include_relationships=False,
        ),
        projection_request=_request(),
    )

    assert result.receipt.source_complete is True
    assert result.receipt.complete is True


async def test_gateway_applies_only_the_definition_purpose() -> None:
    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={
                "id": "resource-a",
                "label": "API",
                "incident_context": "restricted incident details",
            },
        ),
    )

    result = await gateway.materialize(
        _definition(),
        projection_request=_request(purposes=frozenset({"operations-review", "incident-response"})),
    )

    record = result.materialization.graph.objects[0]
    assert record.properties["incident_context"] == REDACTED_PLACEHOLDER
    assert result.receipt.redactions.purpose_binding_count == 1
    with pytest.raises(PermissionError, match="purpose was not declared"):
        await gateway.materialize(
            _definition(),
            projection_request=_request(purposes=frozenset({"incident-response"})),
        )


async def test_gateway_hides_redacted_endpoint_identity_and_drops_dangling_link() -> None:
    object_type = _object_type(restricted_identity=True)
    definition = _definition()
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord(
                    id="resource-secret",
                    object_type="Resource",
                    properties={"id": "resource-secret", "label": "Visible label"},
                ),
            ),
            links=(
                OntologyLinkRecord(
                    link_type="depends_on",
                    from_id="resource-secret",
                    to_id="hidden-resource",
                ),
            ),
        ),
        concrete_types=("Resource",),
        truncated=False,
    )
    service = cast(ObjectSetService, _StaticObjectSetService(materialization))
    gateway = SecuredObjectSetQueryGateway(
        service=service,
        object_types={object_type.name: object_type},
        ontology_release=build_ontology_release(object_types=(object_type,)),
        evaluation_cutoff=lambda: datetime(2026, 8, 8, tzinfo=UTC),
    )

    result = await gateway.materialize(definition, projection_request=_request())

    graph = result.materialization.graph
    assert graph.objects[0].id == "redacted-object-1"
    assert graph.links == ()
    assert "resource-secret" not in str(graph)
    assert "hidden-resource" not in str(graph)
    assert result.receipt.redactions.redacted_identity_count == 1
    assert result.receipt.redactions.removed_link_count == 1


async def test_gateway_preserves_typed_link_metadata_without_false_redaction() -> None:
    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={"id": "resource-a", "label": "API"},
        ),
        OntologyObjectRecord(
            id="resource-b",
            object_type="Resource",
            properties={"id": "resource-b", "label": "Database"},
        ),
        links=(
            OntologyLinkRecord(
                link_type="depends_on",
                from_id="resource-a",
                to_id="resource-b",
                properties={
                    LINK_OBSERVATION_METADATA_PROPERTY: LinkObservationMetadata(
                        state_fact=StateFactMetadata(
                            lane=StateFactLane.OBSERVED,
                            authority=StateFactAuthority.PROVIDER,
                            source_identity="inventory-provider",
                            source_revision="revision-1",
                            effective_at=datetime(2026, 8, 8, tzinfo=UTC),
                            recorded_at=datetime(2026, 8, 8, tzinfo=UTC),
                            evidence_cutoff=datetime(2026, 8, 8, tzinfo=UTC),
                            freshness_ceiling_seconds=300,
                            completeness=1.0,
                            synthetic=False,
                            evidence_refs=("evidence-link-1",),
                        ),
                        verification_method="provider-observation",
                        verified=False,
                    ).to_mapping(),
                },
            ),
        ),
    )

    result = await gateway.materialize(_definition(), projection_request=_request())

    properties = result.materialization.graph.links[0].properties
    assert set(properties) == {LINK_OBSERVATION_METADATA_PROPERTY}
    metadata = properties[LINK_OBSERVATION_METADATA_PROPERTY]
    assert metadata["state_fact"]["source_identity"] == "inventory-provider"
    assert result.receipt.redactions.links_with_redactions == 0
    assert result.receipt.redactions.redacted_link_property_count == 0


async def test_gateway_allocates_collision_safe_aliases_and_preserves_link_closure() -> None:
    restricted_type = _object_type(restricted_identity=True)
    visible_type = OntologyObjectType(
        schema_version="1.0.0",
        name="VisibleResource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    definition = _definition()
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord(
                    id="resource-secret",
                    object_type="Resource",
                    properties={"id": "resource-secret", "label": "Hidden identity"},
                ),
                OntologyObjectRecord(
                    id="redacted-object-1",
                    object_type="VisibleResource",
                    properties={"id": "redacted-object-1"},
                ),
            ),
            links=(
                OntologyLinkRecord(
                    link_type="depends_on",
                    from_id="resource-secret",
                    to_id="redacted-object-1",
                ),
            ),
        ),
        concrete_types=("Resource", "VisibleResource"),
        truncated=False,
    )
    gateway = SecuredObjectSetQueryGateway(
        service=cast(ObjectSetService, _StaticObjectSetService(materialization)),
        object_types={
            restricted_type.name: restricted_type,
            visible_type.name: visible_type,
        },
        ontology_release=build_ontology_release(
            object_types=(restricted_type, visible_type),
        ),
        evaluation_cutoff=lambda: datetime(2026, 8, 8, tzinfo=UTC),
    )

    result = await gateway.materialize(definition, projection_request=_request())

    graph = result.materialization.graph
    projected_ids = {record.id for record in graph.objects}
    assert len(projected_ids) == len(graph.objects) == 2
    assert "redacted-object-1" in projected_ids
    assert "resource-secret" not in projected_ids
    assert all(
        link.from_id in projected_ids and link.to_id in projected_ids for link in graph.links
    )
    assert "resource-secret" not in str(result)


async def test_gateway_preserves_object_set_truncation() -> None:
    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={"id": "resource-a", "label": "API"},
        ),
        OntologyObjectRecord(
            id="resource-b",
            object_type="Resource",
            properties={"id": "resource-b", "label": "Worker"},
        ),
    )

    result = await gateway.materialize(
        _definition(limit=1),
        projection_request=_request(),
    )

    assert result.materialization.truncated is True
    assert result.materialization.truncation_reason == "result_limit"
    assert result.materialization.graph.truncated is True
    assert result.receipt.truncated is True
    assert result.receipt.truncation_reason == "result_limit"


async def test_gateway_fails_closed_for_unknown_returned_declaration() -> None:
    definition = _definition()
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord(
                    id="unknown-a",
                    object_type="UnknownType",
                    properties={"id": "unknown-a"},
                ),
            )
        ),
        concrete_types=("UnknownType",),
        truncated=False,
    )
    service = cast(ObjectSetService, _StaticObjectSetService(materialization))
    gateway = SecuredObjectSetQueryGateway(
        service=service,
        object_types={"Resource": _object_type()},
        ontology_release=build_ontology_release(object_types=(_object_type(),)),
        evaluation_cutoff=lambda: datetime(2026, 8, 8, tzinfo=UTC),
    )

    with pytest.raises(OntologyProjectionError, match="missing ObjectType declaration"):
        await gateway.materialize(definition, projection_request=_request())


async def test_gateway_receipt_is_immutable_and_grants_no_authority() -> None:
    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={"id": "resource-a", "label": "API"},
        ),
    )

    result = await gateway.materialize(_definition(), projection_request=_request())

    assert result.receipt.execution_authority is False
    assert result.receipt.ontology_release.digest.startswith("sha256:")
    assert result.receipt.projected_result_digest.startswith("sha256:")
    assert result.receipt.observation_cutoff == datetime(2026, 8, 8, tzinfo=UTC)
    assert result.receipt.temporal_support == "current_state_only"
    assert "approval" not in type(result.receipt).model_fields
    with pytest.raises(ValidationError, match="frozen"):
        result.receipt.execution_authority = True  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        result.receipt.redactions.removed_link_count = 99  # type: ignore[misc]


async def test_gateway_rejects_past_and_future_as_of_for_current_state_store() -> None:
    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={"id": "resource-a", "label": "API"},
        ),
    )
    cutoff = datetime(2026, 8, 8, tzinfo=UTC)

    for unsupported_as_of in (
        cutoff - timedelta(seconds=2),
        cutoff + timedelta(seconds=2),
    ):
        with pytest.raises(ValueError, match="current-state.*as_of"):
            await gateway.materialize(
                _definition().model_copy(update={"as_of": unsupported_as_of}),
                projection_request=_request(),
            )


async def test_gateway_deep_freezes_result_and_detects_receipt_mismatch() -> None:
    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={
                "id": "resource-a",
                "label": "API",
                "metadata": {"owners": ["team-a"], "nested": {"region": "example"}},
            },
        ),
    )

    result = await gateway.materialize(_definition(), projection_request=_request())
    metadata = cast(
        dict[str, object], result.materialization.graph.objects[0].properties["metadata"]
    )
    digest_before = result.receipt.projected_result_digest

    with pytest.raises(TypeError):
        metadata["nested"] = {"region": "changed"}
    owners = cast(tuple[str, ...], metadata["owners"])
    with pytest.raises(TypeError):
        owners[0] = "changed"  # type: ignore[index]
    assert result.receipt.projected_result_digest == digest_before

    mismatched_receipt = result.receipt.model_copy(
        update={"projected_result_digest": "sha256:" + "0" * 64}
    )
    with pytest.raises(ValueError, match="projected result digest"):
        SecuredObjectSetQueryResult(
            materialization=result.materialization,
            receipt=mismatched_receipt,
        )


class _StaticObjectSetService:
    def __init__(self, materialization: ObjectSetMaterialization) -> None:
        self._materialization = materialization

    async def materialize(self, definition: ObjectSetDefinition) -> ObjectSetMaterialization:
        if definition != self._materialization.definition:
            raise AssertionError("unexpected ObjectSet definition")
        return self._materialization
