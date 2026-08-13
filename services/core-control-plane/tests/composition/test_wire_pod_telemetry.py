"""Production composition coverage for the issued Pod telemetry function."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fdai.composition import build_semantic_query_runtime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectTraversal,
)
from fdai.core.ontology_platform.models import (
    InterfaceImplementation,
    OntologyInterfaceType,
)
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.pod_telemetry import (
    PodTelemetryPathResult,
    TelemetrySegmentStatus,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)
CLUSTER_REF = "kubernetes.cluster:example"
POD_ID = f"{CLUSTER_REF}/resource/pod-api-0"
SERVICE_ID = f"{CLUSTER_REF}/resource/service-api"
ENDPOINTS_ID = f"{CLUSTER_REF}/resource/endpoints-api"
OBSERVATION_ID = "observation:pod-cpu:1"


class _PodTelemetryModel:
    def __init__(self, definition: ObjectSetDefinition) -> None:
        self._definition = definition

    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "operation": "select",
            "subject_constraints": ["Resource"],
            "measure_concepts": ["container.cpu.usage"],
            "temporal_scope": {},
            "output_shape": "resource_list",
            "evidence_requirements": ["authoritative_ontology"],
            "unresolved_terms": [],
            "clarification": None,
            "confidence": 0.9,
        }

    def propose_plan(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "node_id": "pod-graph",
                    "kind": "object_set",
                    "depends_on": [],
                    "arguments": {"definition": self._definition.model_dump(mode="json")},
                    "output_kind": "query.table",
                },
                {
                    "node_id": "pod-path",
                    "kind": "function",
                    "depends_on": ["pod-graph"],
                    "arguments": {
                        "function_name": "query.pod_telemetry_path",
                        "arguments": {
                            "pod_id": POD_ID,
                            "expected_cluster_ref": CLUSTER_REF,
                        },
                        "dependency_arguments": {"pod-graph": "query_result"},
                    },
                    "output_kind": "pod.telemetry.path",
                },
            ],
            "output_node_ids": ["pod-path"],
        }


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
                STATE_FACT_METADATA_PROPERTY: PropertyDecl(type=PropertyType.OBJECT),
            },
        ),
    )


def _link_types() -> tuple[OntologyLinkType, ...]:
    return (
        OntologyLinkType(
            schema_version="1.0.0",
            name="kubernetes_selects",
            version="1.0.0",
            from_type="Resource",
            to_type="Resource",
            cardinality=LinkCardinality.MANY_TO_MANY,
        ),
        OntologyLinkType(
            schema_version="1.0.0",
            name="kubernetes_exposes_endpoints",
            version="1.0.0",
            from_type="Resource",
            to_type="Resource",
            cardinality=LinkCardinality.ONE_TO_ONE,
        ),
        OntologyLinkType(
            schema_version="1.0.0",
            name="observation_targets_resource",
            version="1.0.0",
            from_type="Observation",
            to_type="Resource",
            cardinality=LinkCardinality.MANY_TO_ONE,
        ),
    )


def _state_fact(*evidence_refs: str, synthetic: bool = False) -> StateFactMetadata:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.TELEMETRY,
        source_identity="telemetry-reader",
        source_revision="telemetry:1",
        effective_at=NOW,
        recorded_at=NOW,
        evidence_cutoff=NOW,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=synthetic,
        evidence_refs=evidence_refs,
    )


def _resource(resource_id: str, kind: str) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=resource_id,
        object_type="Resource",
        properties={
            "id": resource_id,
            "type": f"kubernetes.{kind.casefold()}",
            "properties": {"cluster_ref": CLUSTER_REF, "kind": kind},
        },
    )


async def _runtime(*, synthetic_sample: bool):
    object_types = _object_types()
    link_types = _link_types()
    functions = operational_function_types(())
    interface = OntologyInterfaceType(name="ObservableEvidence", version="1.0.0")
    implementations = tuple(
        InterfaceImplementation(object_type=item.name, interfaces=(interface.name,))
        for item in object_types
    )
    release = build_ontology_release(
        object_types=object_types,
        link_types=link_types,
        interface_types=(interface,),
        function_types=functions,
    )
    store = InMemoryOntologyInstanceStore(object_types=object_types, link_types=link_types)
    for record in (
        _resource(POD_ID, "Pod"),
        _resource(SERVICE_ID, "Service"),
        _resource(ENDPOINTS_ID, "Endpoints"),
        OntologyObjectRecord(
            id=OBSERVATION_ID,
            object_type="Observation",
            properties={
                "id": OBSERVATION_ID,
                "target_ref": POD_ID,
                "metric": "container.cpu.usage",
                "value": 0.42,
                "unit": "ratio",
                "observed_at": NOW,
                "evidence_ref": "metric-sample:pod-cpu:1",
                "source_revision": "telemetry:1",
                STATE_FACT_METADATA_PROPERTY: _state_fact(
                    "metric-sample:pod-cpu:1",
                    synthetic=synthetic_sample,
                ).to_mapping(),
            },
        ),
    ):
        await store.upsert_object(record)
    for index, link in enumerate(
        (
            OntologyLinkRecord("kubernetes_selects", SERVICE_ID, POD_ID),
            OntologyLinkRecord("kubernetes_exposes_endpoints", SERVICE_ID, ENDPOINTS_ID),
            OntologyLinkRecord("observation_targets_resource", OBSERVATION_ID, POD_ID),
        ),
        start=1,
    ):
        await store.upsert_link(
            OntologyLinkRecord(
                link.link_type,
                link.from_id,
                link.to_id,
                properties={
                    LINK_OBSERVATION_METADATA_PROPERTY: LinkObservationMetadata(
                        state_fact=_state_fact(f"topology:{index}"),
                        verification_method="independent-source",
                        verified=True,
                        verifier_identity="topology-verifier",
                        verifier_revision="verifier:1",
                        verification_receipt_ref=f"topology-verification:{index}",
                    ).to_mapping()
                },
            )
        )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.INTERFACE, name=interface.name),
        traversal=ObjectTraversal(
            link_types=tuple(item.name for item in link_types),
            direction="both",
            max_depth=3,
        ),
        root_ids=(POD_ID,),
        as_of=NOW,
        purpose="telemetry-verification",
        limit=16,
    )
    return build_semantic_query_runtime(
        model=_PodTelemetryModel(definition),
        ontology_release=release,
        ontology_catalog=OntologyCatalog(
            object_types=object_types,
            interface_types=(interface,),
            interface_implementations=implementations,
            link_types=link_types,
            action_types=(),
            function_types=(),
            property_semantics=empty_property_semantic_registry(),
        ),
        ontology_store=store,
        purpose="telemetry-verification",
        now=lambda: NOW,
    )


async def _execute(*, synthetic_sample: bool) -> PodTelemetryPathResult:
    runtime = await _runtime(synthetic_sample=synthetic_sample)
    result = await runtime.handle(
        utterance="Verify the Pod telemetry path.",
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "answered", result.reason
    assert result.execution is not None
    path = result.execution.results["pod-path"].value
    assert isinstance(path, PodTelemetryPathResult)
    assert path.execution_authority is False
    assert path.claimed_health is False
    return path


async def test_runtime_composition_returns_fully_verified_pod_telemetry_path() -> None:
    path = await _execute(synthetic_sample=False)

    assert path.complete is True
    assert [segment.status for segment in path.segments] == [
        TelemetrySegmentStatus.VERIFIED,
        TelemetrySegmentStatus.VERIFIED,
        TelemetrySegmentStatus.VERIFIED,
        TelemetrySegmentStatus.VERIFIED,
    ]


async def test_runtime_composition_keeps_synthetic_sample_unverified() -> None:
    path = await _execute(synthetic_sample=True)

    assert path.complete is False
    assert path.completeness == 0.75
    assert path.segments[-1].status is TelemetrySegmentStatus.UNVERIFIED
    assert path.segments[-1].reasons == ("state_evidence_synthetic",)
