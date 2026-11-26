"""Exact-target semantic planning for Kubernetes rollout evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentBoundary,
)
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import SemanticPlanningDisposition
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanVerifier,
    build_query_manifest,
)
from fdai.core.ontology_platform.kubernetes_rollout_queries import (
    KUBERNETES_ROLLOUT_FUNCTION_NAME,
    KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT,
    kubernetes_rollout_function_type,
)
from fdai.core.ontology_platform.property_values import PropertyValueDomain, PropertyValueGroup
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
from fdai_service_contracts.semantic_judgment import SemanticJudgmentTier

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)


class _ManifestProvider:
    def __init__(self, manifest: Any) -> None:
        self._manifest = manifest

    def manifest_for(self, *, principal: Principal, purpose: str):  # type: ignore[no-untyped-def]
        assert principal.role is Role.READER
        assert purpose == "operations-review"
        return self._manifest


class _Model:
    def __init__(self, *, frame: dict[str, object], plan: dict[str, object] | None) -> None:
        self._frame = frame
        self._plan = plan
        self.frame_calls = 0
        self.plan_calls = 0

    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        self.frame_calls += 1
        return self._frame

    def propose_plan(self, **_kwargs: Any) -> dict[str, object] | None:
        self.plan_calls += 1
        return self._plan


class _RolloutJudgmentModel:
    def __init__(self, primary_intent: str) -> None:
        self._primary_intent = primary_intent

    def judge(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "primary_intent": self._primary_intent,
            "targets": [],
            "requested_facets": ["cause", "safest_recovery_plan"],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "execution_authority": False,
        }


def _manifest() -> tuple[Any, ObjectSetDefinition]:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "type": PropertyDecl(type=PropertyType.STRING, required=True),
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
    function = kubernetes_rollout_function_type()
    release = build_ontology_release(
        object_types=(resource,),
        link_types=(ownership,),
        function_types=(function,),
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
        link_types=(ownership,),
        functions=(function,),
        bound_function_names=(function.name,),
        property_values=(
            PropertyValueDomain(
                object_type="Resource",
                property_name="type",
                values=("kubernetes.deployment",),
                groups=(
                    PropertyValueGroup(
                        id="kubernetes.deployment",
                        values=("kubernetes.deployment",),
                        terms=("rollout", "rollouts", "롤아웃", "쿠버네티스 배포"),
                    ),
                ),
            ),
        ),
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(ObjectPredicate(property="id", equals="resource-a"),),
        as_of=NOW,
        purpose="operations-review",
        limit=2,
    )
    return manifest, definition


def _frame(utterance: str) -> dict[str, object]:
    def span(text: str) -> dict[str, object]:
        start = utterance.index(text)
        return {"start": start, "end": start + len(text), "text": text}

    return {
        "operation": "explain_change",
        "subject_constraints": ["Resource", "deployment-api-v2"],
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
                    "span": span("deployment-api-v2"),
                    "role": "affected_target",
                    "object_type_candidates": ["Resource"],
                }
            ],
            "symptom_measures": [
                {
                    "measure_id": "rollout",
                    "span": span("rollout이 멈춘"),
                    "concept_id": KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT,
                    "target_mention_id": "target",
                    "direction": "decrease",
                }
            ],
            "primary_symptom_measure_id": "rollout",
            "temporal_cues": [{"cue_id": "onset", "span": span("멈춘"), "role": "onset"}],
            "relationship_intents": [
                {
                    "relationship_id": "ownership",
                    "span": span("rollout이 멈춘"),
                    "source_mention_id": "target",
                    "target_mention_id": None,
                    "query_side_candidates": ["kubernetes_owned_by.incoming"],
                }
            ],
            "hypotheses": [
                {
                    "hypothesis_id": "deployment-change",
                    "span": span("원인"),
                    "relationship_id": "ownership",
                    "cause_measure_concept": "deployment.change",
                    "effect_measure_id": "rollout",
                    "competing_explanations": ["resource-saturation"],
                },
                {
                    "hypothesis_id": "resource-saturation",
                    "span": span("원인"),
                    "relationship_id": "ownership",
                    "cause_measure_concept": "resource.saturation",
                    "effect_measure_id": "rollout",
                    "competing_explanations": ["deployment-change"],
                },
            ],
            "evidence_standard": "support_and_refutation",
            "answer_shape": "diagnosis",
            "confidence": 0.9,
        },
        "confidence": 0.9,
    }


def test_exact_target_rollout_investigation_uses_server_owned_plan() -> None:
    utterance = "deployment-api-v2 rollout이 멈춘 원인을 조사해줘."
    manifest, fallback_definition = _manifest()
    t1 = _Model(frame=_frame(utterance), plan=None)
    t2 = _Model(
        frame={
            "operation": "select",
            "subject_constraints": ["Resource"],
            "measure_concepts": [],
            "temporal_scope": {},
            "output_shape": "resource_list",
            "evidence_requirements": ["authoritative_inventory"],
            "unresolved_terms": [],
            "clarification_requirements": [],
            "clarification": None,
            "investigation": None,
            "confidence": 0.9,
        },
        plan={
            "nodes": [
                {
                    "node_id": "resources",
                    "kind": "object_set",
                    "depends_on": [],
                    "arguments": {"definition": fallback_definition.model_dump(mode="json")},
                    "output_kind": "query.table",
                }
            ],
            "output_node_ids": ["resources"],
        },
    )
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(
                QueryNodeKind.OBJECT_SET,
                QueryNodeKind.RELATIONSHIP_TRAVERSAL,
                QueryNodeKind.FUNCTION,
            )
        ),
        metric_concepts=(
            "deployment.change",
            KUBERNETES_ROLLOUT_SYMPTOM_CONCEPT,
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

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.nodes[-1].arguments["function_name"] == KUBERNETES_ROLLOUT_FUNCTION_NAME
    assert (t1.plan_calls, t2.frame_calls, t2.plan_calls) == (0, 0, 0)
    assert outcome.execution_authority is False


@pytest.mark.parametrize(
    "primary_intent",
    (
        "query.kubernetes_rollout_evidence",
        "tool.run-investigation",
        "tool.run_investigation",
    ),
)
def test_typed_investigation_judgment_selects_rollout_candidates_before_frame_model(
    primary_intent: str,
) -> None:
    manifest, _fallback_definition = _manifest()
    model = _Model(frame={}, plan=None)
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_RolloutJudgmentModel(primary_intent),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        semantic_judgment=judgment,
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="배포 이후 rollout이 멈춘 원인과 가장 안전한 복구안을 제시해줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_target_candidates"
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {
            "property": "type",
            "operator": "equals",
            "equals": "kubernetes.deployment",
        }
    ]
    assert (model.frame_calls, model.plan_calls) == (0, 0)
    assert outcome.execution_authority is False
