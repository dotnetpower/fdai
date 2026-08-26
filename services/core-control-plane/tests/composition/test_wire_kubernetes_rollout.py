"""Production composition coverage for issued Kubernetes rollout evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fdai.composition import build_semantic_query_runtime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform.kubernetes_rollout_evidence import (
    KubernetesRolloutEvidenceResult,
    KubernetesRolloutStatus,
)
from fdai.core.ontology_platform.kubernetes_rollout_queries import (
    KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT,
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

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
DEPLOYMENT_ID = "deployment-api-v2"
REPLICA_SET_ID = "replica-set-api-v2"
POD_ID = "pod-api-v2"


class _RolloutModel:
    def __init__(self, utterance: str) -> None:
        self._utterance = utterance
        self.plan_calls = 0

    def _span(self, text: str) -> dict[str, object]:
        start = self._utterance.index(text)
        return {"start": start, "end": start + len(text), "text": text}

    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "operation": "explain_change",
            "subject_constraints": ["Resource", DEPLOYMENT_ID],
            "measure_concepts": [KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT],
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
                        "span": self._span(DEPLOYMENT_ID),
                        "role": "affected_target",
                        "object_type_candidates": ["Resource"],
                    }
                ],
                "symptom_measures": [
                    {
                        "measure_id": "rollout",
                        "span": self._span("rollout이 멈춘"),
                        "concept_id": KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT,
                        "target_mention_id": "target",
                        "direction": "decrease",
                    }
                ],
                "primary_symptom_measure_id": "rollout",
                "temporal_cues": [{"cue_id": "onset", "span": self._span("멈춘"), "role": "onset"}],
                "relationship_intents": [
                    {
                        "relationship_id": "ownership",
                        "span": self._span("rollout이 멈춘"),
                        "source_mention_id": "target",
                        "target_mention_id": None,
                        "query_side_candidates": ["kubernetes_owned_by.incoming"],
                    }
                ],
                "hypotheses": [
                    {
                        "hypothesis_id": "controller-progress",
                        "span": self._span("원인"),
                        "relationship_id": "ownership",
                        "cause_measure_concept": KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT,
                        "effect_measure_id": "rollout",
                        "competing_explanations": ["pod-readiness"],
                    },
                    {
                        "hypothesis_id": "pod-readiness",
                        "span": self._span("원인"),
                        "relationship_id": "ownership",
                        "cause_measure_concept": KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT,
                        "effect_measure_id": "rollout",
                        "competing_explanations": ["controller-progress"],
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


def _state_fact(evidence_ref: str) -> StateFactMetadata:
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
        evidence_refs=(evidence_ref,),
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
                STATE_FACT_METADATA_PROPERTY: _state_fact(f"state:{resource_id}").to_mapping(),
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
                state_fact=_state_fact(f"ownership:{child_id}:{owner_id}"),
                verification_method="deterministic-cross-check",
                verified=True,
                verifier_identity="inventory-relationship-verifier",
                verifier_revision="verifier-1",
                verification_receipt_ref=f"verification:{child_id}:{owner_id}",
            ).to_mapping()
        },
    )


async def test_runtime_executes_issued_rollout_plan_without_model_plan() -> None:
    utterance = f"{DEPLOYMENT_ID} rollout이 멈춘 원인을 조사해줘."
    model = _RolloutModel(utterance)
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
        link_types=(ownership,),
        function_types=functions,
    )
    store = InMemoryOntologyInstanceStore(
        object_types=(resource,),
        link_types=(ownership,),
    )
    for record in (
        _resource(
            DEPLOYMENT_ID,
            "kubernetes.deployment",
            desired_replicas=3,
            updated_replicas=1,
            ready_replicas=0,
            available_replicas=0,
            unavailable_replicas=3,
            progressing_status="False",
            progressing_reason="ProgressDeadlineExceeded",
        ),
        _resource(REPLICA_SET_ID, "kubernetes.replica-set"),
        _resource(
            POD_ID,
            "kubernetes.pod",
            phase="Pending",
            ready=False,
            container_count=1,
            ready_container_count=0,
            restart_count=0,
            container_waiting_reasons=("ImagePullBackOff",),
        ),
    ):
        await store.upsert_object(record)
    for link in (
        _ownership(REPLICA_SET_ID, DEPLOYMENT_ID),
        _ownership(POD_ID, REPLICA_SET_ID),
    ):
        await store.upsert_link(link)
    runtime = build_semantic_query_runtime(
        model=model,
        ontology_release=release,
        ontology_catalog=OntologyCatalog(
            object_types=(resource,),
            interface_types=(),
            interface_implementations=(),
            link_types=(ownership,),
            action_types=(),
            function_types=(),
            property_semantics=empty_property_semantic_registry(),
        ),
        ontology_store=store,
        purpose="operations-review",
        now=lambda: NOW,
    )

    result = await runtime.handle(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="reader", role=Role.READER),
    )

    assert result.disposition == "answered", result.reason
    assert result.execution is not None
    evidence = result.execution.results["rollout-evidence"].value
    assert isinstance(evidence, KubernetesRolloutEvidenceResult)
    assert evidence.status is KubernetesRolloutStatus.STALLED
    assert evidence.complete is True
    assert evidence.cause_claim_supported is False
    assert evidence.execution_authority is False
    assert model.plan_calls == 0
