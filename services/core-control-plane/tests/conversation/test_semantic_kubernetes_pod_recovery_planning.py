"""Exact-target semantic planning for Kubernetes Pod recovery evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import SemanticPlanningDisposition
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import OntologyQueryPlanVerifier, build_query_manifest
from fdai.core.ontology_platform.kubernetes_pod_lifecycle_cohort_queries import (
    KUBERNETES_POD_LIFECYCLE_COHORT_FUNCTION_NAME,
    kubernetes_pod_lifecycle_cohort_function_type,
)
from fdai.core.ontology_platform.kubernetes_pod_recovery_queries import (
    KUBERNETES_POD_RECOVERY_FUNCTION_NAME,
    KUBERNETES_POD_RESTART_HISTORY_CONCEPT,
    KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT,
    kubernetes_pod_recovery_function_type,
)
from fdai.core.ontology_platform.query_metric_handlers import METRIC_ARGUMENT_SCHEMAS
from fdai.shared.contracts.models import (
    CeilingRole,
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import QueryNodeKind

NOW = datetime(2026, 8, 25, 17, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)


class _ManifestProvider:
    def __init__(self, manifest: Any) -> None:
        self._manifest = manifest

    def manifest_for(self, *, principal: Principal, purpose: str):  # type: ignore[no-untyped-def]
        assert principal.role is Role.READER
        assert purpose == "operations-review"
        return self._manifest


class _Model:
    def __init__(self, frame: dict[str, object]) -> None:
        self._frame = frame
        self.plan_calls = 0

    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        return self._frame

    def propose_plan(self, **_kwargs: Any) -> None:
        self.plan_calls += 1
        return None


def _manifest():  # type: ignore[no-untyped-def]
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "name": PropertyDecl(type=PropertyType.STRING),
            "type": PropertyDecl(type=PropertyType.STRING, required=True),
        },
    )
    function = kubernetes_pod_recovery_function_type()
    cohort_function = kubernetes_pod_lifecycle_cohort_function_type()
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
    release = build_ontology_release(
        object_types=(resource,),
        link_types=(dependency, ownership),
        function_types=(function, cohort_function),
    )
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
        link_types=(dependency, ownership),
        functions=(function, cohort_function),
        bound_function_names=(function.name, cohort_function.name),
    )


def _frame(utterance: str) -> dict[str, object]:
    def span(text: str) -> dict[str, object]:
        start = utterance.index(text)
        return {"start": start, "end": start + len(text), "text": text}

    return {
        "operation": "explain_change",
        "subject_constraints": ["Resource", "order-api-0"],
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
                    "span": span("order-api-0"),
                    "role": "affected_target",
                    "object_type_candidates": ["Resource"],
                }
            ],
            "symptom_measures": [
                {
                    "measure_id": "restart",
                    "span": span("재시작된"),
                    "concept_id": KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT,
                    "target_mention_id": "target",
                    "direction": "increase",
                }
            ],
            "primary_symptom_measure_id": "restart",
            "temporal_cues": [{"cue_id": "onset", "span": span("갑자기"), "role": "onset"}],
            "relationship_intents": [
                {
                    "relationship_id": "impact",
                    "span": span("원인"),
                    "source_mention_id": "target",
                    "target_mention_id": None,
                    "query_side_candidates": ["depends_on.outgoing"],
                }
            ],
            "hypotheses": [
                {
                    "hypothesis_id": "resource-pressure",
                    "span": span("원인"),
                    "relationship_id": "impact",
                    "cause_measure_concept": "resource.saturation",
                    "effect_measure_id": "restart",
                    "competing_explanations": ["workload-change"],
                },
                {
                    "hypothesis_id": "workload-change",
                    "span": span("원인"),
                    "relationship_id": "impact",
                    "cause_measure_concept": "deployment.change",
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


def test_exact_pod_restart_investigation_uses_server_owned_plan() -> None:
    utterance = "order-api-0 Pod가 갑자기 재시작된 원인과 현재 회복 여부를 조사해줘."
    model = _Model(_frame(utterance))
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(
            QueryNodeKind.OBJECT_SET,
            QueryNodeKind.METRIC_SCOPE_SERIES,
            QueryNodeKind.RELATIONSHIP_TRAVERSAL,
            QueryNodeKind.FUNCTION,
        ),
        extension_argument_schemas={
            QueryNodeKind.METRIC_SCOPE_SERIES: METRIC_ARGUMENT_SCHEMAS[
                QueryNodeKind.METRIC_SCOPE_SERIES
            ]
        },
        reviewed_metric_concepts=(KUBERNETES_POD_RESTART_HISTORY_CONCEPT,),
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(_manifest()),
        verifier=verifier,
        metric_concepts=(
            "deployment.change",
            KUBERNETES_POD_RESTART_SYMPTOM_CONCEPT,
            KUBERNETES_POD_RESTART_HISTORY_CONCEPT,
            "resource.saturation",
        ),
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED, outcome.reason
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.nodes[-1].arguments["function_name"] == (
        KUBERNETES_POD_RECOVERY_FUNCTION_NAME
    )
    assert (
        outcome.plan.nodes[-2].arguments["function_name"]
        == KUBERNETES_POD_LIFECYCLE_COHORT_FUNCTION_NAME
    )
    assert "pod-lifecycle-events" in outcome.plan.nodes[-1].depends_on
    assert "pod-replacement-candidates" in outcome.plan.nodes[-1].depends_on
    assert model.plan_calls == 0
    assert outcome.execution_authority is False
