"""Competency fixtures for secured Pod telemetry path verification."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.models import (
    InterfaceImplementation,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectTraversal,
    OntologyInterfaceType,
)
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.pod_telemetry import (
    PodTelemetryPathResult,
    TelemetrySegmentStatus,
    evaluate_pod_telemetry_path,
    telemetry_link_subject,
    telemetry_object_subject,
)
from fdai.core.ontology_platform.query_gateway import (
    SecuredObjectSetQueryGateway,
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
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

_CUTOFF = datetime(2026, 8, 8, 12, tzinfo=UTC)
_CLUSTER_REF = "kubernetes.cluster:example"
_POD_ID = f"{_CLUSTER_REF}/resource/pod-uid"
_SERVICE_ID = f"{_CLUSTER_REF}/resource/service-uid"
_ENDPOINTS_ID = f"{_CLUSTER_REF}/resource/endpoints-uid"
_OBSERVATION_ID = "observation:pod-cpu:1"


def _resource(object_id: str, kind: str, name: str) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=object_id,
        object_type="Resource",
        properties={
            "id": object_id,
            "type": f"kubernetes.{kind.lower()}",
            "name": name,
            "properties": {"cluster_ref": _CLUSTER_REF, "kind": kind},
        },
    )


def _observation() -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=_OBSERVATION_ID,
        object_type="Observation",
        properties={
            "id": _OBSERVATION_ID,
            "target_ref": _POD_ID,
            "metric": "container.cpu.usage",
            "value": 0.42,
            "unit": "ratio",
            "observed_at": _CUTOFF,
            "evidence_ref": "metric-sample:pod-cpu:1",
            "source_revision": "metrics:17",
        },
    )


def _state_fact(*evidence_refs: str) -> StateFactMetadata:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.TELEMETRY,
        source_identity="telemetry-reader",
        source_revision="metrics:17",
        effective_at=_CUTOFF,
        recorded_at=_CUTOFF,
        evidence_cutoff=_CUTOFF,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=tuple(evidence_refs),
    )


def _objects(*, include_observation: bool = True) -> tuple[OntologyObjectRecord, ...]:
    resources = (
        _resource(_POD_ID, "Pod", "api-0"),
        _resource(_SERVICE_ID, "Service", "api"),
        _resource(_ENDPOINTS_ID, "Endpoints", "api"),
    )
    return (*resources, _observation()) if include_observation else resources


def _evaluate(
    secured: SecuredObjectSetQueryResult,
    evidence: dict[str, StateFactMetadata],
    *,
    expected_cluster_ref: str = _CLUSTER_REF,
) -> PodTelemetryPathResult:
    return evaluate_pod_telemetry_path(
        secured,
        pod_id=_POD_ID,
        expected_cluster_ref=expected_cluster_ref,
        cutoff=_CUTOFF,
        state_evidence=evidence,
    )


def _object_types() -> tuple[OntologyObjectType, ...]:
    return (
        OntologyObjectType(
            schema_version="1.0.0",
            name="Resource",
            version="1.0.0",
            key="id",
            properties={
                "id": PropertyDecl(type=PropertyType.STRING, required=True),
                "type": PropertyDecl(type=PropertyType.STRING, required=True),
                "name": PropertyDecl(type=PropertyType.STRING),
                "properties": PropertyDecl(type=PropertyType.OBJECT),
            },
        ),
        OntologyObjectType(
            schema_version="1.0.0",
            name="Observation",
            version="1.0.0",
            key="id",
            properties={
                "id": PropertyDecl(type=PropertyType.STRING, required=True),
                "target_ref": PropertyDecl(type=PropertyType.STRING, required=True),
                "metric": PropertyDecl(type=PropertyType.STRING, required=True),
                "value": PropertyDecl(type=PropertyType.NUMBER, required=True),
                "unit": PropertyDecl(type=PropertyType.STRING, required=True),
                "observed_at": PropertyDecl(type=PropertyType.DATETIME, required=True),
                "evidence_ref": PropertyDecl(type=PropertyType.STRING, required=True),
                "source_revision": PropertyDecl(type=PropertyType.STRING, required=True),
            },
        ),
    )


def _link_types() -> tuple[OntologyLinkType, ...]:
    return tuple(
        OntologyLinkType(
            schema_version="1.0.0",
            name=name,
            version="1.0.0",
            from_type=from_type,
            to_type="Resource",
            cardinality=cardinality,
        )
        for name, from_type, cardinality in (
            ("kubernetes_selects", "Resource", LinkCardinality.MANY_TO_MANY),
            ("kubernetes_exposes_endpoints", "Resource", LinkCardinality.ONE_TO_ONE),
            ("observation_targets_resource", "Observation", LinkCardinality.MANY_TO_ONE),
        )
    )


async def _secured_result(
    *,
    objects: tuple[OntologyObjectRecord, ...],
    links: tuple[OntologyLinkRecord, ...],
    limit: int = 32,
) -> SecuredObjectSetQueryResult:
    object_types = _object_types()
    link_types = _link_types()
    interface = OntologyInterfaceType(name="ObservableEvidence", version="1.0.0")
    implementations = tuple(
        InterfaceImplementation(
            object_type=item.name,
            interfaces=(interface.name,),
        )
        for item in object_types
    )
    store = InMemoryOntologyInstanceStore(object_types=object_types, link_types=link_types)
    for record in objects:
        await store.upsert_object(record)
    for link in links:
        await store.upsert_link(link)
    service = ObjectSetService(
        store=store,
        interfaces=compile_interfaces(
            interfaces=(interface,),
            implementations=implementations,
            object_types=object_types,
        ),
        object_type_names=frozenset(item.name for item in object_types),
    )
    gateway = SecuredObjectSetQueryGateway(
        service=service,
        object_types={item.name: item for item in object_types},
        ontology_release=build_ontology_release(
            object_types=object_types,
            link_types=link_types,
            interface_types=(interface,),
        ),
        evaluation_cutoff=lambda: _CUTOFF,
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(
            kind=ObjectSelectorKind.INTERFACE,
            name=interface.name,
        ),
        traversal=ObjectTraversal(
            link_types=tuple(item.name for item in link_types),
            direction="both",
            max_depth=3,
        ),
        root_ids=(_POD_ID,),
        as_of=_CUTOFF,
        purpose="telemetry-verification",
        limit=limit,
    )
    return await gateway.materialize(
        definition,
        projection_request=ProjectionRequest(
            caller_role=CeilingRole.READER,
            declared_purposes=frozenset({"telemetry-verification"}),
        ),
    )


async def test_complete_pod_telemetry_chain_is_fully_verified() -> None:
    links = (
        OntologyLinkRecord("kubernetes_selects", _SERVICE_ID, _POD_ID),
        OntologyLinkRecord("kubernetes_exposes_endpoints", _SERVICE_ID, _ENDPOINTS_ID),
        OntologyLinkRecord("observation_targets_resource", _OBSERVATION_ID, _POD_ID),
    )
    secured = await _secured_result(
        objects=_objects(),
        links=links,
    )
    evidence = {
        telemetry_link_subject(link): _state_fact(f"topology:{index}")
        for index, link in enumerate(links, start=1)
    }
    evidence[telemetry_object_subject(_OBSERVATION_ID)] = _state_fact("metric-sample:pod-cpu:1")

    result = _evaluate(secured, evidence)

    assert result.completeness == 1.0
    assert result.complete is True
    assert result.claimed_health is False
    assert [segment.status for segment in result.segments] == [
        TelemetrySegmentStatus.VERIFIED,
        TelemetrySegmentStatus.VERIFIED,
        TelemetrySegmentStatus.VERIFIED,
        TelemetrySegmentStatus.VERIFIED,
    ]
    assert result.evidence_refs == (
        "metric-sample:pod-cpu:1",
        "topology:1",
        "topology:2",
        "topology:3",
    )


async def test_missing_service_selector_relation_stays_missing() -> None:
    endpoint_link = OntologyLinkRecord("kubernetes_exposes_endpoints", _SERVICE_ID, _ENDPOINTS_ID)
    observation_link = OntologyLinkRecord("observation_targets_resource", _OBSERVATION_ID, _POD_ID)
    secured = await _secured_result(
        objects=_objects(),
        links=(endpoint_link, observation_link),
    )
    evidence = {
        telemetry_link_subject(observation_link): _state_fact("topology:observation"),
        telemetry_object_subject(_OBSERVATION_ID): _state_fact("metric-sample:pod-cpu:1"),
    }

    result = _evaluate(secured, evidence)

    assert result.complete is False
    assert result.completeness == 0.5
    assert result.segments[0].status is TelemetrySegmentStatus.MISSING
    assert "relationship_missing" in result.segments[0].reasons
    assert result.segments[1].status is TelemetrySegmentStatus.MISSING


async def test_stale_observation_never_claims_complete_telemetry() -> None:
    links = (
        OntologyLinkRecord("kubernetes_selects", _SERVICE_ID, _POD_ID),
        OntologyLinkRecord("kubernetes_exposes_endpoints", _SERVICE_ID, _ENDPOINTS_ID),
        OntologyLinkRecord("observation_targets_resource", _OBSERVATION_ID, _POD_ID),
    )
    secured = await _secured_result(
        objects=_objects(),
        links=links,
    )
    evidence = {
        telemetry_link_subject(link): _state_fact(f"topology:{index}")
        for index, link in enumerate(links, start=1)
    }
    stale_at = _CUTOFF - timedelta(minutes=6)
    evidence[telemetry_object_subject(_OBSERVATION_ID)] = replace(
        _state_fact("metric-sample:pod-cpu:1"),
        effective_at=stale_at,
        evidence_cutoff=stale_at,
    )

    result = _evaluate(secured, evidence)

    assert result.complete is False
    assert result.completeness == 0.75
    assert result.claimed_health is False
    assert result.segments[-1].status is TelemetrySegmentStatus.STALE


async def test_incomplete_synthetic_state_stays_unverified() -> None:
    links = (
        OntologyLinkRecord("kubernetes_selects", _SERVICE_ID, _POD_ID),
        OntologyLinkRecord("kubernetes_exposes_endpoints", _SERVICE_ID, _ENDPOINTS_ID),
        OntologyLinkRecord("observation_targets_resource", _OBSERVATION_ID, _POD_ID),
    )
    secured = await _secured_result(
        objects=_objects(),
        links=links,
    )
    evidence = {
        telemetry_link_subject(link): _state_fact(f"topology:{index}")
        for index, link in enumerate(links, start=1)
    }
    evidence[telemetry_object_subject(_OBSERVATION_ID)] = replace(
        _state_fact("metric-sample:pod-cpu:1"),
        completeness=0.5,
        synthetic=True,
    )

    result = _evaluate(secured, evidence)

    sample = result.segments[-1]
    assert sample.status is TelemetrySegmentStatus.UNVERIFIED
    assert sample.reasons == (
        "state_evidence_incomplete",
        "state_evidence_synthetic",
    )
    assert result.complete is False


async def test_wrong_cluster_identity_rejects_every_segment() -> None:
    secured = await _secured_result(
        objects=(_resource(_POD_ID, "Pod", "api-0"),),
        links=(),
    )

    result = _evaluate(secured, {}, expected_cluster_ref="kubernetes.cluster:other")

    assert result.completeness == 0.0
    assert result.complete is False
    assert all(segment.status is TelemetrySegmentStatus.MISSING for segment in result.segments)
    assert all("wrong_cluster_identity" in segment.reasons for segment in result.segments)


async def test_cross_cluster_service_and_endpoints_stay_unverified() -> None:
    other_cluster = "kubernetes.cluster:other"
    service_id = f"{other_cluster}/resource/service-uid"
    endpoints_id = f"{other_cluster}/resource/endpoints-uid"
    links = (
        OntologyLinkRecord("kubernetes_selects", service_id, _POD_ID),
        OntologyLinkRecord("kubernetes_exposes_endpoints", service_id, endpoints_id),
        OntologyLinkRecord("observation_targets_resource", _OBSERVATION_ID, _POD_ID),
    )
    secured = await _secured_result(
        objects=(
            _resource(_POD_ID, "Pod", "api-0"),
            _resource(service_id, "Service", "api"),
            _resource(endpoints_id, "Endpoints", "api"),
            _observation(),
        ),
        links=links,
    )
    evidence = {
        telemetry_link_subject(link): _state_fact(f"cross-cluster:{index}")
        for index, link in enumerate(links, start=1)
    }
    evidence[telemetry_object_subject(_OBSERVATION_ID)] = _state_fact("metric-sample:pod-cpu:1")

    result = _evaluate(secured, evidence)

    assert result.complete is False
    assert result.completeness == 0.5
    assert result.segments[0].status is TelemetrySegmentStatus.UNVERIFIED
    assert "service_wrong_cluster_identity" in result.segments[0].reasons
    assert result.segments[1].status is TelemetrySegmentStatus.UNVERIFIED
    assert "service_wrong_cluster_identity" in result.segments[1].reasons
    assert "endpoints_wrong_cluster_identity" in result.segments[1].reasons


async def test_bounded_cyclic_graph_stays_unverified() -> None:
    links = (
        OntologyLinkRecord("kubernetes_selects", _SERVICE_ID, _POD_ID),
        OntologyLinkRecord("kubernetes_selects", _POD_ID, _SERVICE_ID),
        OntologyLinkRecord("kubernetes_exposes_endpoints", _SERVICE_ID, _ENDPOINTS_ID),
        OntologyLinkRecord("observation_targets_resource", _OBSERVATION_ID, _POD_ID),
    )
    secured = await _secured_result(
        objects=_objects(),
        links=links,
        limit=2,
    )
    evidence = {
        telemetry_link_subject(link): _state_fact(f"bounded:{index}")
        for index, link in enumerate(links, start=1)
    }
    evidence[telemetry_object_subject(_OBSERVATION_ID)] = _state_fact("metric-sample:pod-cpu:1")

    result = _evaluate(secured, evidence)

    assert secured.receipt.truncated is True
    assert result.complete is False
    assert any("graph_incomplete" in segment.reasons for segment in result.segments)
    assert any(segment.status is TelemetrySegmentStatus.UNVERIFIED for segment in result.segments)


async def test_missing_observation_never_implies_health() -> None:
    links = (
        OntologyLinkRecord("kubernetes_selects", _SERVICE_ID, _POD_ID),
        OntologyLinkRecord("kubernetes_exposes_endpoints", _SERVICE_ID, _ENDPOINTS_ID),
    )
    secured = await _secured_result(
        objects=_objects(include_observation=False),
        links=links,
    )
    evidence = {
        telemetry_link_subject(link): _state_fact(f"topology:{index}")
        for index, link in enumerate(links, start=1)
    }

    result = _evaluate(secured, evidence)

    assert result.completeness == 0.5
    assert result.complete is False
    assert result.claimed_health is False
    assert [segment.status for segment in result.segments[-2:]] == [
        TelemetrySegmentStatus.MISSING,
        TelemetrySegmentStatus.MISSING,
    ]
