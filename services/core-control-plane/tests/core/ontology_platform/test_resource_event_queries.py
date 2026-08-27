"""Verified Resource event history FunctionType tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.models import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
    ObjectSetTruncationReason,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.core.ontology_platform.resource_event_queries import (
    RESOURCE_EVENT_FUNCTION_NAME,
    RESOURCE_EVENT_MEASURE_CONCEPTS,
    ResourceEventCollection,
    ResourceEventObservation,
    resource_event_function_type,
    resource_event_history_function,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord

NOW = datetime(2026, 8, 21, 17, 0, tzinfo=UTC)


def _resource(name: str) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=f"resource-{name}",
        object_type="Resource",
        properties={
            "id": f"resource-{name}",
            "name": name,
            "type": "container-app",
        },
    )


def _kubernetes_resource(name: str) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=f"resource-{name}",
        object_type="Resource",
        properties={
            "id": f"resource-{name}",
            "name": name,
            "type": "kubernetes.pod",
            "properties": {
                "cluster_ref": "cluster-example",
                "uid": "pod-uid-example",
                "status": "Running",
            },
        },
    )


def _query_result(
    objects: tuple[OntologyObjectRecord, ...],
    *,
    complete: bool = True,
    exact_target: str | None = None,
) -> SecuredObjectSetQueryResult:
    declaration = resource_event_function_type()
    release = build_ontology_release(function_types=(declaration,))
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        predicates=(
            (
                ObjectPredicate(
                    property="name",
                    operator=ObjectPredicateOperator.EQUALS,
                    equals=exact_target,
                ),
            )
            if exact_target is not None
            else ()
        ),
        limit=2 if exact_target is not None else 1000,
    )
    reason = None if complete else ObjectSetTruncationReason.RESULT_LIMIT
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(objects=objects, links=(), truncated=not complete),
        concrete_types=("Resource",),
        truncated=not complete,
        truncation_reason=reason,
    )
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=release.ref(),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="operations-review",
            caller_role="reader",
            observation_cutoff=NOW,
            as_of_skew_seconds=0,
            returned_object_count=len(objects),
            returned_link_count=0,
            complete=complete,
            truncated=not complete,
            truncation_reason=reason,
            redactions=ObjectSetRedactionSummary(
                objects_with_redactions=0,
                redacted_identity_count=0,
                access_scope_count=0,
                purpose_binding_count=0,
                undeclared_property_count=0,
                links_with_redactions=0,
                redacted_link_property_count=0,
                removed_link_count=0,
            ),
        ),
    )


class _Reader:
    def __init__(self, result: ResourceEventCollection) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], tuple[str, ...], int]] = []

    async def read_history(
        self,
        *,
        resource_ids: tuple[str, ...],
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection:
        self.calls.append((resource_ids, event_families, lookback_seconds))
        return self.result


class _IdentityReader(_Reader):
    def __init__(self, result: ResourceEventCollection) -> None:
        super().__init__(result)
        self.identity: Mapping[str, Mapping[str, str]] | None = None

    async def read_history_with_identity(
        self,
        *,
        resource_ids: tuple[str, ...],
        resource_identity: Mapping[str, Mapping[str, str]],
        event_families: tuple[str, ...],
        lookback_seconds: int,
    ) -> ResourceEventCollection:
        self.identity = resource_identity
        with pytest.raises(TypeError):
            resource_identity[resource_ids[0]]["uid"] = "changed"  # type: ignore[index]
        with pytest.raises(TypeError):
            resource_identity["other"] = {}  # type: ignore[index]
        return self.result


async def _invoke(
    reader: _Reader,
    query_result: SecuredObjectSetQueryResult,
) -> dict[str, object]:
    declaration = resource_event_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        resource_event_history_function(release, reader=reader),
    )
    result = await registry.invoke(
        RESOURCE_EVENT_FUNCTION_NAME,
        {
            "query_result": query_result.model_dump(mode="json"),
            "event_families": list(RESOURCE_EVENT_MEASURE_CONCEPTS),
            "lookback_seconds": 3600,
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


def _collection(
    resource_ids: tuple[str, ...],
    *,
    events: tuple[ResourceEventObservation, ...] = (),
    complete: bool = True,
    limitation: str | None = None,
) -> ResourceEventCollection:
    return ResourceEventCollection(
        resource_ids=resource_ids,
        events=events,
        observed_at=NOW,
        complete=complete,
        limitation=limitation,
        attempt_ref="azure-resource-event:attempt",
    )


def test_event_function_declares_server_owned_read_contract() -> None:
    declaration = resource_event_function_type()

    assert declaration.name == RESOURCE_EVENT_FUNCTION_NAME
    assert set(declaration.input_schema["properties"]) == {
        "query_result",
        "event_families",
        "lookback_seconds",
    }
    assert declaration.required_role is CeilingRole.READER
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False


async def test_event_function_projects_verified_chronology_and_partial_status() -> None:
    resources = (_resource("service-a"), _resource("service-b"))
    reader = _Reader(
        _collection(
            ("resource-service-a", "resource-service-b"),
            events=(
                ResourceEventObservation(
                    resource_id="resource-service-a",
                    event_family="resource_event.resource_health",
                    event_kind="availability_status",
                    status="unavailable",
                    classification="platform_initiated",
                    occurred_at=NOW - timedelta(minutes=10),
                    evidence_ref="azure-resource-event:event-a",
                ),
            ),
            complete=False,
            limitation="source_coverage_incomplete",
        )
    )

    result = await _invoke(reader, _query_result(resources))

    assert result["complete"] is False
    assert result["truncation_reason"] == "source_coverage_incomplete"
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"] == {
        "classification": "platform_initiated",
        "event_family": "resource_event.resource_health",
        "event_kind": "availability_status",
        "evidence_ref": "azure-resource-event:event-a",
        "execution_authority": False,
        "name": "service-a",
        "occurred_at": (NOW - timedelta(minutes=10)).isoformat(),
        "status": "unavailable",
        "type": "container-app",
    }
    assert reader.calls == [
        (
            ("resource-service-a", "resource-service-b"),
            RESOURCE_EVENT_MEASURE_CONCEPTS,
            3600,
        )
    ]


async def test_event_function_distinguishes_verified_zero_from_unavailable() -> None:
    resource = _resource("service-a")
    verified_reader = _Reader(_collection(("resource-service-a",)))
    unavailable_reader = _Reader(
        _collection(
            ("resource-service-a",),
            complete=False,
            limitation="source_unavailable",
        )
    )

    verified = await _invoke(verified_reader, _query_result((resource,)))
    unavailable = await _invoke(unavailable_reader, _query_result((resource,)))

    assert verified == {"complete": True, "rows": [], "truncation_reason": None}
    assert unavailable == {
        "complete": False,
        "rows": [],
        "truncation_reason": "source_unavailable",
    }


async def test_event_function_rejects_an_unresolved_exact_target() -> None:
    reader = _Reader(_collection(("unused-resource",)))

    result = await _invoke(reader, _query_result((), exact_target="missing-resource"))

    assert result == {
        "complete": False,
        "rows": [],
        "truncation_reason": "target_resolution_not_exact",
    }
    assert reader.calls == []


async def test_event_function_does_not_read_an_incomplete_secured_scope() -> None:
    reader = _Reader(_collection(("resource-service-a",)))

    result = await _invoke(reader, _query_result((_resource("service-a"),), complete=False))

    assert result == {
        "complete": False,
        "rows": [],
        "truncation_reason": "resource_scope_incomplete",
    }
    assert reader.calls == []


async def test_event_function_rejects_provider_scope_widening() -> None:
    reader = _Reader(_collection(("resource-other",)))

    with pytest.raises(ValueError, match="changed the secured resource scope"):
        await _invoke(reader, _query_result((_resource("service-a"),)))


async def test_event_function_passes_only_immutable_secured_identity_fields() -> None:
    resource = _kubernetes_resource("pod-a")
    reader = _IdentityReader(_collection(("resource-pod-a",)))

    await _invoke(reader, _query_result((resource,)))

    assert reader.identity == {
        "resource-pod-a": {
            "cluster_ref": "cluster-example",
            "uid": "pod-uid-example",
        }
    }
