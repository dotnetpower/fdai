"""Security tests for bounded ontology ObjectSet query projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.query_gateway import (
    SecuredObjectSetQueryGateway,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryReceiptIssuer,
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
) -> ProjectionRequest:
    return ProjectionRequest(caller_role=role, declared_purposes=purposes)


async def _gateway_with_records(
    object_type: OntologyObjectType,
    *records: OntologyObjectRecord,
    links: tuple[OntologyLinkRecord, ...] = (),
    receipt_issuer: SecuredObjectSetQueryReceiptIssuer | None = None,
) -> SecuredObjectSetQueryGateway:
    link_type = OntologyLinkType(
        schema_version="1.0.0",
        name="depends_on",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(object_type,),
        link_types=((link_type,) if links else ()),
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
        max_as_of_skew=timedelta(seconds=1),
        receipt_issuer=receipt_issuer,
    )


async def test_gateway_seals_exact_receipt_with_injected_issuer() -> None:
    issued: list[SecuredObjectSetQueryReceipt] = []

    class _Issuer:
        def issue(self, receipt: SecuredObjectSetQueryReceipt) -> None:
            issued.append(receipt)

    object_type = _object_type()
    gateway = await _gateway_with_records(
        object_type,
        OntologyObjectRecord(
            id="resource-a",
            object_type="Resource",
            properties={"id": "resource-a", "label": "API"},
        ),
        receipt_issuer=_Issuer(),
    )

    result = await gateway.materialize(_definition(), projection_request=_request())

    assert issued == [result.receipt]


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


async def test_gateway_strips_all_link_properties_and_records_redaction() -> None:
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
                    "provider_resource_id": "/subscriptions/raw-secret/resource-a",
                    "evidence": {"target_id": "raw-secret-resource-b"},
                },
            ),
        ),
    )

    result = await gateway.materialize(_definition(), projection_request=_request())

    assert result.materialization.graph.links[0].properties == {}
    assert result.receipt.redactions.links_with_redactions == 1
    assert result.receipt.redactions.redacted_link_property_count == 2
    assert "raw-secret" not in str(result)


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
