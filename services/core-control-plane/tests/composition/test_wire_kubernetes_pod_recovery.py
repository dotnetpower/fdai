"""Production composition coverage for issued Kubernetes Pod recovery evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fdai.composition import build_semantic_query_runtime
from fdai.core.conversation.session import Principal, Role
from fdai.core.detection.series import MetricSample
from fdai.core.ontology_platform.kubernetes_pod_recovery_evidence import (
    KubernetesPodRecoveryEvidenceResult,
    KubernetesPodRecoveryStatus,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_queries import (
    KUBERNETES_POD_RESTART_HISTORY_CONCEPT,
    KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT,
)
from fdai.core.ontology_platform.metric_semantics import (
    MetricAggregation,
    MetricSemanticDefinition,
    MetricSemanticRegistry,
    MetricWindow,
)
from fdai.core.ontology_platform.operational_functions import operational_function_types
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
from tests.decision_evidence import StubDecisionEvidenceAdmissionProvider

NOW = datetime(2026, 8, 25, 18, tzinfo=UTC)
POD_ID = "order-api-0"
REPLICA_SET_ID = "order-api-rs"
DEPLOYMENT_ID = "order-api"


class _PodRecoveryModel:
    def __init__(self, utterance: str) -> None:
        self._utterance = utterance
        self.plan_calls = 0

    def _span(self, text: str) -> dict[str, object]:
        start = self._utterance.index(text)
        return {"start": start, "end": start + len(text), "text": text}

    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "operation": "explain_change",
            "subject_constraints": ["Resource", POD_ID],
            "measure_concepts": [KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT],
            "temporal_scope": {},
            "output_shape": "causal_evidence",
            "evidence_requirements": ["authoritative_inventory"],
            "unresolved_terms": [],
            "clarification_requirements": [],
            "clarification": None,
            "investigation": {
                "operation": "explain_change",
                "entities": [
                    {
                        "mention_id": "target",
                        "span": self._span(POD_ID),
                        "role": "affected_target",
                        "object_type_candidates": ["Resource"],
                    }
                ],
                "symptom_measures": [
                    {
                        "measure_id": "restart",
                        "span": self._span("재시작된"),
                        "concept_id": KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT,
                        "target_mention_id": "target",
                        "direction": "increase",
                    }
                ],
                "primary_symptom_measure_id": "restart",
                "temporal_cues": [
                    {"cue_id": "onset", "span": self._span("갑자기"), "role": "onset"}
                ],
                "relationship_intents": [
                    {
                        "relationship_id": "impact",
                        "span": self._span("원인"),
                        "source_mention_id": "target",
                        "target_mention_id": None,
                        "query_side_candidates": ["depends_on.outgoing"],
                    }
                ],
                "hypotheses": [
                    {
                        "hypothesis_id": "resource-pressure",
                        "span": self._span("원인"),
                        "relationship_id": "impact",
                        "cause_measure_concept": KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT,
                        "effect_measure_id": "restart",
                        "competing_explanations": ["workload-change"],
                    },
                    {
                        "hypothesis_id": "workload-change",
                        "span": self._span("원인"),
                        "relationship_id": "impact",
                        "cause_measure_concept": KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT,
                        "effect_measure_id": "restart",
                        "competing_explanations": ["resource-pressure"],
                    },
                ],
                "evidence_standard": "support_and_refutation",
                "answer_shape": "diagnosis",
                "confidence": 0.9,
            },
            "confidence": 0.9,
        }

    def propose_plan(self, **_kwargs: Any) -> None:
        self.plan_calls += 1
        return None


class _RestartMetricProvider:
    async def read(  # type: ignore[no-untyped-def]
        self, *, definition, resource_id, start, end, query_labels=None
    ):
        assert definition.concept_id == KUBERNETES_POD_RESTART_HISTORY_CONCEPT
        assert resource_id == POD_ID
        assert query_labels == {"resource_id": "cluster-a", "pod_uid": "pod-uid-a"}
        return MetricWindow(
            concept_id=definition.concept_id,
            resource_id=resource_id,
            unit=definition.canonical_unit,
            start=start,
            end=end,
            samples=(MetricSample(timestamp=end, value=1.0),),
            complete=True,
            evidence_refs=("metric:pod-restart:order-api-0",),
        )


def _metric_registry() -> MetricSemanticRegistry:
    return MetricSemanticRegistry.build(
        (
            MetricSemanticDefinition(
                concept_id=KUBERNETES_POD_RESTART_HISTORY_CONCEPT,
                provider_metric="k8s.pod.restarts",
                canonical_unit="count",
                aggregation=MetricAggregation.SUM,
                description="Restart-count increase for one immutable Kubernetes Pod UID.",
                monotonic=True,
                scope_label_selectors={
                    "resource_id": ("properties", "properties", "cluster_ref"),
                    "pod_uid": ("properties", "properties", "uid"),
                },
            ),
        )
    )


def _state_fact() -> StateFactMetadata:
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="kubernetes-api-inventory",
        source_revision="generation-1",
        effective_at=NOW,
        recorded_at=NOW,
        evidence_cutoff=NOW,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=("kubernetes:pod:order-api-0",),
    )


def _resource(resource_id: str, resource_type: str, **properties: object) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=resource_id,
        object_type="Resource",
        properties={
            "id": resource_id,
            "type": resource_type,
            "properties": {
                **properties,
                STATE_FACT_METADATA_PROPERTY: _state_fact().to_mapping(),
            },
        },
    )


def _ownership(child_id: str, owner_id: str) -> OntologyLinkRecord:
    return OntologyLinkRecord(
        link_type="kubernetes_owned_by",
        from_id=child_id,
        to_id=owner_id,
        properties={
            LINK_OBSERVATION_METADATA_PROPERTY: LinkObservationMetadata(
                state_fact=_state_fact(),
                verification_method="deterministic-cross-check",
                verified=True,
                verifier_identity="inventory-relationship-verifier",
                verifier_revision="verifier-1",
                verification_receipt_ref=f"verification:{child_id}:{owner_id}",
            ).to_mapping()
        },
    )


async def test_runtime_executes_issued_pod_recovery_plan_without_model_plan() -> None:
    utterance = f"{POD_ID} Pod가 갑자기 재시작된 원인과 현재 회복 여부를 조사해줘."
    model = _PodRecoveryModel(utterance)
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "type": PropertyDecl(type=PropertyType.STRING, required=True),
            "properties": PropertyDecl(type=PropertyType.OBJECT),
        },
    )
    dependency = OntologyLinkType(
        schema_version="1.0.0",
        name="depends_on",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    ownership = OntologyLinkType(
        schema_version="1.0.0",
        name="kubernetes_owned_by",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    functions = operational_function_types(())
    release = build_ontology_release(
        object_types=(resource,),
        link_types=(dependency, ownership),
        function_types=functions,
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(resource,),
        link_types=(dependency, ownership),
    )
    for record in (
        _resource(
            POD_ID,
            "kubernetes.pod",
            cluster_ref="cluster-a",
            uid="pod-uid-a",
            phase="Running",
            ready=True,
            container_count=1,
            ready_container_count=1,
            restart_count=2,
        ),
        _resource(REPLICA_SET_ID, "kubernetes.replica-set"),
        _resource(
            DEPLOYMENT_ID,
            "kubernetes.deployment",
            desired_replicas=1,
            ready_replicas=1,
            available_replicas=1,
            unavailable_replicas=0,
        ),
    ):
        await store.upsert_object(record)
    for link in (
        _ownership(POD_ID, REPLICA_SET_ID),
        _ownership(REPLICA_SET_ID, DEPLOYMENT_ID),
    ):
        await store.upsert_link(link)
    runtime = build_semantic_query_runtime(
        model=model,
        ontology_release=release,
        ontology_catalog=OntologyCatalog(
            object_types=(resource,),
            interface_types=(),
            interface_implementations=(),
            link_types=(dependency, ownership),
            action_types=(),
            function_types=(),
            property_semantics=empty_property_semantic_registry(),
        ),
        ontology_store=store,
        metric_registry=_metric_registry(),
        metric_window_provider=_RestartMetricProvider(),
        purpose="operations-review",
        decision_evidence_admission_provider=StubDecisionEvidenceAdmissionProvider(lambda: NOW),
        now=lambda: NOW,
    )

    result = await runtime.handle(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "answered", result.reason
    assert result.execution is not None
    evidence = result.execution.results["pod-recovery-evidence"].value
    assert isinstance(evidence, KubernetesPodRecoveryEvidenceResult)
    assert evidence.status is KubernetesPodRecoveryStatus.RECOVERED
    assert evidence.recovery_verified is True
    assert evidence.restart_history_complete is True
    assert evidence.restart_observed_in_window is True
    assert evidence.restart_delta == 1
    assert evidence.owner_deployment_id == DEPLOYMENT_ID
    assert evidence.deployment_recovery_verified is True
    assert evidence.cause_claim_supported is False
    assert evidence.execution_authority is False
    assert model.plan_calls == 0
