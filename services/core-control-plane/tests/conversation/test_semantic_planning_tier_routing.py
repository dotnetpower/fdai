"""T1-first semantic planning and bounded T2 escalation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from fdai.composition.semantic_query_model_targets import t1_model_targets, t2_model_targets
from fdai.core.conversation.conversation_preflight import (
    ConversationPreflightBinding,
    ConversationPreflightBoundary,
    SocialResponseNarratorBinding,
)
from fdai.core.conversation.semantic_activity_planning import normalize_activity_proposal
from fdai.core.conversation.semantic_judgment import (
    SemanticJudgmentBinding,
    SemanticJudgmentBoundary,
    SemanticJudgmentModelResponse,
    SemanticJudgmentObservation,
)
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_cascade import (
    _judgment_link_subjects,
    _judgment_object_subjects,
    _validate_frame_proposal,
)
from fdai.core.conversation.semantic_planning_frame import (
    build_bound_incident_metric_comparison_frame,
    build_business_capability_mapping_frame,
    build_configuration_drift_clarification,
    build_historical_topology_clarification,
    build_network_path_clarification,
    build_ontology_release_health_frame,
    build_ontology_trace_frame,
    build_operating_objectives_frame,
    build_private_connectivity_clarification,
    build_recovery_plan_clarification,
    build_resource_activity_clarification,
    build_resource_classification_frame,
    build_resource_current_state_clarification,
    build_resource_event_history_clarification,
    build_resource_relationship_clarification,
    build_rule_state_frame,
    build_semantic_frame,
    build_service_agent_ownership_frame,
    build_service_current_health_clarification,
    build_unbound_change_correlation_frame,
    is_completed_change_outcome_frame,
    is_configuration_drift_evidence_frame,
    is_historical_topology_clarification_frame,
    is_incident_triage_frame,
    is_network_path_clarification_frame,
    is_ontology_trace_frame,
    is_resource_classification_frame,
    normalize_historical_topology_clarification,
    normalize_network_path_clarification,
    normalize_ontology_trace_frame,
    normalize_operating_objectives_frame,
    normalize_resource_classification_frame,
    resolve_semantic_judgment_action_draft,
    resolve_semantic_judgment_bound_read,
)
from fdai.core.conversation.semantic_planning_frame_checks import (
    deterministic_pre_frame_outcome,
)
from fdai.core.conversation.semantic_planning_models import (
    BoundIncident,
    ClarificationRequirement,
    SemanticDirectResponseIntent,
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningDisposition,
)
from fdai.core.conversation.semantic_runtime import (
    SemanticConversationRuntime,
    _current_relationship_mapping_unavailable,
    _query_output_incomplete,
)
from fdai.core.conversation.semantic_target_candidate_planning import (
    build_non_resource_target_clarification,
    normalize_decision_outcome_relationship,
    normalize_operating_relationship_temporal_scope,
    resource_target_candidates_apply_to_proposal,
)
from fdai.core.conversation.session import Principal, Role, Turn
from fdai.core.ontology_platform import (
    METRIC_ARGUMENT_SCHEMAS,
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanExecutor,
    OntologyQueryPlanVerifier,
    QueryNodeResult,
    QueryPlanExecution,
    build_query_manifest,
)
from fdai.core.ontology_platform.declaration_queries import (
    ontology_declaration_function_type,
)
from fdai.core.ontology_platform.evidence_health_queries import (
    ontology_evidence_health_function_type,
)
from fdai.core.ontology_platform.incident_queries import (
    INCIDENT_EVIDENCE_MAX_RECORDS,
    incident_evidence_function_type,
)
from fdai.core.ontology_platform.inventory_impact_queries import inventory_impact_function_type
from fdai.core.ontology_platform.manifest_queries import ontology_manifest_function_type
from fdai.core.ontology_platform.property_values import PropertyValueDomain, PropertyValueGroup
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.core.ontology_platform.relationship_queries import (
    ontology_relationships_function_type,
)
from fdai.core.ontology_platform.release_diff_queries import ontology_release_diff_function_type
from fdai.core.ontology_platform.resource_activity_queries import (
    RESOURCE_ACTIVITY_FUNCTION_NAME,
    resource_activity_function_type,
)
from fdai.core.ontology_platform.resource_current_state_queries import (
    RESOURCE_CURRENT_STATE_FUNCTION_NAME,
    resource_current_state_function_type,
)
from fdai.core.ontology_platform.resource_error_activity_correlation_queries import (
    ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME,
    error_activity_correlation_function_type,
)
from fdai.core.ontology_platform.resource_health_assessment_queries import (
    target_health_assessment_function_type,
)
from fdai.core.ontology_platform.resource_ingress_queries import (
    RESOURCE_INGRESS_FUNCTION_NAME,
    resource_ingress_function_type,
)
from fdai.core.ontology_platform.resource_metric_queries import (
    RESOURCE_METRIC_FUNCTION_NAME,
    RESOURCE_METRIC_SERIES_FUNCTION_NAME,
    resource_metric_function_type,
    resource_metric_series_function_type,
)
from fdai.delivery.golden_question_dataset import load_golden_question_dataset
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    QueryTerms,
)
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    NarratorCandidate,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.models import (
    CeilingRole,
    LinkCardinality,
    OntologyFunctionType,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import QueryNodeKind, SemanticOperation
from fdai_service_contracts.semantic_judgment import (
    SemanticJudgmentProposal,
    SemanticJudgmentTier,
)

NOW = datetime(2026, 8, 14, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[4]
DIGEST = "sha256:" + ("a" * 64)
_NAMED_INSTANCE_UTTERANCE = "aks-fdai-observe-lab 클러스터 상태 요약해줘"


class _ManifestProvider:
    def __init__(self, manifest: Any) -> None:
        self._manifest = manifest
        self.calls = 0

    def manifest_for(self, *, principal: Principal, purpose: str):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self._manifest


class _Model:
    def __init__(self, *, frame: object, plan: object) -> None:
        self.frame = frame
        self.plan = plan
        self.frame_calls = 0
        self.plan_calls = 0
        self.plan_evaluation_times: list[datetime] = []

    def propose_frame(self, **_kwargs: Any) -> Any:
        self.frame_calls += 1
        return self.frame

    def propose_plan(self, **kwargs: Any) -> Any:
        self.plan_calls += 1
        self.plan_evaluation_times.append(kwargs["evaluation_time"])
        return self.plan


class _DraftJudgmentModel:
    def judge(self, *, utterance: str, **_kwargs: Any) -> dict[str, object]:
        return {
            "primary_intent": "action_request",
            "targets": [
                {
                    "kind": "action_type",
                    "value": "Draft",
                    "canonical_value": "ops.restart-service",
                    "source_start": 0,
                    "source_end": 5,
                }
            ],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "draft_only",
            "action_subject": "Change",
            "execution_authority": False,
        }


class _GreetingJudgmentModel:
    def __init__(
        self,
        primary_intent: str = "greeting",
        *,
        requested_facets: tuple[str, ...] = (),
        answer: str = "A model-authored response for this exact turn.",
    ) -> None:
        self._primary_intent = primary_intent
        self._requested_facets = requested_facets
        self._answer = answer
        self.calls = 0

    def judge(self, **kwargs: Any) -> dict[str, object]:
        self.calls += 1
        result: dict[str, object] = {
            "primary_intent": self._primary_intent,
            "targets": [],
            "requested_facets": self._requested_facets,
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "execution_authority": False,
        }
        if self._primary_intent in {"greeting", "self_introduction"}:
            answer = (
                "안녕하세요. 무엇을 도와드릴까요?"
                if kwargs["locale"] == "ko"
                and self._answer == "A model-authored response for this exact turn."
                else self._answer
            )
            result["direct_response"] = {
                "locale": kwargs["locale"],
                "answer": answer,
                "profile_digest": kwargs["direct_response_profile_digest"],
                "execution_authority": False,
            }
        return result


class _PreflightModel:
    def __init__(
        self,
        *,
        social_act: str,
        operational_signal: str,
        context_dependency: str = "none",
        answer: str | None = None,
        continued_answer: str | None = None,
        confidence: float = 0.97,
    ) -> None:
        self.social_act = social_act
        self.operational_signal = operational_signal
        self.context_dependency = context_dependency
        self.answer = answer
        self.continued_answer = continued_answer
        self.confidence = confidence
        self.calls = 0

    def preflight(self, **_kwargs: Any) -> dict[str, object]:
        self.calls += 1
        return {
            "social_act": self.social_act,
            "operational_signal": self.operational_signal,
            "context_dependency": self.context_dependency,
            "confidence": self.confidence,
            "execution_authority": False,
        }

    def narrate_social(self, **kwargs: Any) -> dict[str, object] | None:
        if self.answer is None:
            return None
        return {
            "locale": kwargs["locale"],
            "answer": (
                self.continued_answer
                if kwargs["continued"] and self.continued_answer is not None
                else self.answer
            ),
            "profile_digest": kwargs["direct_response_profile_digest"],
            "execution_authority": False,
        }


class _UnavailablePreflightModel:
    def __init__(self) -> None:
        self.calls = 0

    def preflight(self, **_kwargs: Any) -> None:
        self.calls += 1
        return None


def _preflight_boundary(model: _PreflightModel) -> ConversationPreflightBoundary:
    return ConversationPreflightBoundary(
        binding=ConversationPreflightBinding(
            model=model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
        narrator=SocialResponseNarratorBinding(
            model=model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )


def _unavailable_preflight_boundary(
    model: _UnavailablePreflightModel,
) -> ConversationPreflightBoundary:
    return ConversationPreflightBoundary(
        binding=ConversationPreflightBinding(
            model=model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        )
    )


class _ObservedJudgmentModel(_GreetingJudgmentModel):
    def __init__(self, observation: SemanticJudgmentObservation) -> None:
        super().__init__("object_set")
        self._observation = observation

    def judge(self, **kwargs: Any) -> SemanticJudgmentModelResponse:
        return SemanticJudgmentModelResponse(
            proposal=super().judge(**kwargs),
            observation=self._observation,
        )


class _ActionTypeOnlyDraftJudgmentModel(_DraftJudgmentModel):
    def judge(self, *, utterance: str, **_kwargs: Any) -> dict[str, object]:
        value = "remediate.restrict-network-access"
        start = utterance.index(value)
        return {
            "primary_intent": "action_request",
            "targets": [
                {
                    "kind": "action_type",
                    "value": value,
                    "canonical_value": value,
                    "source_start": start,
                    "source_end": start + len(value),
                }
            ],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "draft_only",
            "action_subject": "Rule",
            "execution_authority": False,
        }


class _LowConfidenceDraftJudgmentModel(_DraftJudgmentModel):
    def judge(self, *, utterance: str, **kwargs: Any) -> dict[str, object]:
        proposal = super().judge(utterance=utterance, **kwargs)
        proposal["confidence"] = 0.5
        return proposal


class _LocalizedActionPostureJudgmentModel:
    def __init__(
        self,
        *,
        source_value: str,
        action_posture: str,
        action_subject: str,
    ) -> None:
        self._source_value = source_value
        self._action_posture = action_posture
        self._action_subject = action_subject

    def judge(self, *, utterance: str, **_kwargs: Any) -> dict[str, object]:
        source_start = utterance.index(self._source_value)
        return {
            "primary_intent": (
                "action_request" if self._action_posture == "draft_only" else "incident_evidence"
            ),
            "targets": [
                {
                    "kind": "request_concept",
                    "value": self._source_value,
                    "source_start": source_start,
                    "source_end": source_start + len(self._source_value),
                }
            ],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": self._action_posture,
            "action_subject": self._action_subject,
            "execution_authority": False,
        }


class _IncidentDraftJudgmentModel:
    def judge(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "primary_intent": "action_request",
            "targets": [],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "draft_only",
            "action_subject": "Incident",
            "execution_authority": False,
        }


class _OperatingSubjectJudgmentModel:
    def judge(self, *, utterance: str, **_kwargs: Any) -> dict[str, object]:
        targets = []
        source_values = (
            (("비용 목표", "CostObjective"), ("비즈니스 서비스", "BusinessService"))
            if "비용 목표" in utterance
            else (
                ("cost objective", "CostObjective"),
                ("business service", "BusinessService"),
            )
        )
        for value, canonical_value in source_values:
            source_start = utterance.index(value)
            targets.append(
                {
                    "kind": "object_type",
                    "value": value,
                    "canonical_value": canonical_value,
                    "source_start": source_start,
                    "source_end": source_start + len(value),
                }
            )
        return {
            "primary_intent": "cost_objective_detail",
            "targets": targets,
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "execution_authority": False,
        }


class _JudgmentAwareModel(_Model):
    def propose_frame(self, **kwargs: Any) -> Any:
        self.frame_calls += 1
        judgment = kwargs.get("semantic_judgment")
        assert isinstance(judgment, dict)
        assert judgment.get("action_posture") == "draft_only"
        return _frame()


class _AcceptingVerifier:
    def verify(self, _plan: object, *, manifest: object) -> None:
        assert manifest is not None


def _fixture(
    *,
    property_values: tuple[PropertyValueDomain, ...] = (),
    include_rule: bool = False,
    include_resource_type: bool = False,
    function_types: tuple[OntologyFunctionType, ...] = (),
    additional_object_types: tuple[OntologyObjectType, ...] = (),
    additional_link_types: tuple[OntologyLinkType, ...] = (),
) -> tuple[Any, ObjectSetDefinition]:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "secret": PropertyDecl(type=PropertyType.STRING, access_scope=CeilingRole.OWNER),
            **(
                {"type": PropertyDecl(type=PropertyType.STRING, required=True)}
                if include_resource_type
                else {}
            ),
        },
    )
    rule = OntologyObjectType(
        schema_version="1.0.0",
        name="Rule",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    object_types = (
        (resource, *additional_object_types, rule)
        if include_rule
        else (resource, *additional_object_types)
    )
    release = build_ontology_release(
        object_types=object_types,
        link_types=additional_link_types,
        function_types=function_types,
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=object_types,
        link_types=additional_link_types,
        functions=function_types,
        bound_function_names=tuple(item.name for item in function_types),
        property_values=property_values,
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(ObjectPredicate(property="id", equals="resource-a"),),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )
    return manifest, definition


def _frame(**overrides: object) -> dict[str, object]:
    return {
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
        **overrides,
    }


def _plan(definition: ObjectSetDefinition) -> dict[str, object]:
    return {
        "nodes": [
            {
                "node_id": "resources",
                "kind": "object_set",
                "depends_on": [],
                "arguments": {"definition": definition.model_dump(mode="json")},
                "output_kind": "query.table",
            }
        ],
        "output_node_ids": ["resources"],
    }


def _function_plan(
    function_name: str,
    *,
    output_kind: str,
    function_arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "nodes": [
            {
                "node_id": "function-result",
                "kind": "function",
                "depends_on": [],
                "arguments": {
                    "function_name": function_name,
                    "arguments": function_arguments or {},
                    "dependency_arguments": {},
                },
                "output_kind": output_kind,
            }
        ],
        "output_node_ids": ["function-result"],
    }


def _function_set_plan(*function_names: str) -> dict[str, object]:
    function_arguments: dict[str, dict[str, object]] = {
        "query.inventory_impact": {"depth": 1, "link_types": ["contains"]},
        "query.ontology_evidence_health": {"object_type": "Resource"},
        "query.ontology_release_diff": {
            "base_release_digest": DIGEST,
            "candidate_release_digest": "sha256:" + ("b" * 64),
            "limit": 100,
        },
    }
    return {
        "nodes": [
            {
                "node_id": f"function-{index}",
                "kind": "function",
                "depends_on": [],
                "arguments": {
                    "function_name": function_name,
                    "arguments": function_arguments[function_name],
                    "dependency_arguments": {},
                },
                "output_kind": "query.table",
            }
            for index, function_name in enumerate(function_names)
        ],
        "output_node_ids": [f"function-{index}" for index in range(len(function_names))],
    }


def _declaration_sections_plan(*sections: str) -> dict[str, object]:
    nodes = [
        {
            "node_id": section,
            "kind": "function",
            "depends_on": [],
            "arguments": {
                "function_name": "query.ontology_declaration",
                "arguments": {
                    "kind": "object",
                    "name": "Resource",
                    "section": section,
                    "limit": 100,
                },
                "dependency_arguments": {},
            },
            "output_kind": "query.table",
        }
        for section in sections
    ]
    return {"nodes": nodes, "output_node_ids": list(sections)}


def _aggregate_plan(definition: ObjectSetDefinition) -> dict[str, object]:
    plan = _plan(definition)
    plan["nodes"] = [
        *plan["nodes"],  # type: ignore[misc]
        {
            "node_id": "aggregate",
            "kind": "aggregate",
            "depends_on": ["resources"],
            "arguments": {"operation": "count", "group_by": [], "limit": 10},
            "output_kind": "query.table",
        },
    ]
    plan["output_node_ids"] = ["aggregate"]
    return plan


def _manifest_aggregate_plan(*, kinds: tuple[str, ...] = ("object",)) -> dict[str, object]:
    plan = _function_plan(
        "query.manifest",
        output_kind="query.table",
        function_arguments={"kinds": list(kinds), "limit": 1000},
    )
    plan["nodes"] = [
        *plan["nodes"],  # type: ignore[misc]
        {
            "node_id": "aggregate",
            "kind": "aggregate",
            "depends_on": ["function-result"],
            "arguments": {"operation": "count", "group_by": [], "limit": 10},
            "output_kind": "query.table",
        },
    ]
    plan["output_node_ids"] = ["aggregate"]
    return plan


def _target_cardinality_language() -> InventoryQueryLanguageRegistry:
    return InventoryQueryLanguageRegistry(
        schema_version="1.1.0",
        version="1.1.0",
        default_scope="subscription",
        default_activity_lookback_seconds=604800,
        current_requires_fresh=True,
        suffixes=("은", "는", "이", "가", "의", "을", "를"),
        signals={
            "target_singular": QueryTerms(terms=("my", "this", "내", "해당")),
            "target_collection": QueryTerms(
                terms=("all", "every", "list", "모두", "모든", "전체", "목록")
            ),
        },
        query_kinds={},
        groupings={},
        projections={},
        scopes={},
        states={},
        operations={},
        time_units={},
    )


def _activity_language() -> InventoryQueryLanguageRegistry:
    return InventoryQueryLanguageRegistry(
        schema_version="1.1.0",
        version="1.1.0",
        default_scope="subscription",
        default_activity_lookback_seconds=604800,
        current_requires_fresh=True,
        suffixes=("은", "는", "이", "가", "의", "을", "를"),
        signals={
            "activity": QueryTerms(terms=("changed", "변경", "변경됐어")),
            "causal_diagnosis": QueryTerms(terms=("why", "cause", "왜", "원인")),
        },
        query_kinds={},
        groupings={},
        projections={},
        scopes={},
        states={},
        operations={},
        time_units={},
    )


def _service(
    t1: _Model,
    t2: _Model,
    manifest: Any,
    *,
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
) -> SemanticPlanningService:
    return SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        inventory_query_language=inventory_query_language,
        now=lambda: NOW,
    )


def _run(
    service: SemanticPlanningService,
    *,
    utterance: str = "Show matching resources",
    locale: str = "en",
):  # type: ignore[no-untyped-def]
    return service.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        locale=locale,
    )


def test_valid_t1_plan_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets", "_expected_intent"),
    [
        ("greeting", (), SemanticDirectResponseIntent.GREETING),
        ("self_introduction", (), SemanticDirectResponseIntent.SELF_INTRODUCTION),
        (
            "self_introduction",
            ("identity", "role"),
            SemanticDirectResponseIntent.SELF_INTRODUCTION,
        ),
    ],
)
def test_full_judgment_social_intent_requires_bound_social_narrator(
    primary_intent: str,
    requested_facets: tuple[str, ...],
    _expected_intent: SemanticDirectResponseIntent,
) -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_GreetingJudgmentModel(
                primary_intent,
                requested_facets=requested_facets,
            ),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="The model interprets this complete turn")

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "social_response_narrator_unavailable"
    assert outcome.direct_response_intent is None
    assert outcome.direct_response_answer is None
    assert outcome.plan is None
    assert manifests.calls == 1
    assert (t1.frame_calls, t1.plan_calls) == (0, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_preflight_direct_social_bypasses_manifest_and_full_judgment() -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    full_model = _GreetingJudgmentModel("greeting")
    preflight_model = _PreflightModel(
        social_act="greeting",
        operational_signal="none",
        answer="반가워요. 무엇을 함께 살펴볼까요?",
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=full_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
        preflight=_preflight_boundary(preflight_model),
    )
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="안녕", locale="ko")

    assert outcome.disposition is SemanticPlanningDisposition.DIRECT_RESPONSE
    assert outcome.direct_response_answer == "반가워요. 무엇을 함께 살펴볼까요?"
    assert outcome.social_act.value == "greeting"
    assert manifests.calls == 0
    assert full_model.calls == 0
    assert (t1.frame_calls, t1.plan_calls) == (0, 0)


def test_preflight_mixed_social_turn_continues_full_operational_planning() -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    full_model = _GreetingJudgmentModel("greeting")
    preflight_model = _PreflightModel(
        social_act="greeting",
        operational_signal="mixed",
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=full_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
        preflight=_preflight_boundary(preflight_model),
    )
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="안녕, 현재 상태를 알려줘", locale="ko")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.social_act.value == "greeting"
    assert manifests.calls == 1
    assert full_model.calls == 1
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)


def test_preflight_context_independent_greeting_with_prior_turn_stays_direct() -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    full_model = _GreetingJudgmentModel("status")
    preflight_model = _PreflightModel(
        social_act="greeting",
        operational_signal="none",
        context_dependency="social_continuity",
        answer="안녕하세요. FDAI Console의 Bragi입니다.",
        continued_answer=(
            "다시 인사해 주셔서 반갑습니다. 이어서 살펴볼 운영 내용을 말씀해 주세요."
        ),
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=full_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
        preflight=_preflight_boundary(preflight_model),
    )
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="좋아",
        prior_turns=(Turn(turn_id="prior", direction="outbound", content="Proceed?"),),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        locale="ko",
    )

    assert outcome.disposition is SemanticPlanningDisposition.DIRECT_RESPONSE
    assert outcome.direct_response_answer == (
        "다시 인사해 주셔서 반갑습니다. 이어서 살펴볼 운영 내용을 말씀해 주세요."
    )
    assert manifests.calls == 0
    assert full_model.calls == 0


@pytest.mark.parametrize(
    ("social_act", "answer"),
    [
        ("thanks", "감사합니다. 이어서 필요하신 내용을 말씀해 주세요."),
        ("farewell", "함께해 주셔서 감사합니다. 다음에 다시 뵙겠습니다."),
    ],
)
def test_preflight_additional_social_act_stays_direct(
    social_act: str,
    answer: str,
) -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    full_model = _GreetingJudgmentModel("status")
    preflight_model = _PreflightModel(
        social_act=social_act,
        operational_signal="none",
        context_dependency="social_continuity",
        answer=answer,
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=full_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
        preflight=_preflight_boundary(preflight_model),
    )
    service = SemanticPlanningService(
        model=_Model(frame=_frame(), plan=_plan(definition)),
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="social turn",
        prior_turns=(Turn(turn_id="prior", direction="outbound", content="Prior answer"),),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        locale="ko",
    )

    assert outcome.disposition is SemanticPlanningDisposition.DIRECT_RESPONSE
    assert outcome.direct_response_intent is SemanticDirectResponseIntent.GREETING
    assert outcome.direct_response_answer == answer
    assert manifests.calls == 0
    assert full_model.calls == 0


def test_preflight_pending_decision_with_prior_turn_uses_full_planning() -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    full_model = _GreetingJudgmentModel("status")
    preflight_model = _PreflightModel(
        social_act="acknowledgement",
        operational_signal="contextual",
        context_dependency="pending_decision",
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=full_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
        preflight=_preflight_boundary(preflight_model),
    )
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="좋아",
        prior_turns=(Turn(turn_id="prior", direction="outbound", content="Proceed?"),),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        locale="ko",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert manifests.calls == 1
    assert full_model.calls == 1


def test_preflight_acknowledgement_vetoes_contradictory_full_direct_response() -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    full_model = _GreetingJudgmentModel("greeting")
    preflight_model = _PreflightModel(
        social_act="acknowledgement",
        operational_signal="none",
        context_dependency="none",
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=full_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
        preflight=_preflight_boundary(preflight_model),
    )
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="좋아, 진행해 주세요", locale="ko")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert manifests.calls == 1
    assert full_model.calls == 1
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)


def test_malformed_preflight_vetoes_contradictory_full_direct_response() -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    full_model = _GreetingJudgmentModel("greeting")
    malformed_preflight = _PreflightModel(
        social_act="acknowledgement",
        operational_signal="explicit",
        context_dependency="pending_decision",
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=full_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
        preflight=_preflight_boundary(malformed_preflight),
    )
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="좋아, 진행해 주세요", locale="ko")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert manifests.calls == 1
    assert full_model.calls == 1
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)


def test_full_judgment_direct_response_without_narrator_holds_prior_thread() -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    full_model = _GreetingJudgmentModel("greeting")
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=full_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="좋아",
        prior_turns=(Turn(turn_id="prior", direction="outbound", content="Proceed?"),),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        locale="ko",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "social_response_narrator_unavailable"
    assert full_model.calls == 1
    assert (t1.frame_calls, t1.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    "preflight_model",
    [
        _PreflightModel(
            social_act="greeting",
            operational_signal="none",
            answer="Hello.",
            confidence=0.89,
        ),
    ],
)
def test_preflight_noneligible_candidate_uses_full_planning(
    preflight_model: _PreflightModel,
) -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    full_model = _GreetingJudgmentModel("status")
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=full_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
        preflight=_preflight_boundary(preflight_model),
    )
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert manifests.calls == 1
    assert full_model.calls == 1
    assert preflight_model.calls == 1


def test_low_confidence_social_preflight_never_uses_full_judgment_prose() -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    full_model = _GreetingJudgmentModel(
        "greeting",
        answer="The full semantic judgment authored this response.",
    )
    preflight_model = _PreflightModel(
        social_act="greeting",
        operational_signal="none",
        answer="Low-confidence draft.",
        confidence=0.89,
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=full_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
        preflight=_preflight_boundary(preflight_model),
    )
    service = SemanticPlanningService(
        model=_Model(frame=_frame(), plan=_plan(definition)),
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Hello")

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "social_response_narrator_unavailable"
    assert manifests.calls == 1
    assert full_model.calls == 1


def test_unavailable_preflight_never_uses_full_judgment_prose() -> None:
    manifest, definition = _fixture()
    manifests = _ManifestProvider(manifest)
    full_model = _GreetingJudgmentModel(
        "greeting",
        answer="The full semantic judgment authored this response.",
    )
    preflight_model = _UnavailablePreflightModel()
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=full_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
        preflight=_unavailable_preflight_boundary(preflight_model),
    )
    service = SemanticPlanningService(
        model=_Model(frame=_frame(), plan=_plan(definition)),
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Hello")

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "social_response_narrator_unavailable"
    assert preflight_model.calls == 1
    assert full_model.calls == 1


@pytest.mark.parametrize(
    "primary_intent",
    ["advise.greeting", "conversation_greeting", "identity"],
)
def test_noncanonical_social_intent_does_not_select_direct_response(
    primary_intent: str,
) -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_GreetingJudgmentModel(primary_intent),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    manifests = _ManifestProvider(manifest)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Greetings, operator")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.direct_response_intent is None
    assert outcome.manifest_digest == manifest.manifest_digest
    assert outcome.plan is not None
    assert manifests.calls == 1
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_planned_outcome_retains_authority_free_model_observation() -> None:
    manifest, definition = _fixture()
    observation = SemanticJudgmentObservation(
        model="semantic-test",
        usage={"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        trace_call={"duration_ms": 25},
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_ObservedJudgmentModel(observation),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=_Model(frame=_frame(), plan=_plan(definition)),
        escalation_model=None,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.model_observations == (observation,)
    assert outcome.execution_authority is False


def test_greeting_prefixed_operational_judgment_keeps_query_planning() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_GreetingJudgmentModel("status"),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    manifests = _ManifestProvider(manifest)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        semantic_judgment=judgment,
        manifests=manifests,
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="안녕, 현재 상태 알려줘")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.direct_response_intent is None
    assert manifests.calls == 1
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_self_introduction_with_operational_request_keeps_query_planning() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = _service(t1, t2, manifest)

    outcome = _run(service, utterance="너를 소개하고 현재 상태도 알려줘")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.direct_response_intent is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_social_primary_with_operational_facet_keeps_query_planning() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_GreetingJudgmentModel(
                "self_introduction",
                requested_facets=("current_model_state",),
            ),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="The model preserved an operational facet")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.direct_response_intent is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_advise_only_judgment_rejects_action_draft_frame() -> None:
    manifest, _definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="action_draft",
            subject_constraints=["ActionType"],
            output_shape="action_draft",
        ),
        plan=None,
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_GreetingJudgmentModel(
                "procedure",
                requested_facets=("governance", "restart"),
            ),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="The model selected an advise-only procedure")

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_action_posture_mismatch"
    assert outcome.plan is None
    assert outcome.execution_authority is False
    assert t1.plan_calls == 0


def test_evidence_validation_without_a_coverage_function_is_unavailable() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="validate",
            output_shape="evidence_validation",
            evidence_requirements=["evidence_completeness"],
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_evidence_validation_unavailable"
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_evidence_validation_subject_clarification_resolves_then_holds() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="validate",
            subject_constraints=[],
            output_shape="evidence_validation",
            evidence_requirements=["evidence_completeness"],
            unresolved_terms=["visible resources"],
            clarification_requirements=["subject"],
            clarification="Which resources should I validate?",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_evidence_validation_unavailable"
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Resource",)
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_evidence_validation_resource_identity_resolves_then_holds() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="validate",
            subject_constraints=[],
            output_shape="evidence_validation",
            evidence_requirements=["evidence_completeness"],
            unresolved_terms=["visible resource identity"],
            clarification_requirements=["resource_identity"],
            clarification="Which visible resource identity should I validate?",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_evidence_validation_unavailable"
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Resource",)
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_evidence_validation_keeps_concrete_subject_clarification() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="validate",
            subject_constraints=["resource-a"],
            output_shape="evidence_validation",
            unresolved_terms=["resource-a"],
            clarification_requirements=["subject"],
            clarification="Which resource-a identity should I validate?",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert t1.plan_calls == 0
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_misclassified_evidence_validation_fails_closed_without_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(operation="validate", output_shape="resource_list"),
        plan=_plan(definition),
    )
    t2 = _Model(
        frame=_frame(
            operation="validate",
            output_shape="evidence_validation",
            evidence_requirements=["evidence_completeness"],
        ),
        plan=_plan(definition),
    )

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_misclassified_causal_frame_fails_closed_without_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(operation="select", output_shape="causal_evidence"),
        plan=_plan(definition),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_target_bound_causal_frame_omission_does_not_invoke_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="explain_change",
            subject_constraints=["Resource", "resource-a"],
            output_shape="causal_evidence",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest), utterance="Why is resource-a slower?")

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_target_bound_t1_omission_stays_t1_when_t2_is_unavailable() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="explain_change",
            subject_constraints=["Resource", "resource-a"],
            output_shape="causal_evidence",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest), utterance="Why is resource-a slower?")

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert outcome.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_t1_clarification_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            unresolved_terms=["resource"],
            clarification_requirements=["subject"],
            clarification="Which resource do you mean?",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert t1.plan_calls == 0
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_impact_without_exact_target_uses_typed_clarification() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            output_shape="inventory_impact",
            unresolved_terms=["resource_identity"],
            clarification_requirements=["resource_identity"],
            clarification="Which exact resource should I assess for impact?",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=None)

    outcome = _run(
        _service(t1, t2, manifest),
        utterance="이 데이터베이스에 장애가 나면 어떤 서비스가 영향을 받아?",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.clarification == "Which exact resource should I assess for impact?"
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_current_topology_question_does_not_trigger_impact_rejection() -> None:
    manifest, definition = _fixture()
    topology_plan = {
        "nodes": [
            {
                "node_id": "topology",
                "kind": "topology_at",
                "depends_on": [],
                "arguments": {
                    "as_of": NOW.isoformat(),
                    "known_at": NOW.isoformat(),
                },
                "output_kind": "topology.graph",
            }
        ],
        "output_node_ids": ["topology"],
    }
    t1 = _Model(frame=_frame(output_shape="topology_graph"), plan=topology_plan)
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="psql-example의 현재 연결 상태를 보여줘")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_targetless_topology_question_asks_for_exact_resource_before_candidates() -> None:
    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
    )
    t1 = _Model(
        frame=_frame(output_shape="topology_graph", temporal_scope={"kind": "current"}),
        plan=_plan(definition),
    )
    service = SemanticPlanningService(
        model=t1,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Show topology for my Container App.")

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Resource",)
    assert outcome.frame.output_shape == "ontology_relationships"
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert t1.frame_calls == 1
    assert t1.plan_calls == 0


def test_exact_target_impact_builds_service_path_without_t2() -> None:
    class _ReturningVerifier:
        def verify(self, plan: Any, *, manifest: object) -> Any:
            assert manifest is not None
            return plan

    catalog = load_ontology_catalog(
        ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
    )
    release = build_ontology_release(
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        action_types=catalog.action_types,
        interface_types=catalog.interface_types,
        function_types=catalog.function_types,
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=catalog.object_types,
        link_types=catalog.link_types,
        interfaces=catalog.interface_types,
        action_types=catalog.action_types,
        functions=catalog.function_types,
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource", "ca-fdai-dev-krc-core"],
            operation="select",
            output_shape="inventory_impact",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_ReturningVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance=(
            "For the exact target ca-fdai-dev-krc-core, which currently observed services "
            "and dependencies would be impacted if it became unavailable?"
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
    )
    target, services = outcome.plan.nodes
    assert target.arguments["definition"]["predicates"] == [
        {
            "property": "name",
            "operator": "equals",
            "equals": "ca-fdai-dev-krc-core",
        }
    ]
    assert services.depends_on == ("impact-target",)
    assert services.arguments["selector"] == {
        "kind": "object_type",
        "name": "BusinessService",
    }
    assert services.arguments["link_types"] == ["workload_runs_on", "implemented_by"]
    assert services.arguments["direction"] == "incoming"
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    ("utterance", "target", "lookback_seconds"),
    (
        (
            "ca-fdai-dev-krc-core에서 지난 30분 동안 revision 상태 변화나 재시작이 "
            "있었어? 시간과 근거를 보여줘.",
            "ca-fdai-dev-krc-core",
            1800,
        ),
        (
            "In the last 2 hours, did api-example restart or have a revision status change?",
            "api-example",
            7200,
        ),
        (
            "api-example의 지난 7일 변경 이력을 시간과 근거와 함께 보여줘.",
            "api-example",
            604800,
        ),
        (
            "api-example의 지난 1주일 변경 이력을 시간과 근거와 함께 보여줘.",
            "api-example",
            604800,
        ),
        (
            "Show the changes for api-example over the last week with evidence.",
            "api-example",
            604800,
        ),
    ),
)
def test_exact_target_activity_builds_bounded_read_without_t2(
    utterance: str,
    target: str,
    lookback_seconds: int,
) -> None:
    class _ReturningVerifier:
        def verify(self, plan: Any, *, manifest: object) -> Any:
            assert manifest is not None
            return plan

    manifest, _ = _fixture(function_types=(resource_activity_function_type(),))
    t1 = _Model(
        frame=_frame(
            operation="select",
            subject_constraints=["Resource", target],
            output_shape="target_activity",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_ReturningVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.SELECT
    assert outcome.frame.output_shape == "target_activity"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
    )
    target_node, activity = outcome.plan.nodes
    assert target_node.arguments["definition"]["predicates"] == [
        {"property": "id", "operator": "equals", "equals": target}
    ]
    assert activity.depends_on == ("activity-target",)
    assert activity.arguments["function_name"] == RESOURCE_ACTIVITY_FUNCTION_NAME
    assert activity.arguments["arguments"] == {"lookback_seconds": lookback_seconds}
    assert activity.arguments["dependency_arguments"] == {"activity-target": "query_result"}
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_temporal_comparison_exact_activity_frame_is_normalized_without_t2() -> None:
    class _ReturningVerifier:
        def verify(self, plan: Any, *, manifest: object) -> Any:
            assert manifest is not None
            return plan

    utterance = "지난 1주일 동안 api-example-prod Container App에서 무엇이 변경됐어?"
    manifest, _ = _fixture(function_types=(resource_activity_function_type(),))
    t1 = _Model(
        frame=_frame(
            operation="compare",
            subject_constraints=["Resource"],
            measure_concepts=["change_activity"],
            temporal_scope={"lookback_seconds": 604800},
            output_shape="temporal_comparison",
        ),
        plan=None,
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_ReturningVerifier(),  # type: ignore[arg-type]
        inventory_query_language=_activity_language(),
        now=lambda: NOW,
    )

    outcome = _run(service, utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.SELECT
    assert outcome.frame.output_shape == "target_activity"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.nodes[1].arguments["function_name"] == RESOURCE_ACTIVITY_FUNCTION_NAME
    assert outcome.plan.nodes[1].arguments["arguments"] == {"lookback_seconds": 604800}
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    ("frame", "expected_disposition", "expected_reason"),
    [
        (
            _frame(
                operation="compare",
                subject_constraints=["Change"],
                temporal_scope={"kind": "windowed"},
                output_shape="temporal_comparison",
            ),
            SemanticPlanningDisposition.UNAVAILABLE,
            "semantic_temporal_comparison_unavailable",
        ),
        (
            _frame(),
            SemanticPlanningDisposition.UNSUPPORTED,
            "semantic_plan_invalid",
        ),
    ],
)
def test_invalid_temporal_comparison_holds_without_widening_other_failures(
    frame: dict[str, object],
    expected_disposition: SemanticPlanningDisposition,
    expected_reason: str,
) -> None:
    class _RejectingVerifier:
        def verify(self, _plan: object, *, manifest: object) -> None:
            assert manifest is not None
            raise ValueError("invalid test plan")

    manifest, definition = _fixture()
    service = SemanticPlanningService(
        model=_Model(frame=frame, plan=_plan(definition)),
        manifests=_ManifestProvider(manifest),
        verifier=_RejectingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is expected_disposition
    assert outcome.reason == expected_reason
    assert outcome.execution_authority is False


def test_change_comparison_rejects_generic_topology_substitution() -> None:
    class _ReturningVerifier:
        def verify(self, plan: Any, *, manifest: object) -> Any:
            assert manifest is not None
            return plan

    manifest, _definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="compare",
            subject_constraints=["Change"],
            measure_concepts=["change_activity_correlation"],
            temporal_scope={"kind": "windowed"},
            output_shape="temporal_comparison",
        ),
        plan={
            "nodes": [
                {
                    "node_id": "baseline",
                    "kind": "topology_at",
                    "depends_on": [],
                    "arguments": {},
                    "output_kind": "topology.graph",
                },
                {
                    "node_id": "current",
                    "kind": "topology_at",
                    "depends_on": [],
                    "arguments": {},
                    "output_kind": "topology.graph",
                },
                {
                    "node_id": "difference",
                    "kind": "topology_diff",
                    "depends_on": ["baseline", "current"],
                    "arguments": {},
                    "output_kind": "topology.diff",
                },
            ],
            "output_node_ids": ["difference"],
        },
    )
    service = SemanticPlanningService(
        model=t1,
        manifests=_ManifestProvider(manifest),
        verifier=_ReturningVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_temporal_comparison_unavailable"
    assert outcome.execution_authority is False


@pytest.mark.parametrize(
    ("utterance", "operation", "subjects"),
    (
        (
            "지난 1주일 동안 api-example에서 왜 변경이 발생했어?",
            "compare",
            ["Resource", "api-example"],
        ),
        (
            "지난 1주일 동안 Container App에서 무엇이 변경됐어?",
            "compare",
            ["Resource"],
        ),
        (
            "지난 1주일 동안 api-example-prod와 api-worker-prod에서 무엇이 변경됐어?",
            "compare",
            ["Resource"],
        ),
        (
            "지난 1주일과 지난 1일 동안 api-example에서 무엇이 변경됐어?",
            "compare",
            ["Resource", "api-example"],
        ),
        (
            "지난 1주일 동안 api-example 변경을 집계해 줘.",
            "aggregate",
            ["Resource", "api-example"],
        ),
        (
            "지난 1주일 동안 api-example 변경관리 현황을 보여줘.",
            "compare",
            ["Resource", "api-example"],
        ),
    ),
)
def test_activity_normalization_keeps_ambiguous_or_non_read_frames_closed(
    utterance: str,
    operation: str,
    subjects: list[str],
) -> None:
    manifest, _ = _fixture(function_types=(resource_activity_function_type(),))
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            operation=operation,
            subject_constraints=subjects,
            measure_concepts=["change_activity"],
            temporal_scope={"lookback_seconds": 604800},
            output_shape=(
                "aggregation_table" if operation == "aggregate" else "temporal_comparison"
            ),
        )
    )

    normalized = normalize_activity_proposal(
        proposal,
        utterance=utterance,
        descriptors=manifest.descriptors,
        inventory_query_language=_activity_language(),
    )

    assert normalized is proposal


@pytest.mark.parametrize(
    "utterance",
    (
        "Why did api-example restart in the last 30 minutes?",
        "api-example가 왜 지난 30분 동안 재시작했어?",
        "api-example에 revision 상태 변화나 재시작이 있었어?",
    ),
)
def test_causal_or_unbounded_activity_does_not_complete_frame(utterance: str) -> None:
    manifest, definition = _fixture(function_types=(resource_activity_function_type(),))
    t1 = _Model(
        frame=_frame(
            operation="explain_change",
            subject_constraints=["Resource", "api-example"],
            output_shape="causal_evidence",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=None)

    outcome = _run(_service(t1, t2, manifest), utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    ("utterance", "target"),
    (
        (
            "ca-fdai-dev-krc-core의 현재 활성 revision 이름과 ready 상태를 보여줘. "
            "각각의 관측 시각과 근거도 포함해.",
            "ca-fdai-dev-krc-core",
        ),
        (
            "Show the current revision name and ready state for api-example with evidence.",
            "api-example",
        ),
    ),
)
def test_exact_target_current_state_builds_function_read_without_t2(
    utterance: str,
    target: str,
) -> None:
    class _ReturningVerifier:
        def verify(self, plan: Any, *, manifest: object) -> Any:
            assert manifest is not None
            return plan

    manifest, _ = _fixture(function_types=(resource_current_state_function_type(),))
    t1 = _Model(
        frame=_frame(
            operation="select",
            subject_constraints=["Resource", target],
            output_shape="target_current_state",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_ReturningVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.SELECT
    assert outcome.frame.output_shape == "target_current_state"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
    )
    target_node, current_state = outcome.plan.nodes
    assert target_node.arguments["definition"]["predicates"] == [
        {"property": "id", "operator": "equals", "equals": target}
    ]
    assert current_state.depends_on == ("current-state-target",)
    assert current_state.arguments["function_name"] == RESOURCE_CURRENT_STATE_FUNCTION_NAME
    assert current_state.arguments["arguments"] == {}
    assert current_state.arguments["dependency_arguments"] == {
        "current-state-target": "query_result"
    }
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_exact_target_ingress_builds_typed_function_read_without_t2() -> None:
    class _ReturningVerifier:
        def verify(self, plan: Any, *, manifest: object) -> Any:
            assert manifest is not None
            return plan

    manifest, _ = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        function_types=(resource_ingress_function_type(),),
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource", "app-example"],
            measure_concepts=["ingress_configuration"],
            output_shape="property_filtered_resources",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_ReturningVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance="app-example의 인그레스 구성을 근거와 함께 보여줘.",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "target_ingress_configuration"
    assert outcome.plan is not None
    target, ingress = outcome.plan.nodes
    assert target.arguments["definition"]["predicates"] == [
        {"property": "id", "operator": "equals", "equals": "app-example"},
        {"property": "type", "operator": "equals", "equals": "compute.container-app"},
    ]
    assert ingress.arguments["function_name"] == RESOURCE_INGRESS_FUNCTION_NAME
    assert ingress.arguments["dependency_arguments"] == {"ingress-target": "query_result"}
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_exact_target_memory_percentage_builds_seven_day_metric_read_without_t2() -> None:
    class _ReturningVerifier:
        def verify(self, plan: Any, *, manifest: object) -> Any:
            assert manifest is not None
            return plan

    manifest, _ = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        function_types=(resource_metric_function_type(),),
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource", "app-example"],
            measure_concepts=["resource.memory.usage_pct"],
            temporal_scope={"lookback_seconds": 604800},
            output_shape="resource_metric_list",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_ReturningVerifier(),  # type: ignore[arg-type]
        metric_concepts=("resource.memory.usage_pct",),
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance=("app-example Container App의 지난 7일 평균 메모리 사용률을 근거와 함께 보여줘."),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "target_resource_metric"
    assert outcome.plan is not None
    target, metric = outcome.plan.nodes
    assert target.arguments["definition"]["predicates"] == [
        {"property": "type", "operator": "equals", "equals": "compute.container-app"},
        {"property": "id", "operator": "equals", "equals": "app-example"},
    ]
    assert target.arguments["definition"]["limit"] == 2
    assert metric.arguments["function_name"] == RESOURCE_METRIC_FUNCTION_NAME
    assert metric.arguments["arguments"] == {
        "metric_concepts": ["resource.memory.usage_pct"],
        "window_seconds": 604800,
    }
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_exact_target_memory_percentage_chart_builds_metric_series_without_t2() -> None:
    class _ReturningVerifier:
        def verify(self, plan: Any, *, manifest: object) -> Any:
            assert manifest is not None
            return plan

    manifest, _ = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        function_types=(resource_metric_series_function_type(),),
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource", "app-example"],
            measure_concepts=["resource.memory.usage_pct"],
            temporal_scope={"lookback_seconds": 604800},
            output_shape="target_resource_metric_series",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_ReturningVerifier(),  # type: ignore[arg-type]
        metric_concepts=("resource.memory.usage_pct",),
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance=("app-example Container App의 지난 7일 메모리 사용률을 시각화해 줘."),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "target_resource_metric_series"
    assert outcome.plan is not None
    target, metric = outcome.plan.nodes
    assert target.kind is QueryNodeKind.OBJECT_SET
    assert metric.kind is QueryNodeKind.FUNCTION
    assert metric.depends_on == (target.node_id,)
    assert metric.arguments["function_name"] == RESOURCE_METRIC_SERIES_FUNCTION_NAME
    assert metric.arguments["arguments"] == {
        "metric_concept": "resource.memory.usage_pct",
        "window_seconds": int(timedelta(days=7).total_seconds()),
    }
    assert metric.arguments["dependency_arguments"] == {target.node_id: "query_result"}
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_exact_target_chart_normalizes_aggregate_metric_frame_without_t2() -> None:
    class _ReturningVerifier:
        def verify(self, plan: Any, *, manifest: object) -> Any:
            assert manifest is not None
            return plan

    manifest, _ = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        function_types=(resource_metric_series_function_type(),),
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource", "ca-fdai-dev-krc-core"],
            measure_concepts=["resource.memory.usage_pct"],
            temporal_scope={"lookback_seconds": 604800},
            output_shape="target_resource_metric",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_ReturningVerifier(),  # type: ignore[arg-type]
        metric_concepts=("resource.memory.usage_pct",),
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance=(
            "지난 1주일간 ca-fdai-dev-krc-core Container App의 메모리 사용률(%)을 시각화해줘."
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "target_resource_metric_series"
    assert outcome.plan is not None
    assert outcome.plan.nodes[-1].arguments["function_name"] == (
        RESOURCE_METRIC_SERIES_FUNCTION_NAME
    )
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_exact_target_chart_normalizes_temporal_comparison_frame_without_t2() -> None:
    class _ReturningVerifier:
        def verify(self, plan: Any, *, manifest: object) -> Any:
            assert manifest is not None
            return plan

    manifest, _ = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        function_types=(resource_metric_series_function_type(),),
    )
    t1 = _Model(
        frame=_frame(
            operation="compare",
            subject_constraints=["Resource", "ca-fdai-dev-krc-core"],
            measure_concepts=["resource.memory.usage_pct"],
            temporal_scope={"lookback_seconds": 604800},
            output_shape="temporal_comparison",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_ReturningVerifier(),  # type: ignore[arg-type]
        metric_concepts=("resource.memory.usage_pct",),
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance=(
            "지난 1주일간 ca-fdai-dev-krc-core Container App의 메모리 사용률(%)을 시각화해줘."
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.SELECT
    assert outcome.frame.output_shape == "target_resource_metric_series"
    assert outcome.plan is not None
    assert outcome.plan.nodes[-1].arguments["function_name"] == (
        RESOURCE_METRIC_SERIES_FUNCTION_NAME
    )
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_exact_target_health_assessment_builds_bounded_read_without_t2() -> None:
    manifest, _ = _fixture(
        function_types=(
            resource_activity_function_type(),
            resource_current_state_function_type(),
            target_health_assessment_function_type(),
        )
    )
    t1 = _Model(
        frame=_frame(
            operation="validate",
            subject_constraints=["Resource", "ca-fdai-dev-krc-core"],
            measure_concepts=["health", "readiness", "evidence_freshness"],
            output_shape="target_health_assessment",
            evidence_requirements=["application_health", "evidence_gaps"],
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(
                QueryNodeKind.OBJECT_SET,
                QueryNodeKind.FUNCTION,
                QueryNodeKind.METRIC_SCOPE_SERIES,
            ),
            extension_argument_schemas={
                QueryNodeKind.METRIC_SCOPE_SERIES: METRIC_ARGUMENT_SCHEMAS[
                    QueryNodeKind.METRIC_SCOPE_SERIES
                ]
            },
            reviewed_metric_concepts=(
                "request.errors",
                "request.volume",
                "resource.saturation",
            ),
        ),
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance=(
            "For the exact target ca-fdai-dev-krc-core, is the current evidence sufficient "
            "to claim it is healthy? Separate platform lifecycle and readiness from "
            "application-service health, state evidence freshness and gaps, and do not "
            "execute changes."
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.VALIDATE
    assert outcome.frame.output_shape == "target_health_assessment"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.output_node_ids == ("target-health-assessment",)
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {
            "property": "id",
            "operator": "equals",
            "equals": "ca-fdai-dev-krc-core",
        }
    ]
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_exact_target_error_activity_correlation_builds_bounded_read_without_t2() -> None:
    manifest, _ = _fixture(
        function_types=(
            resource_activity_function_type(),
            error_activity_correlation_function_type(),
        )
    )
    t1 = _Model(
        frame=_frame(
            operation="compare",
            subject_constraints=["Resource", "ca-fdai-dev-krc-core"],
            measure_concepts=["request.errors", "activity_log"],
            output_shape="target_error_activity_correlation",
            evidence_requirements=["equal_windows", "freshness", "evidence_gaps"],
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(
                QueryNodeKind.OBJECT_SET,
                QueryNodeKind.FUNCTION,
                QueryNodeKind.METRIC_SCOPE_SERIES,
            ),
            extension_argument_schemas={
                QueryNodeKind.METRIC_SCOPE_SERIES: METRIC_ARGUMENT_SCHEMAS[
                    QueryNodeKind.METRIC_SCOPE_SERIES
                ]
            },
            reviewed_metric_concepts=("request.errors",),
        ),
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance=(
            "For the exact target ca-fdai-dev-krc-core over the last 30 minutes, did "
            "request errors increase, and is there any correlated Activity Log change? "
            "Separate missing evidence from zero, state the evidence window, freshness, "
            "and gaps, and do not execute changes."
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.COMPARE
    assert outcome.frame.output_shape == "target_error_activity_correlation"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.output_node_ids == ("target-error-activity-correlation",)
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {
            "property": "id",
            "operator": "equals",
            "equals": "ca-fdai-dev-krc-core",
        }
    ]
    baseline, current = outcome.plan.nodes[1:3]
    assert baseline.arguments["concept_id"] == "request.errors"
    assert current.arguments["concept_id"] == "request.errors"
    assert baseline.arguments["end"] == current.arguments["start"]
    assert outcome.plan.nodes[3].arguments["function_name"] == RESOURCE_ACTIVITY_FUNCTION_NAME
    assert (
        outcome.plan.nodes[4].arguments["function_name"] == ERROR_ACTIVITY_CORRELATION_FUNCTION_NAME
    )
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    "utterance",
    (
        (
            "Why did request errors increase after an Activity Log change for "
            "ca-fdai-dev-krc-core in the last 30 minutes?"
        ),
        (
            "For api-example-primary or api-example-secondary in the last 30 minutes, "
            "did request errors increase with a correlated Activity Log change?"
        ),
    ),
)
def test_wrong_error_activity_frame_is_not_lexically_rewritten(
    utterance: str,
) -> None:
    manifest, definition = _fixture(
        function_types=(
            resource_activity_function_type(),
            error_activity_correlation_function_type(),
        )
    )
    t1 = _Model(
        frame=_frame(
            operation="explain_change",
            subject_constraints=["Resource"],
            output_shape="causal_evidence",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=None)

    outcome = _run(_service(t1, t2, manifest), utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.EXPLAIN_CHANGE
    assert outcome.frame.output_shape == "causal_evidence"
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_ambiguous_target_health_assessment_clarifies_without_broad_read() -> None:
    manifest, definition = _fixture(
        function_types=(
            resource_activity_function_type(),
            resource_current_state_function_type(),
            target_health_assessment_function_type(),
        )
    )
    t1 = _Model(
        frame=_frame(
            operation="validate",
            subject_constraints=["Resource"],
            measure_concepts=["health", "readiness"],
            output_shape="target_health_assessment",
            evidence_requirements=["application_health", "evidence_gaps"],
            unresolved_terms=["resource_identity"],
            clarification_requirements=["resource_identity"],
            clarification="Which exact resource name should I assess for health evidence?",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=None)

    outcome = _run(
        _service(t1, t2, manifest),
        utterance=(
            "Is api-example-primary or api-example-secondary healthy based on current "
            "readiness and application evidence?"
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.clarification == (
        "Which exact resource name should I assess for health evidence?"
    )
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_current_state_uses_verified_runtime_target_constraint() -> None:
    class _ReturningVerifier:
        def verify(self, plan: Any, *, manifest: object) -> Any:
            assert manifest is not None
            return plan

    manifest, _ = _fixture(function_types=(resource_current_state_function_type(),))
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource", "ca-fdai-dev-krc-core"],
            output_shape="target_current_state",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=None, plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_ReturningVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance=(
            "ca-fdai-dev-krc-core의 현재 활성 revision 이름과 ready 상태를 보여줘. "
            "각각의 관측 시각과 근거도 포함해."
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {
            "property": "id",
            "operator": "equals",
            "equals": "ca-fdai-dev-krc-core",
        }
    ]
    assert outcome.plan.nodes[1].arguments["function_name"] == (
        RESOURCE_CURRENT_STATE_FUNCTION_NAME
    )
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_current_state_does_not_complete_multiple_runtime_targets() -> None:
    manifest, definition = _fixture(function_types=(resource_current_state_function_type(),))
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            output_shape="target_current_state",
            unresolved_terms=["resource_identity"],
            clarification_requirements=["resource_identity"],
            clarification="Which exact resource name should I query?",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=None)

    outcome = _run(
        _service(t1, t2, manifest),
        utterance=(
            "Show the current revision and ready state for ca-example-one and ca-example-two."
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.plan is None
    assert outcome.clarification == "Which exact resource name should I query?"
    assert t1.frame_calls == 1


def test_current_state_without_exact_target_requests_korean_clarification() -> None:
    manifest, definition = _fixture(function_types=(resource_current_state_function_type(),))
    t1 = _Model(
        frame=_frame(
            operation="select",
            subject_constraints=["Resource"],
            output_shape="target_current_state",
            unresolved_terms=["resource_identity"],
            clarification_requirements=["resource_identity"],
            clarification="어떤 리소스의 정확한 이름을 조회할까요?",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=None)

    outcome = _run(
        _service(t1, t2, manifest),
        utterance="현재 core 앱의 revision과 ready 상태를 보여줘.",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.clarification == "어떤 리소스의 정확한 이름을 조회할까요?"
    assert outcome.plan is None
    assert outcome.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_resource_activity_clarification_accepts_typed_duration_target() -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.resource_change_activity",
            "targets": [
                {
                    "kind": "resource_type",
                    "value": "Container App",
                    "source_start": 0,
                    "source_end": 13,
                },
                {
                    "kind": "time_range",
                    "value": "30 minutes",
                    "source_start": 14,
                    "source_end": 24,
                    "canonical_value": "duration.PT30M",
                },
            ],
            "requested_facets": [
                "resource_change_activity",
                "revision",
                "restart",
                "configuration",
                "past_30_minutes",
            ],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
        }
    )

    result = build_resource_activity_clarification(
        judgment,
        utterance="Container App 30 minutes",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.output_shape == "target_activity"
    assert frame.temporal_scope == {"kind": "windowed"}


def test_resource_activity_clarification_accepts_event_history_facets() -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.resource_event_history",
            "targets": [
                {
                    "kind": "resource",
                    "value": "Container App",
                    "source_start": 0,
                    "source_end": 13,
                },
                {
                    "kind": "time_range",
                    "value": "30 minutes",
                    "source_start": 14,
                    "source_end": 24,
                    "canonical_value": "duration.PT30M",
                },
            ],
            "requested_facets": [
                "resource_event_history",
                "resource",
                "time_range",
                "event_type",
            ],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
        }
    )

    result = build_resource_event_history_clarification(
        judgment,
        utterance="Container App 30 minutes",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.output_shape == "resource_event_history"
    assert frame.temporal_scope == {"kind": "windowed"}


@pytest.mark.parametrize(
    "requested_facets",
    [
        (
            "configuration_drift",
            "evidence_supports_hypothesis",
            "evidence_refutes_hypothesis",
        ),
        (
            "drift_check_produces_finding",
            "drift_check_supported_by_evidence",
            "evidence_supports_hypothesis",
            "evidence_refutes_hypothesis",
        ),
    ],
)
def test_configuration_drift_without_exact_resource_requests_clarification(
    requested_facets: tuple[str, ...],
) -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.ontology_relationships",
            "targets": [],
            "requested_facets": list(requested_facets),
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
        }
    )

    result = build_configuration_drift_clarification(
        judgment,
        utterance="구성 드리프트 근거를 확인해 주세요.",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.operation is SemanticOperation.VALIDATE
    assert frame.subject_constraints == ("Resource",)


def test_ambiguous_resource_current_state_honors_typed_clarification() -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.resource_current_state",
            "targets": [
                {
                    "kind": "resource_type",
                    "value": "Container App",
                    "canonical_value": None,
                    "source_start": 0,
                    "source_end": 13,
                }
            ],
            "requested_facets": ["current_state"],
            "confidence": 0.95,
            "ambiguous": True,
            "alternatives": ["multiple_resources"],
            "unresolved_terms": ["Resource identity"],
            "clarification": "Which exact Container App name or resource ID should be checked?",
            "action_posture": "advise_only",
            "action_subject": "none",
        }
    )

    result = build_resource_current_state_clarification(
        judgment,
        utterance="Container App current state",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.output_shape == "target_current_state"
    assert frame.temporal_scope == {"kind": "current"}


def test_unresolved_relationship_current_state_gets_server_clarification() -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.ontology_relationships",
            "targets": [
                {
                    "kind": "object_type",
                    "value": "Resource",
                    "canonical_value": None,
                    "source_start": 0,
                    "source_end": 8,
                }
            ],
            "requested_facets": ["current_state"],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
        }
    )

    result = build_resource_current_state_clarification(
        judgment,
        utterance="Resource current state",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert proposal.clarification is not None
    assert frame.output_shape == "target_current_state"


def test_collected_rule_state_builds_exact_declaration_frame() -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.ontology_declaration",
            "targets": [],
            "requested_facets": [
                "rule_state",
                "collected_reference",
                "not_active_policy",
                "no_current_violation",
            ],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
        }
    )

    frame = build_rule_state_frame(
        judgment,
        utterance="Explain the collected Rule state.",
        context=(),
    )

    assert frame is not None
    assert frame.subject_constraints == ("Rule",)
    assert frame.measure_concepts == ("rule_state",)
    assert frame.output_shape == "ontology_declaration"


def test_service_current_health_without_exact_service_requests_clarification() -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.ontology_relationships",
            "targets": [],
            "requested_facets": [
                "business_services",
                "workloads",
                "resources",
                "current_state",
                "unknown_state",
                "partial_service_graph",
            ],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
        }
    )

    result = build_service_current_health_clarification(
        judgment,
        utterance="서비스의 현재 상태와 알 수 없는 상태를 구분해 주세요.",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.subject_constraints == ("BusinessService", "Resource", "Workload")
    assert frame.temporal_scope == {"kind": "current"}


@pytest.mark.parametrize(
    ("primary_intent", "facets"),
    [
        (
            "query.ontology_relationships",
            [
                "incident",
                "change",
                "approved_windows",
                "target_resources",
                "service_paths",
                "without_current_finding",
            ],
        ),
        (
            "query.ontology_relationships",
            [
                "incident",
                "approved_windows",
                "target_resources",
                "service_paths",
                "without_current_finding",
            ],
        ),
        (
            "query.resource_change_activity",
            [
                "changes",
                "approved_windows",
                "target_resources",
                "service_paths",
                "without_causal_inference",
            ],
        ),
        (
            "query.ontology_relationships",
            [
                "incident",
                "change_activity",
                "approved_windows",
                "target_resources",
                "service_paths",
                "without_current_finding",
            ],
        ),
    ],
)
def test_unbound_change_correlation_preserves_compare_windowed_hold(
    primary_intent: str,
    facets: list[str],
) -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": primary_intent,
            "targets": [],
            "requested_facets": facets,
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
        }
    )

    outcome = deterministic_pre_frame_outcome(
        judgment=judgment,
        utterance="Correlate the bound incident changes.",
        context=(),
        descriptors=(),
        manifest_digest=DIGEST,
        bound_incident=False,
    )

    assert outcome is not None
    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_change_correlation_incident_binding_unavailable"
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.COMPARE
    assert outcome.frame.subject_constraints == (
        "BusinessService",
        "Change",
        "ChangeWindow",
        "Resource",
        "Workload",
    )
    assert outcome.frame.temporal_scope == {"kind": "windowed"}


def test_unbound_change_correlation_accepts_only_reviewed_type_targets() -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.ontology_relationships",
            "targets": [
                {
                    "kind": "object_type",
                    "value": "changes",
                    "canonical_value": "Change",
                    "source_start": 10,
                    "source_end": 17,
                },
                {
                    "kind": "object_type",
                    "value": "incident",
                    "canonical_value": "Incident",
                    "source_start": 28,
                    "source_end": 36,
                },
                {
                    "kind": "object_type",
                    "value": "resources",
                    "canonical_value": "Resource",
                    "source_start": 48,
                    "source_end": 57,
                },
            ],
            "requested_facets": [
                "incident",
                "change",
                "approved_windows",
                "targets",
                "service_paths",
                "correlation",
                "without_current_finding",
            ],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
        }
    )

    frame = build_unbound_change_correlation_frame(
        judgment,
        bound_incident=False,
        utterance="Correlate changes for the incident with target resources.",
        context=(),
    )

    assert frame is not None
    assert frame.operation is SemanticOperation.COMPARE
    assert frame.temporal_scope == {"kind": "windowed"}


@pytest.mark.parametrize(
    ("bound_incident", "extra_facet", "missing_facets"),
    [
        (True, None, ()),
        (False, "configuration_drift", ()),
        (False, None, ("service_paths",)),
        (False, None, ("incident", "change")),
        (False, None, ("without_current_finding",)),
    ],
)
def test_change_correlation_hold_requires_unbound_bounded_typed_contract(
    bound_incident: bool,
    extra_facet: str | None,
    missing_facets: tuple[str, ...],
) -> None:
    facets = [
        "incident",
        "change",
        "approved_windows",
        "target_resources",
        "service_paths",
        "without_current_finding",
    ]
    if extra_facet is not None:
        facets.append(extra_facet)
    for missing_facet in missing_facets:
        facets.remove(missing_facet)
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.ontology_relationships",
            "targets": [],
            "requested_facets": facets,
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
        }
    )

    assert (
        build_unbound_change_correlation_frame(
            judgment,
            bound_incident=bound_incident,
            utterance="Correlate the bound incident changes.",
            context=(),
        )
        is None
    )


def test_current_revision_without_ready_cue_does_not_force_state_function() -> None:
    manifest, definition = _fixture(function_types=(resource_current_state_function_type(),))
    t1 = _Model(
        frame=_frame(subject_constraints=["Resource", "api-example"]),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=None)

    outcome = _run(
        _service(t1, t2, manifest),
        utterance="Show the current revision for api-example.",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert all(node.kind is not QueryNodeKind.FUNCTION for node in outcome.plan.nodes)
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_causal_current_revision_question_does_not_complete_state_frame() -> None:
    manifest, definition = _fixture(function_types=(resource_current_state_function_type(),))
    t1 = _Model(
        frame=_frame(
            operation="explain_change",
            subject_constraints=["Resource", "api-example"],
            output_shape="causal_evidence",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=None)

    outcome = _run(
        _service(t1, t2, manifest),
        utterance="Why is the current revision for api-example not ready?",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize("requirement", ("principal_scope", "purpose"))
def test_t1_server_bound_clarification_fails_closed_without_t2(requirement: str) -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            unresolved_terms=[requirement],
            clarification_requirements=[requirement],
            clarification="Which server context should I use?",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_unavailable_t1_frame_retries_only_frame_with_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=None, plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (1, 0)


async def test_unavailable_t1_and_t2_frames_terminate_as_typed_hold() -> None:
    manifest, _definition = _fixture()
    t1 = _Model(frame=None, plan=None)
    t2 = _Model(frame=None, plan=None)
    runtime = SemanticConversationRuntime(
        planner=_service(t1, t2, manifest),
        executor=object(),  # type: ignore[arg-type]
    )

    result = await runtime.handle(
        utterance="Show resources",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )

    assert result.disposition == "held"
    assert result.reason == "semantic_frame_unavailable"
    assert result.execution is None
    assert result.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (1, 0)


def test_unavailable_targetless_t1_frame_discovers_candidates_before_t2() -> None:
    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
    )
    t1 = _Model(frame=None, plan=None)
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(
        _service(
            t1,
            t2,
            manifest,
            inventory_query_language=_target_cardinality_language(),
        ),
        utterance="내 Container App에서 HTTP 500 오류가 발생하는 이유는 무엇이야?",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_target_candidates"
    assert outcome.plan is not None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)
    assert outcome.execution_authority is False


def test_resource_candidates_do_not_replace_non_resource_operating_subjects() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["BusinessService", "CostObjective"],
            unresolved_terms=["business_service_identity"],
            clarification_requirements=["subject"],
            clarification="Which business service should I inspect?",
        )
    )
    descriptors = (
        {
            "kind": "object",
            "name": "Resource",
            "properties": {
                "type": {
                    "value_groups": [
                        {
                            "terms": ["Container Apps"],
                            "values": ["compute.container-app"],
                        }
                    ]
                }
            },
        },
        {"kind": "object", "name": "BusinessService"},
        {"kind": "object", "name": "CostObjective"},
    )

    assert (
        resource_target_candidates_apply_to_proposal(
            proposal,
            utterance="Show the cost objective for a Container Apps business service.",
            descriptors=descriptors,
            inventory_query_language=_target_cardinality_language(),
        )
        is False
    )


def test_non_resource_operating_subject_returns_target_clarification() -> None:
    business_service = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    cost_objective = OntologyObjectType(
        schema_version="1.0.0",
        name="CostObjective",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, _definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        additional_object_types=(business_service, cost_objective),
    )
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["BusinessService", "CostObjective"],
            output_shape="ontology_relationships",
        )
    )

    resolved = build_non_resource_target_clarification(
        proposal,
        utterance="Show the cost objective for my Container App business service.",
        context=(),
        descriptors=manifest.descriptors,
        inventory_query_language=_target_cardinality_language(),
    )

    assert resolved is not None
    resolved_proposal, frame = resolved
    assert resolved_proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.subject_constraints == ("BusinessService", "CostObjective")
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "ontology_relationships"


def test_operating_mapping_frame_normalizes_to_current() -> None:
    business_capability = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessCapability",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    business_service = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, definition = _fixture(
        additional_object_types=(business_capability, business_service),
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["BusinessCapability", "BusinessService"],
            output_shape="ontology_relationships",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=None)

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("BusinessCapability", "BusinessService")
    assert outcome.frame.temporal_scope == {"kind": "current"}


@pytest.mark.parametrize(
    ("proposed_scope", "expected_scope"),
    [({}, {"kind": "current"}), ({"kind": "historical"}, {"kind": "historical"})],
)
def test_single_endpoint_relationship_uses_current_unless_scope_is_explicit(
    proposed_scope: dict[str, object],
    expected_scope: dict[str, object],
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["BusinessCapability"],
            temporal_scope=proposed_scope,
            output_shape="ontology_relationships",
        )
    )
    descriptors = (
        {"kind": "object", "name": "Resource"},
        {"kind": "object", "name": "BusinessCapability"},
    )

    _resolved_proposal, frame = normalize_operating_relationship_temporal_scope(
        proposal,
        build_semantic_frame(proposal, utterance="", context=()),
        utterance="",
        context=(),
        descriptors=descriptors,
    )

    assert frame.temporal_scope == expected_scope


@pytest.mark.parametrize(
    ("utterance", "clarification"),
    [
        (
            "Trace a decision through its action run to the observed outcome.",
            "Provide the exact DecisionCase name or ID?",
        ),
        (
            "의사 결정에서 작업 실행을 거쳐 관측된 결과까지 추적해 주세요.",
            "추적할 정확한 DecisionCase 이름 또는 ID를 알려주세요?",
        ),
    ],
)
def test_decision_outcome_relationship_restores_lineage_and_requests_target(
    utterance: str,
    clarification: str,
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["ActionRun", "Decision", "DecisionCase", "ObservedOutcome"],
            temporal_scope={"kind": "current"},
            output_shape="ontology_relationships",
        )
    )
    descriptors = tuple(
        {"kind": "object", "name": name}
        for name in (
            "Resource",
            "Decision",
            "DecisionCase",
            "ActionOption",
            "ActionRun",
            "ObservedOutcome",
        )
    )

    resolved, frame = normalize_decision_outcome_relationship(
        proposal,
        build_semantic_frame(proposal, utterance=utterance, context=()),
        utterance=utterance,
        context=(),
        descriptors=descriptors,
    )

    assert frame.subject_constraints == (
        "DecisionCase",
        "ActionOption",
        "ActionRun",
        "ObservedOutcome",
    )
    assert frame.temporal_scope == {"kind": "historical"}
    assert resolved.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert resolved.clarification == clarification


def test_decision_outcome_relationship_clarifies_before_plan_proposal() -> None:
    object_types = tuple(
        OntologyObjectType(
            schema_version="1.0.0",
            name=name,
            version="1.0.0",
            key="id",
            properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
        )
        for name in (
            "Decision",
            "DecisionCase",
            "ActionOption",
            "ActionRun",
            "ObservedOutcome",
        )
    )
    manifest, _definition = _fixture(additional_object_types=object_types)
    model = _Model(
        frame=_frame(
            subject_constraints=["ActionRun", "Decision", "DecisionCase", "ObservedOutcome"],
            temporal_scope={"kind": "current"},
            output_shape="ontology_relationships",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance=(
            "Trace a decision through its chosen option and action run to the observed outcome."
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == (
        "DecisionCase",
        "ActionOption",
        "ActionRun",
        "ObservedOutcome",
    )
    assert outcome.frame.temporal_scope == {"kind": "historical"}
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.plan_calls == 0


def test_operating_intent_clarification_restores_reviewed_service_endpoint() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["CostObjective"],
            output_shape="ontology_relationships",
        )
    )
    descriptors = (
        {
            "kind": "object",
            "name": "Resource",
            "properties": {
                "type": {
                    "value_groups": [
                        {
                            "terms": ["Container Apps"],
                            "values": ["compute.container-app"],
                        }
                    ]
                }
            },
        },
        {"kind": "object", "name": "BusinessService"},
        {"kind": "object", "name": "CostObjective"},
        {
            "kind": "link",
            "name": "service_has_cost_objective",
            "from_type": "BusinessService",
            "to_type": "CostObjective",
        },
    )

    resolved = build_non_resource_target_clarification(
        proposal,
        utterance="Container Apps 비용 목표를 보여 주세요.",
        context=(),
        descriptors=descriptors,
        inventory_query_language=_target_cardinality_language(),
    )

    assert resolved is not None
    _resolved_proposal, frame = resolved
    assert frame.subject_constraints == ("BusinessService", "CostObjective")
    assert frame.temporal_scope == {"kind": "current"}


def test_lone_business_service_restores_reviewed_objective_endpoint() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["BusinessService"],
            output_shape="ontology_relationships",
        )
    )
    descriptors = (
        {
            "kind": "object",
            "name": "Resource",
            "properties": {
                "type": {
                    "value_groups": [
                        {
                            "terms": ["Container Apps"],
                            "values": ["compute.container-app"],
                        }
                    ]
                }
            },
        },
        {"kind": "object", "name": "BusinessService"},
        {"kind": "object", "name": "CostObjective"},
        {
            "kind": "link",
            "name": "service_has_cost_objective",
            "from_type": "BusinessService",
            "to_type": "CostObjective",
        },
    )

    resolved = build_non_resource_target_clarification(
        proposal,
        utterance="Container Apps 비즈니스 서비스의 목표를 보여 주세요.",
        context=(),
        descriptors=descriptors,
        inventory_query_language=_target_cardinality_language(),
    )

    assert resolved is not None
    _resolved_proposal, frame = resolved
    assert frame.subject_constraints == ("BusinessService", "CostObjective")
    assert frame.temporal_scope == {"kind": "current"}


def test_invalid_non_resource_frame_recovers_to_target_clarification() -> None:
    business_service = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    cost_objective = OntologyObjectType(
        schema_version="1.0.0",
        name="CostObjective",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        additional_object_types=(business_service, cost_objective),
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            output_shape="resource_target_candidates",
            unresolved_terms=["resource_identity"],
            clarification_requirements=["resource_identity"],
            clarification="Which exact resource should I inspect?",
        ),
        plan=None,
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_OperatingSubjectJudgmentModel(),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        inventory_query_language=_target_cardinality_language(),
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance="Show the cost objective for my Container App business service.",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("BusinessService", "CostObjective")
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.frame.output_shape == "ontology_relationships"
    assert (t1.frame_calls, t2.frame_calls) == (1, 0)


def test_invalid_korean_objective_frame_preserves_manifest_subject() -> None:
    business_service = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    cost_objective = OntologyObjectType(
        schema_version="1.0.0",
        name="CostObjective",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        additional_object_types=(business_service, cost_objective),
        additional_link_types=(
            OntologyLinkType(
                schema_version="1.0.0",
                name="service_has_cost_objective",
                version="1.0.0",
                from_type="BusinessService",
                to_type="CostObjective",
                cardinality=LinkCardinality.MANY_TO_MANY,
            ),
        ),
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["CostObjective"],
            output_shape="ontology_declaration",
        ),
        plan=None,
    )
    t2 = _Model(frame=None, plan=_plan(definition))

    outcome = _run(
        _service(
            t1,
            t2,
            manifest,
            inventory_query_language=_target_cardinality_language(),
        ),
        utterance=("Container Apps 비즈니스 서비스의 검토된 비용 목표와 기간을 보여 주세요."),
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("BusinessService", "CostObjective")
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    "utterance",
    (
        (
            "Show the reviewed cost objective, target, and period for a Container Apps "
            "business service without presenting the objective as observed spend or "
            "realized savings."
        ),
        (
            "Container Apps 비즈니스 서비스의 검토된 비용 목표, 대상 값, 기간을 보여 주고 "
            "이를 관측된 지출이나 실현된 절감액으로 표현하지 마세요."
        ),
    ),
    ids=("en", "ko"),
)
def test_valid_broad_resource_frame_recovers_non_resource_target_clarification(
    utterance: str,
) -> None:
    business_service = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    cost_objective = OntologyObjectType(
        schema_version="1.0.0",
        name="CostObjective",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        additional_object_types=(business_service, cost_objective),
    )
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    t2 = _Model(frame=None, plan=None)
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_OperatingSubjectJudgmentModel(),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        inventory_query_language=_target_cardinality_language(),
        now=lambda: NOW,
    )

    outcome = _run(service, utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("BusinessService", "CostObjective")
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.frame.output_shape == "ontology_relationships"
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_unavailable_cost_objective_frame_recovers_target_clarification() -> None:
    business_service = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    cost_objective = OntologyObjectType(
        schema_version="1.0.0",
        name="CostObjective",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, _definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        additional_object_types=(business_service, cost_objective),
    )
    t1 = _Model(frame=None, plan=None)
    t2 = _Model(frame=None, plan=None)

    outcome = _run(
        _service(
            t1,
            t2,
            manifest,
            inventory_query_language=_target_cardinality_language(),
        ),
        utterance=("Show the reviewed cost objective for a Container Apps business service."),
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("BusinessService", "CostObjective")
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_partial_cost_objective_frame_recovers_target_clarification() -> None:
    business_service = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    cost_objective = OntologyObjectType(
        schema_version="1.0.0",
        name="CostObjective",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        additional_object_types=(business_service, cost_objective),
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["BusinessService", "target", "period"],
            output_shape="ontology_relationships",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=None)

    outcome = _run(
        _service(
            t1,
            t2,
            manifest,
            inventory_query_language=_target_cardinality_language(),
        ),
        utterance=("Show the reviewed cost objective for a Container Apps business service."),
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("BusinessService", "CostObjective")
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    "utterance",
    (
        "Show the cost objective for a Container Apps business service.",
        "Container Apps 비즈니스 서비스의 비용 목표를 보여 주세요.",
    ),
    ids=("en", "ko"),
)
def test_valid_non_resource_objective_frame_requires_exact_target(
    utterance: str,
) -> None:
    business_service = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    cost_objective = OntologyObjectType(
        schema_version="1.0.0",
        name="CostObjective",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        additional_object_types=(business_service, cost_objective),
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["BusinessService", "CostObjective"],
            output_shape="ontology_relationships",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=None, plan=None)

    outcome = _run(
        _service(
            t1,
            t2,
            manifest,
            inventory_query_language=_target_cardinality_language(),
        ),
        utterance=utterance,
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("BusinessService", "CostObjective")
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    "utterance",
    (
        "List all Container Apps business services and their cost objectives.",
        "모든 Container Apps 비즈니스 서비스와 비용 목표를 목록으로 보여 주세요.",
    ),
    ids=("en", "ko"),
)
def test_non_resource_collection_does_not_become_target_clarification(
    utterance: str,
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(subject_constraints=["BusinessService", "CostObjective"])
    )
    descriptors = (
        {"kind": "object", "name": "Resource"},
        {"kind": "object", "name": "BusinessService"},
        {"kind": "object", "name": "CostObjective"},
        {
            "kind": "property_value",
            "object_type": "Resource",
            "property": "type",
            "canonical_value": "compute.container-app",
            "query_terms": ["Container Apps"],
        },
    )

    assert (
        build_non_resource_target_clarification(
            proposal,
            utterance=utterance,
            context=(),
            descriptors=descriptors,
            inventory_query_language=_target_cardinality_language(),
        )
        is None
    )


@pytest.mark.parametrize(
    ("utterance", "query_term"),
    (
        (
            "Identify which declared business capabilities have reviewed service mappings.",
            "service",
        ),
        ("검토된 서비스 매핑이 있는 선언된 비즈니스 기능을 식별해 주세요.", "서비스"),
    ),
    ids=("en", "ko"),
)
def test_unknown_cardinality_non_resource_mapping_does_not_clarify(
    utterance: str,
    query_term: str,
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(subject_constraints=["BusinessCapability", "BusinessService"])
    )
    descriptors = (
        {"kind": "object", "name": "Resource"},
        {"kind": "object", "name": "BusinessCapability"},
        {"kind": "object", "name": "BusinessService"},
        {
            "kind": "property_value",
            "object_type": "Resource",
            "property": "type",
            "canonical_value": "compute.service",
            "query_terms": [query_term],
        },
    )

    assert (
        build_non_resource_target_clarification(
            proposal,
            utterance=utterance,
            context=(),
            descriptors=descriptors,
            inventory_query_language=_target_cardinality_language(),
        )
        is None
    )


def test_non_resource_objective_with_exact_identity_does_not_clarify() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(subject_constraints=["BusinessService", "CostObjective", "service-example-api"])
    )
    descriptors = (
        {"kind": "object", "name": "Resource"},
        {"kind": "object", "name": "BusinessService"},
        {"kind": "object", "name": "CostObjective"},
        {
            "kind": "property_value",
            "object_type": "Resource",
            "property": "type",
            "canonical_value": "compute.container-app",
            "query_terms": ["Container Apps"],
        },
    )

    assert (
        build_non_resource_target_clarification(
            proposal,
            utterance="Show the cost objective for service-example-api Container Apps service.",
            context=(),
            descriptors=descriptors,
            inventory_query_language=_target_cardinality_language(),
        )
        is None
    )


def test_judgment_subject_recovery_ignores_unbound_canonical_target() -> None:
    descriptors = (
        {"kind": "object", "name": "Resource"},
        {"kind": "object", "name": "BusinessService"},
    )
    judgment = {
        "targets": [
            {
                "kind": "object_type",
                "canonical_value": "CostObjective",
            }
        ]
    }

    assert _judgment_object_subjects(judgment, descriptors=descriptors) == ()


def test_judgment_subject_recovery_binds_exact_source_values() -> None:
    descriptors = (
        {"kind": "object", "name": "Resource"},
        {"kind": "object", "name": "BusinessService"},
        {"kind": "object", "name": "CostObjective"},
    )
    judgment = {
        "targets": [
            {"kind": "object_type", "value": "cost objective"},
            {"kind": "object_type", "value": "business service"},
        ]
    }

    assert _judgment_object_subjects(judgment, descriptors=descriptors) == (
        "BusinessService",
        "CostObjective",
    )


def test_judgment_subject_recovery_accepts_manifest_backed_canonical_targets() -> None:
    descriptors = (
        {"kind": "object", "name": "Resource"},
        {"kind": "object", "name": "BusinessService"},
        {"kind": "object", "name": "CostObjective"},
    )
    judgment = {
        "targets": [
            {
                "kind": "objective",
                "value": "cost objective",
                "canonical_value": "CostObjective",
            },
            {
                "kind": "service",
                "value": "business service",
                "canonical_value": "BusinessService",
            },
        ]
    }

    assert _judgment_object_subjects(judgment, descriptors=descriptors) == (
        "BusinessService",
        "CostObjective",
    )


def test_judgment_link_intent_recovers_manifest_endpoints() -> None:
    descriptors = (
        {"kind": "object", "name": "Resource"},
        {"kind": "object", "name": "BusinessService"},
        {"kind": "object", "name": "CostObjective"},
        {
            "kind": "link",
            "name": "service_has_cost_objective",
            "from_type": "BusinessService",
            "to_type": "CostObjective",
        },
    )

    assert _judgment_link_subjects(
        {"primary_intent": "query.service_has_cost_objective"},
        descriptors=descriptors,
        required_subjects=("BusinessService",),
    ) == ("BusinessService", "CostObjective")


def test_unrelated_judgment_link_intent_does_not_replace_object_subject() -> None:
    descriptors = (
        {"kind": "object", "name": "BusinessCapability"},
        {"kind": "object", "name": "BusinessService"},
        {"kind": "object", "name": "ServiceObjective"},
        {
            "kind": "link",
            "name": "service_has_service_objective",
            "from_type": "BusinessService",
            "to_type": "ServiceObjective",
        },
    )

    assert (
        _judgment_link_subjects(
            {"primary_intent": "query.service_has_service_objective"},
            descriptors=descriptors,
            required_subjects=("BusinessCapability",),
        )
        == ()
    )


def test_unavailable_targetless_collection_frame_does_not_reduce_to_candidates() -> None:
    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
    )
    t1 = _Model(frame=None, plan=None)
    t2 = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            measure_concepts=["cpu"],
            output_shape="property_filtered_resources",
        ),
        plan=_plan(definition),
    )

    outcome = _run(
        _service(
            t1,
            t2,
            manifest,
            inventory_query_language=_target_cardinality_language(),
        ),
        utterance="Show CPU telemetry for all Container Apps.",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "property_filtered_resources"
    assert outcome.plan is not None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert t2.frame_calls == 1
    assert outcome.execution_authority is False


def test_invalid_t1_plan_fails_closed_without_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan={"nodes": [], "output_node_ids": []})
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_list"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)
    assert t1.plan_evaluation_times == [NOW]
    assert t2.plan_evaluation_times == []


def _container_app_property_values() -> tuple[PropertyValueDomain, ...]:
    return (
        PropertyValueDomain(
            object_type="Resource",
            property_name="type",
            values=("compute.container-app",),
            groups=(
                PropertyValueGroup(
                    id="compute-container-app",
                    values=("compute.container-app",),
                    terms=("container app", "container apps"),
                ),
            ),
        ),
    )


def test_invalid_targetless_t1_plan_discovers_candidates_before_t2() -> None:
    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            measure_concepts=["ingress"],
            output_shape="property_filtered_resources",
            unresolved_terms=["resource_identity"],
            clarification_requirements=["resource_identity"],
            clarification="Which exact resource should I inspect?",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(
        _service(t1, t2, manifest),
        utterance="How is ingress configured for my Container App?",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_target_candidates"
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {
            "property": "type",
            "operator": "equals",
            "equals": "compute.container-app",
        }
    ]
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)
    assert outcome.execution_authority is False


def test_targetless_current_state_requests_exact_resource_clarification() -> None:
    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        function_types=(resource_current_state_function_type(),),
    )
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            measure_concepts=["provisioning_status", "running_status"],
            output_shape="target_current_state",
            unresolved_terms=["resource_identity"],
            clarification_requirements=["resource_identity"],
            clarification="Which exact resource should I inspect?",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(
        _service(t1, t2, manifest),
        utterance="Report a Container App's current provisioning and running states.",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "target_current_state"
    assert outcome.frame.temporal_scope == {}
    assert outcome.plan is None
    assert outcome.execution_authority is False


def test_current_state_judgment_recovery_preserves_current_candidate_scope() -> None:
    class _CurrentStateJudgmentModel:
        def judge(self, **_kwargs: Any) -> dict[str, object]:
            return {
                "primary_intent": "query.resource_current_state",
                "targets": [],
                "confidence": 0.95,
                "ambiguous": False,
                "action_posture": "advise_only",
                "execution_authority": False,
            }

    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
        function_types=(resource_current_state_function_type(),),
    )
    t1 = _Model(
        frame=_frame(
            operation="validate",
            subject_constraints=["Resource"],
            output_shape="target_current_state",
        ),
        plan={"nodes": [], "output_node_ids": []},
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_CurrentStateJudgmentModel(),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        semantic_judgment=judgment,
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance="Report a Container App's current provisioning and running states.",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "target_current_state"
    assert outcome.frame.temporal_scope == {}
    assert outcome.plan is None
    assert outcome.execution_authority is False


def test_invalid_targetless_investigation_discovers_candidates_before_t2() -> None:
    utterance = "Why is my Container App timing out?"

    def span(text: str) -> dict[str, object]:
        start = utterance.index(text)
        return {"start": start, "end": start + len(text), "text": text}

    manifest, definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
    )
    investigation = {
        "operation": "explain_change",
        "entities": [
            {
                "mention_id": "target",
                "span": span("Container App"),
                "role": "affected_target",
                "object_type_candidates": ["ContainerApp"],
            }
        ],
        "symptom_measures": [
            {
                "measure_id": "timeouts",
                "span": span("timing out"),
                "concept_id": "request.timeout",
                "target_mention_id": "target",
                "direction": "increase",
            }
        ],
        "primary_symptom_measure_id": "timeouts",
        "temporal_cues": [{"cue_id": "onset", "span": span("timing out"), "role": "onset"}],
        "relationship_intents": [
            {
                "relationship_id": "dependencies",
                "span": span("Why"),
                "source_mention_id": "target",
                "target_mention_id": None,
                "query_side_candidates": ["depends_on.outgoing"],
            }
        ],
        "hypotheses": [
            {
                "hypothesis_id": "dependency-latency",
                "span": span("Why"),
                "relationship_id": "dependencies",
                "cause_measure_concept": "dependency.latency",
                "effect_measure_id": "timeouts",
                "competing_explanations": ["resource-saturation"],
            },
            {
                "hypothesis_id": "resource-saturation",
                "span": span("Why"),
                "relationship_id": "dependencies",
                "cause_measure_concept": "resource.saturation",
                "effect_measure_id": "timeouts",
                "competing_explanations": ["dependency-latency"],
            },
        ],
        "evidence_standard": "support_and_refutation",
        "answer_shape": "diagnosis",
        "confidence": 0.9,
    }
    t1 = _Model(
        frame=_frame(
            operation="explain_change",
            subject_constraints=["Resource", "Container App"],
            measure_concepts=["request.timeout"],
            output_shape="causal_evidence",
            investigation=investigation,
        ),
        plan=None,
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest), utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_target_candidates"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (QueryNodeKind.OBJECT_SET,)
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)
    assert outcome.execution_authority is False


def test_mismatched_specialized_t1_plan_fails_closed_without_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(output_shape="resource_list"),
        plan=_function_plan("query.manifest", output_kind="query.table"),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_matching_specialized_t1_plan_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    manifest_plan = _function_plan("query.manifest", output_kind="query.table")
    t1 = _Model(frame=_frame(output_shape="ontology_manifest"), plan=manifest_plan)
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    "output_shape",
    ("inventory_impact", "ontology_release_evidence_health"),
)
def test_strict_v2_specialized_frames_reject_generic_substitutes(output_shape: str) -> None:
    manifest, definition = _fixture()
    generic_plan = _plan(definition)
    t1 = _Model(frame=_frame(output_shape=output_shape), plan=generic_plan)
    t2 = _Model(frame=_frame(), plan=generic_plan)

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    ("output_shape", "function_names"),
    (
        ("inventory_impact", ("query.inventory_impact",)),
        (
            "ontology_release_evidence_health",
            ("query.ontology_release_diff", "query.ontology_evidence_health"),
        ),
    ),
)
def test_strict_v2_specialized_frames_accept_exact_function_sets(
    output_shape: str,
    function_names: tuple[str, ...],
) -> None:
    function_types = {
        "query.inventory_impact": inventory_impact_function_type(),
        "query.ontology_evidence_health": ontology_evidence_health_function_type(),
        "query.ontology_release_diff": ontology_release_diff_function_type(),
    }
    manifest, definition = _fixture(
        function_types=tuple(function_types[name] for name in function_names)
    )
    t1 = _Model(frame=_frame(output_shape=output_shape), plan=_function_set_plan(*function_names))
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_exact_declaration_plan_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    declaration_plan = _function_plan(
        "query.ontology_declaration",
        output_kind="query.table",
        function_arguments={
            "kind": "object",
            "name": "Resource",
            "section": "detail",
            "limit": 100,
        },
    )
    t1 = _Model(
        frame=_frame(
            measure_concepts=["declaration_detail"],
            output_shape="ontology_declaration",
        ),
        plan=declaration_plan,
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_current_relationship_mapping_rejects_function_only_plan() -> None:
    manifest, _definition = _fixture()
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            temporal_scope={"kind": "current"},
            output_shape="ontology_relationships",
        ),
        plan=_function_plan(
            "query.ontology_relationships",
            output_kind="ontology.relationships",
            function_arguments={"object_types": ["Resource"], "limit": 100},
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "ontology_relationships"
    assert outcome.frame.temporal_scope == {"kind": "current"}


def test_current_relationship_mapping_preserves_endpoint_object_set() -> None:
    manifest, definition = _fixture()
    plan = _function_plan(
        "query.ontology_relationships",
        output_kind="ontology.relationships",
        function_arguments={"object_types": ["Resource"], "limit": 100},
    )
    plan["nodes"] = [*_plan(definition)["nodes"], *plan["nodes"]]  # type: ignore[misc]
    plan["output_node_ids"] = ["resources", "function-result"]
    t1 = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            temporal_scope={"kind": "current"},
            output_shape="ontology_relationships",
        ),
        plan=plan,
    )
    service = SemanticPlanningService(
        model=t1,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED


def test_current_relationship_mapping_holds_an_empty_endpoint() -> None:
    manifest, definition = _fixture()
    plan = _function_plan(
        "query.ontology_relationships",
        output_kind="ontology.relationships",
        function_arguments={"object_types": ["Resource"], "limit": 100},
    )
    plan["nodes"] = [*_plan(definition)["nodes"], *plan["nodes"]]  # type: ignore[misc]
    plan["output_node_ids"] = ["resources", "function-result"]
    service = SemanticPlanningService(
        model=_Model(
            frame=_frame(
                subject_constraints=["Resource"],
                temporal_scope={"kind": "current"},
                output_shape="ontology_relationships",
            ),
            plan=plan,
        ),
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )
    planning = _run(service)
    assert planning.plan is not None
    empty_execution = QueryPlanExecution(
        plan_digest=planning.plan.plan_digest,
        status="completed",
        results=MappingProxyType(
            {"resources": QueryNodeResult(value=QueryTable(rows=(), complete=True))}
        ),
        receipts=(),
        output_node_ids=planning.plan.output_node_ids,
    )
    populated_execution = QueryPlanExecution(
        plan_digest=planning.plan.plan_digest,
        status="completed",
        results=MappingProxyType(
            {
                "resources": QueryNodeResult(
                    value=QueryTable(
                        rows=(QueryRow.from_values("resource-a", {"id": "resource-a"}),),
                        complete=True,
                    )
                )
            }
        ),
        receipts=(),
        output_node_ids=planning.plan.output_node_ids,
    )

    assert _current_relationship_mapping_unavailable(planning, empty_execution) is True
    assert _current_relationship_mapping_unavailable(planning, populated_execution) is False


def test_incomplete_output_holds_only_contextual_resource_plans() -> None:
    manifest, definition = _fixture()
    service = SemanticPlanningService(
        model=_Model(frame=_frame(), plan=_plan(definition)),
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )
    planning = _run(service)
    assert planning.plan is not None
    assert planning.frame is not None
    execution = QueryPlanExecution(
        plan_digest=planning.plan.plan_digest,
        status="completed",
        results=MappingProxyType(
            {
                planning.plan.output_node_ids[0]: QueryNodeResult(
                    value=QueryTable(
                        rows=(),
                        complete=False,
                        truncation_reason="row_limit",
                    )
                )
            }
        ),
        receipts=(),
        output_node_ids=planning.plan.output_node_ids,
    )

    assert _query_output_incomplete(planning, execution) is False
    contextual_planning = replace(
        planning,
        frame=planning.frame.model_copy(
            update={"output_shape": SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST}
        ),
    )
    assert _query_output_incomplete(contextual_planning, execution) is True


def test_declaration_frame_without_exact_measure_fails_closed_without_t2() -> None:
    manifest, _definition = _fixture()
    declaration_plan = _function_plan(
        "query.ontology_declaration",
        output_kind="query.table",
        function_arguments={
            "kind": "object",
            "name": "Resource",
            "section": "detail",
            "limit": 100,
        },
    )
    t1 = _Model(frame=_frame(output_shape="ontology_declaration"), plan=declaration_plan)
    t2 = _Model(
        frame=_frame(
            measure_concepts=["declaration_detail"],
            output_shape="ontology_declaration",
        ),
        plan=declaration_plan,
    )
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_declaration_frame_with_non_select_operation_fails_closed_without_t2() -> None:
    manifest, _definition = _fixture()
    declaration_plan = _declaration_sections_plan("detail")
    t1 = _Model(
        frame=_frame(
            operation="action_draft",
            measure_concepts=["declaration_detail"],
            output_shape="ontology_declaration",
        ),
        plan=declaration_plan,
    )
    t2 = _Model(
        frame=_frame(
            measure_concepts=["declaration_detail"],
            output_shape="ontology_declaration",
        ),
        plan=declaration_plan,
    )
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_action_draft_frame_terminates_before_plan_without_t2() -> None:
    manifest, _definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="action_draft",
            subject_constraints=["Incident"],
            temporal_scope={"kind": "current"},
            output_shape="action_draft",
            evidence_requirements=["verified_incident_evidence"],
        ),
        plan=None,
    )
    t2 = _Model(frame=_frame(), plan=None)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.ACTION_DRAFT
    assert outcome.reason == "governed_action_draft_required"
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.ACTION_DRAFT
    assert outcome.frame.output_shape == "action_draft"
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    (
        "utterance",
        "source_value",
        "action_posture",
        "action_subject",
        "expected_disposition",
    ),
    [
        (
            "Draft a review-only incident mitigation proposal.",
            "Draft",
            "draft_only",
            "Incident",
            SemanticPlanningDisposition.ACTION_DRAFT,
        ),
        (
            "검토 전용 장애 완화 제안을 작성해 주세요.",
            "작성",
            "draft_only",
            "Incident",
            SemanticPlanningDisposition.ACTION_DRAFT,
        ),
        (
            "Show the review-only incident mitigation proposal.",
            "mitigation proposal",
            "advise_only",
            "none",
            SemanticPlanningDisposition.PLANNED,
        ),
        (
            "검토 전용 장애 완화 제안을 보여 주세요.",
            "완화 제안",
            "advise_only",
            "none",
            SemanticPlanningDisposition.PLANNED,
        ),
    ],
    ids=("draft-en", "draft-ko", "read-en", "read-ko"),
)
def test_bilingual_typed_action_posture_routes_without_keyword_rules(
    utterance: str,
    source_value: str,
    action_posture: str,
    action_subject: str,
    expected_disposition: SemanticPlanningDisposition,
) -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_LocalizedActionPostureJudgmentModel(
                source_value=source_value,
                action_posture=action_posture,
                action_subject=action_subject,
            ),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="incident-a",
            correlation_id="correlation-a",
        ),
    )

    assert outcome.disposition is expected_disposition
    assert outcome.frame is not None
    assert outcome.execution_authority is False
    assert outcome.frame.execution_authority is False
    if action_posture == "draft_only":
        assert outcome.frame.operation is SemanticOperation.ACTION_DRAFT
        assert outcome.frame.subject_constraints == ("Incident",)
        assert outcome.plan is None
        assert t1.plan_calls == 0
    else:
        assert outcome.frame.operation is SemanticOperation.SELECT
        assert outcome.frame.subject_constraints == ("Resource",)
        assert outcome.plan is not None
        assert outcome.plan.execution_authority is False
        assert t1.plan_calls == 1


def test_incident_action_draft_all_bilingual_wording_styles_remain_authority_free() -> None:
    corpus = load_golden_question_dataset(ROOT / "eval" / "golden-dataset")
    cases = tuple(
        case
        for case in corpus.cases
        if case.semantic_pair_id.rpartition(".")[0] == "action-incident-mitigation-draft"
    )

    assert len(cases) == 16
    assert {case.locale for case in cases} == {"en", "ko"}
    assert len({case.variation_kind for case in cases}) == 8

    manifest, definition = _fixture()
    for case in cases:
        assert case.runtime_context == "incident_binding"
        assert case.expected_frame.operation == "action_draft"
        t1 = _Model(frame=_frame(), plan=_plan(definition))
        judgment = SemanticJudgmentBoundary(
            profile_id="semantic-planning.test",
            profile_version="1.0.0",
            primary=SemanticJudgmentBinding(
                tier=SemanticJudgmentTier.T1,
                model=_IncidentDraftJudgmentModel(),
                model_config_digest=DIGEST,
                prompt_digest=DIGEST,
            ),
        )
        outcome = SemanticPlanningService(
            model=t1,
            semantic_judgment=judgment,
            manifests=_ManifestProvider(manifest),
            verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
            now=lambda: NOW,
        ).plan(
            utterance=case.question,
            prior_turns=(),
            principal=Principal(id="operator", role=Role.READER),
            purpose="operations-review",
            bound_incident=BoundIncident(
                incident_id="incident-a",
                correlation_id="correlation-a",
            ),
        )

        assert outcome.disposition is SemanticPlanningDisposition.ACTION_DRAFT, case.case_id
        assert outcome.frame is not None
        assert outcome.frame.operation is SemanticOperation.ACTION_DRAFT
        assert outcome.frame.subject_constraints == ("Incident",)
        assert outcome.frame.execution_authority is False
        assert outcome.execution_authority is False
        assert outcome.plan is None
        assert t1.plan_calls == 0


def test_bound_incident_supplies_missing_action_draft_subject() -> None:
    manifest, _definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="action_draft",
            subject_constraints=["review-only request"],
            temporal_scope={"kind": "current"},
            output_shape="action_draft",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=t1,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Draft a review-only mitigation proposal.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="incident-a",
            correlation_id="correlation-a",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.ACTION_DRAFT
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Incident", "review-only request")
    assert t1.plan_calls == 0


def test_empty_unbound_action_draft_defaults_to_action_type_subject() -> None:
    manifest, _definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="action_draft",
            subject_constraints=[],
            output_shape="action_draft",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=t1,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.ACTION_DRAFT
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("ActionType",)
    assert outcome.frame.temporal_scope == {}
    assert t1.plan_calls == 0


def test_low_confidence_draft_posture_can_only_lower_to_action_draft() -> None:
    manifest, _definition = _fixture()
    t1 = _Model(frame=_frame(), plan=None)
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_LowConfidenceDraftJudgmentModel(),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Draft a review-only incident mitigation proposal.")

    assert outcome.disposition is SemanticPlanningDisposition.ACTION_DRAFT
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Change",)
    assert outcome.execution_authority is False


def test_low_confidence_advise_posture_does_not_replace_candidate_frame() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    judgment_model = _OperatingSubjectJudgmentModel()
    original_judge = judgment_model.judge

    def low_confidence_judge(**kwargs: Any) -> dict[str, object]:
        proposal = original_judge(**kwargs)
        proposal["confidence"] = 0.5
        return proposal

    judgment_model.judge = low_confidence_judge  # type: ignore[method-assign]
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=judgment_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Show the cost objective for a business service.")

    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Resource",)
    assert outcome.frame.output_shape == "resource_list"
    assert outcome.execution_authority is False


def test_t1_draft_judgment_is_forwarded_to_frame_planning() -> None:
    manifest, _definition = _fixture()
    t1 = _JudgmentAwareModel(
        frame=_frame(
            operation="action_draft",
            subject_constraints=["ActionType"],
            output_shape="action_draft",
        ),
        plan=None,
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_DraftJudgmentModel(),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Draft a rollback proposal")

    assert outcome.disposition is SemanticPlanningDisposition.ACTION_DRAFT
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Change",)
    assert outcome.frame.temporal_scope == {"kind": "historical"}
    assert t1.plan_calls == 0


def test_typed_draft_judgment_canonicalizes_mismatched_candidate_frame() -> None:
    manifest, _definition = _fixture()
    t1 = _Model(frame=_frame(), plan=None)
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_DraftJudgmentModel(),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Draft a rollback proposal")

    assert outcome.disposition is SemanticPlanningDisposition.ACTION_DRAFT
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.ACTION_DRAFT
    assert outcome.frame.subject_constraints == ("Change",)
    assert outcome.frame.temporal_scope == {"kind": "historical"}
    assert outcome.frame.output_shape == "action_draft"
    assert outcome.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)


def test_draft_judgment_preserves_verified_frame_artifact_subject() -> None:
    manifest, _definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="action_draft",
            subject_constraints=["Rule", "remediate.restrict-network-access"],
            output_shape="action_draft",
        ),
        plan=None,
    )
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_ActionTypeOnlyDraftJudgmentModel(),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance="Draft remediate.restrict-network-access from the active Rule",
    )

    assert outcome.disposition is SemanticPlanningDisposition.ACTION_DRAFT
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == (
        "Rule",
        "remediate.restrict-network-access",
    )
    assert outcome.frame.temporal_scope == {}


def test_incomplete_action_draft_does_not_invent_action_type_subject() -> None:
    manifest, _definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="action_draft",
            subject_constraints=["PostgreSQL Flexible Server"],
            unresolved_terms=["resource_identity"],
            clarification_requirements=["resource_identity"],
            output_shape="action_draft",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=t1,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("PostgreSQL Flexible Server",)
    assert t1.plan_calls == 0


@pytest.mark.parametrize(
    ("subject_constraints", "proposed_scope", "expected_scope"),
    [
        (("ActionType",), {"kind": "current"}, {}),
        (("Change",), {"kind": "current"}, {"kind": "historical"}),
        (("Incident",), {}, {"kind": "current"}),
        (("RecoveryPlan",), {}, {"kind": "current"}),
        (("Rule", "remediate.restrict-network-access"), {"kind": "current"}, {}),
    ],
)
def test_action_draft_derives_temporal_scope_from_subject_type(
    subject_constraints: tuple[str, ...],
    proposed_scope: dict[str, str],
    expected_scope: dict[str, str],
) -> None:
    manifest, _definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="action_draft",
            subject_constraints=list(subject_constraints),
            temporal_scope=proposed_scope,
            output_shape="action_draft",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=t1,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.ACTION_DRAFT
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == subject_constraints
    assert outcome.frame.temporal_scope == expected_scope
    assert t1.plan_calls == 0


def test_all_requested_declaration_sections_must_be_outputs() -> None:
    manifest, _definition = _fixture()
    incomplete = _declaration_sections_plan("detail", "dependents")
    incomplete["output_node_ids"] = ["detail"]
    complete = _declaration_sections_plan("detail", "dependents")
    frame = _frame(
        measure_concepts=["declaration_detail", "declaration_dependents"],
        output_shape="ontology_declaration",
    )
    t1 = _Model(frame=frame, plan=incomplete)
    t2 = _Model(frame=_frame(), plan=complete)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_declaration_plan_rejects_hidden_unrelated_nodes() -> None:
    manifest, definition = _fixture()
    hidden = _declaration_sections_plan("detail")
    hidden["nodes"] = [*hidden["nodes"], *_plan(definition)["nodes"]]  # type: ignore[misc]
    complete = _declaration_sections_plan("detail")
    frame = _frame(
        measure_concepts=["declaration_detail"],
        output_shape="ontology_declaration",
    )
    t1 = _Model(frame=frame, plan=hidden)
    t2 = _Model(frame=_frame(), plan=complete)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_declaration_plan_rejects_spoofed_output_kind() -> None:
    manifest, _definition = _fixture()
    spoofed = _declaration_sections_plan("detail")
    spoofed["nodes"][0]["output_kind"] = "topology.graph"  # type: ignore[index]
    complete = _declaration_sections_plan("detail")
    frame = _frame(
        measure_concepts=["declaration_detail"],
        output_shape="ontology_declaration",
    )
    t1 = _Model(frame=frame, plan=spoofed)
    t2 = _Model(frame=_frame(), plan=complete)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_manifest_cannot_satisfy_exact_declaration_frame() -> None:
    manifest, _definition = _fixture()
    exact_plan = _function_plan(
        "query.ontology_declaration",
        output_kind="query.table",
        function_arguments={
            "kind": "object",
            "name": "Resource",
            "section": "detail",
            "limit": 100,
        },
    )
    t1 = _Model(
        frame=_frame(
            measure_concepts=["declaration_detail"],
            output_shape="ontology_declaration",
        ),
        plan=_function_plan("query.manifest", output_kind="query.table"),
    )
    t2 = _Model(frame=_frame(), plan=exact_plan)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_object_set_cannot_satisfy_exact_declaration_frame() -> None:
    manifest, definition = _fixture()
    exact_plan = _function_plan(
        "query.ontology_declaration",
        output_kind="query.table",
        function_arguments={
            "kind": "object",
            "name": "Resource",
            "section": "detail",
            "limit": 100,
        },
    )
    t1 = _Model(
        frame=_frame(
            measure_concepts=["declaration_detail"],
            output_shape="ontology_declaration",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=_frame(), plan=exact_plan)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_exact_rule_declaration_plan_never_invokes_t2() -> None:
    manifest, definition = _fixture(include_rule=True)
    declaration_plan = _function_plan(
        "query.ontology_declaration",
        output_kind="query.table",
        function_arguments={
            "kind": "object",
            "name": "Rule",
            "section": "detail",
            "limit": 100,
        },
    )
    t1 = _Model(
        frame=_frame(
            measure_concepts=["rule_state"],
            subject_constraints=["Rule"],
            output_shape="ontology_declaration",
        ),
        plan=declaration_plan,
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_declaration_plan_name_must_match_exact_frame_subject() -> None:
    manifest, _definition = _fixture()
    mismatched = _function_plan(
        "query.ontology_declaration",
        output_kind="query.table",
        function_arguments={
            "kind": "object",
            "name": "Rule",
            "section": "detail",
            "limit": 100,
        },
    )
    matching = _function_plan(
        "query.ontology_declaration",
        output_kind="query.table",
        function_arguments={
            "kind": "object",
            "name": "Resource",
            "section": "detail",
            "limit": 100,
        },
    )
    t1 = _Model(
        frame=_frame(
            measure_concepts=["declaration_detail"],
            output_shape="ontology_declaration",
        ),
        plan=mismatched,
    )
    t2 = _Model(frame=_frame(), plan=matching)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    ("field", "value"),
    (("section", "dependents"), ("kind", "link")),
)
def test_declaration_plan_axes_must_match_exact_frame_and_manifest(
    field: str,
    value: str,
) -> None:
    manifest, _definition = _fixture()
    mismatched_arguments: dict[str, object] = {
        "kind": "object",
        "name": "Resource",
        "section": "detail",
        "limit": 100,
    }
    mismatched_arguments[field] = value
    t1 = _Model(
        frame=_frame(
            measure_concepts=["declaration_detail"],
            output_shape="ontology_declaration",
        ),
        plan=_function_plan(
            "query.ontology_declaration",
            output_kind="query.table",
            function_arguments=mismatched_arguments,
        ),
    )
    t2 = _Model(
        frame=_frame(),
        plan=_function_plan(
            "query.ontology_declaration",
            output_kind="query.table",
            function_arguments={
                "kind": "object",
                "name": "Resource",
                "section": "detail",
                "limit": 100,
            },
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_named_instance_question_never_settles_for_a_schema_frame() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(output_shape="ontology_manifest"),
        plan=_function_plan("query.manifest", output_kind="query.table"),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance=_NAMED_INSTANCE_UTTERANCE)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert outcome.plan is None
    assert (t1.frame_calls, t2.frame_calls) == (1, 0)
    assert (t1.plan_calls, t2.plan_calls) == (0, 0)


def test_named_instance_question_is_unsupported_when_both_tiers_answer_the_schema() -> None:
    manifest, _definition = _fixture()
    manifest_frame = _frame(output_shape="ontology_manifest")
    manifest_plan = _function_plan("query.manifest", output_kind="query.table")
    t1 = _Model(frame=manifest_frame, plan=manifest_plan)
    t2 = _Model(frame=manifest_frame, plan=manifest_plan)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance=_NAMED_INSTANCE_UTTERANCE)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_declared_vocabulary_keeps_a_hyphenated_schema_question_answerable() -> None:
    manifest, definition = _fixture(
        property_values=(
            PropertyValueDomain(
                object_type="Resource",
                property_name="id",
                values=("app-service-plan", "kubernetes-node-pool"),
                groups=(
                    PropertyValueGroup(
                        id="compute",
                        values=("app-service-plan",),
                        terms=("virtual-network-gateway",),
                    ),
                ),
            ),
        )
    )
    manifest_plan = _function_plan("query.manifest", output_kind="query.table")
    t1 = _Model(frame=_frame(output_shape="ontology_manifest"), plan=manifest_plan)
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance="app-service-plan and virtual-network-gateway declarations, please",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_incident_function_cannot_satisfy_resource_frame() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(output_shape="resource_list"),
        plan=_function_plan("query.incident_evidence", output_kind="incident.evidence"),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def _incident_evidence_plan(*, incident_id: str, correlation_id: str) -> dict[str, object]:
    plan = _function_plan("query.incident_evidence", output_kind="incident.evidence")
    node = plan["nodes"][0]  # type: ignore[index]
    node["arguments"]["arguments"] = {
        "incident_id": incident_id,
        "correlation_id": correlation_id,
        "limit": 50,
    }
    return plan


def _incident_service(plan: dict[str, object], manifest: Any) -> SemanticPlanningService:
    return SemanticPlanningService(
        model=_Model(frame=_frame(output_shape="incident_evidence"), plan=plan),
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )


def _incident_arguments(outcome: Any) -> dict[str, Any]:
    assert outcome.plan is not None
    return dict(outcome.plan.nodes[0].arguments["arguments"])


def test_anchored_conversation_never_retargets_a_read_of_another_incident() -> None:
    """Retargeting would answer about one incident while the operator asked about another."""
    manifest, _ = _fixture()
    service = _incident_service(
        _incident_evidence_plan(
            incident_id="00000000-0000-0000-0000-000000000701",
            correlation_id="another-incident",
        ),
        manifest,
    )

    outcome = service.plan(
        utterance="Report what the evidence for incident 0701 establishes.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    arguments = _incident_arguments(outcome)
    assert arguments["incident_id"] == "00000000-0000-0000-0000-000000000701"
    assert arguments["correlation_id"] == "another-incident"


def _anchored_fixture() -> Any:
    """One manifest that actually offers the incident-evidence capability."""
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    function = incident_evidence_function_type()
    release = build_ontology_release(object_types=(resource,), function_types=(function,))
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
        functions=(function,),
    )


def _anchored_service(manifest: Any, plan: dict[str, object] | None) -> tuple[Any, Any]:
    model = _Model(frame=_frame(output_shape="incident_evidence"), plan=plan)
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )
    return service, model


def test_anchored_incident_read_is_built_from_the_binding_without_a_plan_proposal() -> None:
    manifest = _anchored_fixture()
    service, model = _anchored_service(manifest, None)

    outcome = service.plan(
        utterance="Report what the evidence for this incident establishes.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.plan_calls == 0
    assert outcome.plan is not None
    node = outcome.plan.nodes[0]
    assert node.arguments["function_name"] == "query.incident_evidence"
    assert node.arguments["arguments"] == {
        "incident_id": "00000000-0000-0000-0000-000000000702",
        "correlation_id": "bound-incident",
        "limit": INCIDENT_EVIDENCE_MAX_RECORDS,
    }
    assert outcome.execution_authority is False


def test_bound_incident_historical_comparison_holds_without_recurrence_capability() -> None:
    manifest = _anchored_fixture()
    model = _Model(
        frame=_frame(
            operation="compare",
            subject_constraints=["Incident"],
            temporal_scope={"kind": "historical"},
            output_shape="incident_evidence",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Compare this incident with retained evidence for recurrence.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_incident_recurrence_comparison_unavailable"
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.COMPARE
    assert outcome.frame.subject_constraints == ("Incident",)
    assert outcome.frame.temporal_scope == {"kind": "historical"}
    assert outcome.plan is None
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    "primary_intent",
    ["query.incident_evidence", "query.resource_error_activity_correlation"],
)
def test_judgment_recurrence_restores_bound_historical_frame(primary_intent: str) -> None:
    utterance = "Compare retained incident evidence for recurrence."
    proposal = SemanticFrameProposal.model_validate(_frame())
    judgment = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": ["compare", "recurrence_supported"],
            "targets": [],
        }
    )
    typed_judgment = SemanticJudgmentProposal.model_validate(judgment)

    resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance=utterance, context=()),
        judgment=typed_judgment,
        bound_incident=True,
        utterance=utterance,
        context=(),
    )

    assert resolved.operation is SemanticOperation.COMPARE
    assert frame.subject_constraints == ("Incident",)
    assert frame.temporal_scope == {"kind": "historical"}
    assert frame.output_shape == "incident_evidence"


@pytest.mark.parametrize(
    "requested_facets",
    [
        ["approved_windows", "correlation", "temporal_order_not_cause"],
        ["approved_windows", "target_resources", "temporal_order_not_causation"],
        ["approved_windows", "target_resources", "correlation", "changes_recorded"],
        ["approved_windows", "target_resources", "correlation_without_causation"],
        ["approved_windows", "without_treating_temporal_order_as_proof_of_cause"],
        ["approved_windows", "target_resources", "service_paths", "no_causal_inference"],
        ["approved_time_window", "target_resource", "service_path", "change_activity"],
        ["approved_time_window", "target_resource", "service_path", "related_changes"],
        ["approved_time_window", "target_resource", "service_path", "linked_incident"],
    ],
)
def test_judgment_change_correlation_restores_windowed_frame(
    requested_facets: list[str],
) -> None:
    utterance = "Correlate incident changes without treating temporal order as cause."
    proposal = SemanticFrameProposal.model_validate(_frame())
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_change_activity",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )
    judgment = SemanticJudgmentProposal.model_validate(judgment_data)

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance=utterance, context=()),
        judgment=judgment,
        bound_incident=True,
        utterance=utterance,
        context=(),
    )

    assert frame.operation is SemanticOperation.COMPARE
    assert frame.subject_constraints == ("Change",)
    assert frame.temporal_scope == {"kind": "windowed"}
    assert frame.output_shape == "temporal_comparison"


def test_general_incident_relationship_judgment_does_not_become_change_comparison() -> None:
    utterance = "Show the incident relationship evidence."
    proposal = SemanticFrameProposal.model_validate(
        _frame(subject_constraints=["Incident"], output_shape="ontology_relationships")
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.ontology_relationships",
            "requested_facets": ["approved_windows", "no_causal_inference"],
            "targets": [],
        }
    )
    judgment = SemanticJudgmentProposal.model_validate(judgment_data)

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance=utterance, context=()),
        judgment=judgment,
        bound_incident=True,
        utterance=utterance,
        context=(),
    )

    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("Incident",)
    assert frame.temporal_scope == {}
    assert frame.output_shape == "ontology_relationships"


def test_windowed_change_activity_without_change_or_incident_facet_stays_select() -> None:
    utterance = "Show resource activity in the approved window."
    proposal = SemanticFrameProposal.model_validate(
        _frame(subject_constraints=["Change"], output_shape="ontology_relationships")
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_change_activity",
            "requested_facets": ["approved_time_window", "target_resource"],
            "targets": [],
        }
    )
    judgment = SemanticJudgmentProposal.model_validate(judgment_data)

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance=utterance, context=()),
        judgment=judgment,
        bound_incident=True,
        utterance=utterance,
        context=(),
    )

    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("Change",)
    assert frame.output_shape == "ontology_relationships"


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets"),
    [
        (
            "query.resource_change_activity",
            ["completed_change", "recovery_outcomes", "regression_outcomes"],
        ),
        (
            "query.resource_event_history",
            ["completed_change", "unresolved_outcome", "observed_results"],
        ),
        (
            "query.incident_evidence",
            [
                "completed_change",
                "recovery",
                "regression",
                "unresolved_result",
                "independently_observed",
            ],
        ),
    ],
)
def test_completed_change_outcome_restores_historical_relationship_frame(
    primary_intent: str,
    requested_facets: list[str],
) -> None:
    utterance = "Inspect the completed change outcome."
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["Change", "Incident"],
            output_shape="ontology_relationships",
        )
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance=utterance, context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=True,
        utterance=utterance,
        context=(),
    )

    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("Change",)
    assert is_completed_change_outcome_frame(frame)
    assert "change_outcome_relationship" not in frame.measure_concepts
    assert frame.temporal_scope == {"kind": "historical"}
    assert frame.output_shape == "ontology_relationships"


def test_recurrence_precedes_completed_change_outcome_for_incident_evidence() -> None:
    utterance = "Compare recurrence evidence after the completed change."
    proposal = SemanticFrameProposal.model_validate(
        _frame(subject_constraints=["Incident"], output_shape="ontology_relationships")
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.incident_evidence",
            "requested_facets": [
                "recurrence",
                "completed_change",
                "recovery",
                "regression",
            ],
            "targets": [],
        }
    )

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance=utterance, context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=True,
        utterance=utterance,
        context=(),
    )

    assert frame.operation is SemanticOperation.COMPARE
    assert frame.subject_constraints == ("Incident",)
    assert frame.temporal_scope == {"kind": "historical"}
    assert frame.output_shape == "incident_evidence"


@pytest.mark.parametrize(
    "requested_facets",
    [["completed_change", "incident_linkage"], ["recovery_outcomes", "regression_outcomes"]],
)
def test_incomplete_change_outcome_facets_do_not_restore_historical_frame(
    requested_facets: list[str],
) -> None:
    utterance = "Inspect the change relationship."
    proposal = SemanticFrameProposal.model_validate(
        _frame(subject_constraints=["Change"], output_shape="ontology_relationships")
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_change_activity",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance=utterance, context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=True,
        utterance=utterance,
        context=(),
    )

    assert frame.temporal_scope == {}


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets"),
    [
        (
            "query.resource_change_activity",
            ["completed_change", "not_recovery_needed"],
        ),
        (
            "query.resource_change_activity",
            ["determine_recurrence_supported"],
        ),
    ],
)
def test_negated_outcome_or_wrong_intent_recurrence_stays_select(
    primary_intent: str,
    requested_facets: list[str],
) -> None:
    utterance = "Inspect the change relationship."
    proposal = SemanticFrameProposal.model_validate(
        _frame(subject_constraints=["Change"], output_shape="ontology_relationships")
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance=utterance, context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=True,
        utterance=utterance,
        context=(),
    )

    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("Change",)
    assert frame.temporal_scope == {}
    assert frame.output_shape == "ontology_relationships"


def test_change_outcome_frame_holds_before_unverified_plan_execution() -> None:
    change = OntologyObjectType(
        schema_version="1.0.0",
        name="Change",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, _definition = _fixture(additional_object_types=(change,))
    model = _Model(
        frame=_frame(
            subject_constraints=["Change"],
            measure_concepts=["completed_change", "recovery_outcomes"],
            temporal_scope={"kind": "historical"},
            output_shape="ontology_relationships",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Inspect the completed change outcome.")

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_change_outcome_unavailable"
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets"),
    [
        (
            "query.resource_change_activity",
            [
                "configuration_drift",
                "separate_evidence",
                "supports_each_causal_hypothesis",
                "refutes_each_causal_hypothesis",
            ],
        ),
        (
            "query.resource_error_activity_correlation",
            [
                "configuration_drift",
                "evidence_supporting_hypotheses",
                "evidence_refuting_hypotheses",
            ],
        ),
        (
            "query.resource_event_history",
            [
                "drift_presence",
                "evidence_supports_hypothesis",
                "evidence_refutes_hypothesis",
                "causal_hypotheses",
            ],
        ),
    ],
)
def test_configuration_drift_judgment_restores_resource_validation_frame(
    primary_intent: str,
    requested_facets: list[str],
) -> None:
    utterance = "Validate configuration drift evidence for the target resource."
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["CausalHypothesis", "EvidenceArtifact"],
            measure_concepts=["configuration_drift"],
            output_shape="ontology_relationships",
        )
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance=utterance, context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=False,
        utterance=utterance,
        context=(),
    )

    assert is_configuration_drift_evidence_frame(frame)
    assert frame.operation is SemanticOperation.VALIDATE
    assert frame.subject_constraints == ("Resource",)
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "evidence_validation"


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets"),
    [
        (
            "query.target_health_assessment",
            [
                "stale_relationships",
                "incomplete_relationships",
                "conflicting_relationships",
                "service_to_resource_relationships",
                "health_conclusion",
            ],
        ),
        (
            "query.target_health_assessment",
            [
                "status_conclusion_support",
                "service_resource_relationship",
                "staleness",
                "incompleteness",
                "conflict",
            ],
        ),
        (
            "query.resource_state_inventory",
            [
                "service",
                "resource",
                "relationship",
                "stale",
                "incomplete",
                "conflicting",
                "state_conclusion",
            ],
        ),
        (
            "query.target_health_assessment",
            [
                "status_conclusion",
                "supporting_evidence",
                "service_resource_relation",
                "authorization_scope",
            ],
        ),
    ],
)
def test_service_relationship_evidence_gap_restores_validation_frame(
    primary_intent: str,
    requested_facets: list[str],
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["Resource"],
            temporal_scope={"kind": "current"},
            output_shape="evidence_validation",
        )
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance="", context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=False,
        utterance="",
        context=(),
    )

    assert frame.operation is SemanticOperation.VALIDATE
    assert frame.subject_constraints == ("BusinessService", "Workload", "Resource")
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "evidence_validation"


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets"),
    [
        (
            "query.target_health_assessment",
            [
                "freshness",
                "completeness",
                "conflicts",
                "revisions",
                "evidence",
                "scope",
                "authorized_scope",
                "healthy_result",
            ],
        ),
        (
            "query.resource_health_inventory",
            [
                "freshness",
                "completeness",
                "conflicts",
                "revisions",
                "network_resource_evidence",
                "compute_resource_evidence",
                "authorized_scope",
                "avoid_healthy_result_inference",
            ],
        ),
    ],
)
def test_resource_evidence_health_restores_current_validation_frame(
    primary_intent: str,
    requested_facets: list[str],
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["BusinessService"],
            temporal_scope={"kind": "historical"},
            output_shape="ontology_relationships",
        )
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance="", context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=False,
        utterance="",
        context=(),
    )

    assert frame.operation is SemanticOperation.VALIDATE
    assert frame.subject_constraints == ("Resource",)
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "evidence_validation"
    assert frame.execution_authority is False


@pytest.mark.parametrize(
    "requested_facets",
    [
        ["service_resource_relationship"],
        ["staleness", "incompleteness", "conflict"],
    ],
)
def test_incomplete_service_relationship_evidence_gap_does_not_normalize(
    requested_facets: list[str],
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["Resource"],
            temporal_scope={"kind": "current"},
            output_shape="evidence_validation",
        )
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.target_health_assessment",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance="", context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=False,
        utterance="",
        context=(),
    )

    assert frame.subject_constraints == ("Resource",)


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets"),
    [
        (
            "query.incident_evidence",
            [
                "verified_symptoms",
                "affected_scope",
                "competing_hypotheses",
                "next_safe_diagnostic_step",
            ],
        ),
        (
            "query.target_health_assessment",
            [
                "validated_symptom",
                "impact_scope",
                "competing_hypotheses",
                "safest_next_diagnostic_step",
            ],
        ),
    ],
)
def test_bound_incident_triage_restores_current_validation_frame(
    primary_intent: str,
    requested_facets: list[str],
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["Conversation", "Incident"],
            temporal_scope={"kind": "current"},
            output_shape="ontology_relationships",
        )
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance="", context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=True,
        utterance="",
        context=(),
    )

    assert is_incident_triage_frame(frame)


def test_bound_incident_triage_holds_before_generic_incident_read() -> None:
    incident = OntologyObjectType(
        schema_version="1.0.0",
        name="Incident",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    function = incident_evidence_function_type()
    release = build_ontology_release(
        object_types=(incident,),
        function_types=(function,),
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(incident,),
        functions=(function,),
        bound_function_names=(function.name,),
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Incident"],
            temporal_scope={"kind": "current"},
            output_shape="ontology_relationships",
        ),
        plan=None,
    )
    judgment_model = _OperatingSubjectJudgmentModel()
    judgment_model.judge = lambda **_kwargs: {
        "primary_intent": "query.incident_evidence",
        "targets": [],
        "requested_facets": [
            "verified_symptoms",
            "affected_scope",
            "competing_hypotheses",
            "next_safe_diagnostic_step",
        ],
        "confidence": 0.95,
        "ambiguous": False,
        "action_posture": "advise_only",
        "action_subject": "none",
        "execution_authority": False,
    }
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=judgment_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Triage the bound incident.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000703",
            correlation_id="bound-triage",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_incident_triage_unavailable"
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    "requested_facets",
    [
        ["comparison", "incident_window", "attributed_observations"],
        ["compare", "incident", "window", "observation", "attribution"],
        ["comparison", "incident_context", "source_grounded_observations"],
        ["comparison", "pre_post_incident", "quote_observed_only", "target_attribution"],
        ["comparison", "citation", "incident_context", "pre_post_incident"],
    ],
)
def test_bound_incident_metric_comparison_builds_windowed_observation_frame(
    requested_facets: list[str],
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_metric_series",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    frame = build_bound_incident_metric_comparison_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=True,
        utterance="Compare bound incident metrics.",
        context=(),
    )

    assert frame is not None
    assert frame.operation is SemanticOperation.COMPARE
    assert frame.subject_constraints == ("Observation",)
    assert frame.temporal_scope == {"kind": "windowed"}
    assert frame.output_shape == "temporal_comparison"
    assert frame.execution_authority is False


def test_bound_incident_metric_comparison_accepts_allowlisted_declaration_targets() -> None:
    utterance = "Compare Incident and Resource observations."
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_metric_series",
            "requested_facets": ["compare", "incident_context"],
            "targets": [
                {
                    "kind": "incident_context",
                    "value": "Incident",
                    "canonical_value": "Incident",
                    "source_start": 8,
                    "source_end": 16,
                },
                {
                    "kind": "resource_scope",
                    "value": "Resource",
                    "canonical_value": "Resource",
                    "source_start": 21,
                    "source_end": 29,
                },
            ],
        }
    )

    frame = build_bound_incident_metric_comparison_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=True,
        utterance=utterance,
        context=(),
    )

    assert frame is not None
    assert frame.subject_constraints == ("Observation",)
    assert frame.execution_authority is False


@pytest.mark.parametrize(
    ("bound_incident", "requested_facets", "canonical_target"),
    [
        (False, ["comparison", "incident_window", "attributed_observations"], None),
        (True, ["comparison", "target_window"], None),
        (True, ["not_comparison", "incident_window", "attributed_observations"], None),
        (True, ["comparison", "incident_window", "attributed_observations"], "resource-a"),
    ],
)
def test_incident_metric_comparison_requires_complete_unanchored_bound_judgment(
    bound_incident: bool,
    requested_facets: list[str],
    canonical_target: str | None,
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_metric_series",
            "requested_facets": requested_facets,
            "targets": (
                []
                if canonical_target is None
                else [
                    {
                        "kind": "resource",
                        "value": "resource-a",
                        "canonical_value": canonical_target,
                        "source_start": 0,
                        "source_end": 10,
                    }
                ]
            ),
        }
    )

    frame = build_bound_incident_metric_comparison_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=bound_incident,
        utterance="Resource comparison.",
        context=(),
    )

    assert frame is None


def test_bound_incident_metric_comparison_holds_before_frame_model() -> None:
    observation = OntologyObjectType(
        schema_version="1.0.0",
        name="Observation",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, _definition = _fixture(additional_object_types=(observation,))
    model = _Model(
        frame=_frame(operation="explain_change", output_shape="causal_evidence"),
        plan=None,
    )
    judgment_model = _OperatingSubjectJudgmentModel()
    judgment_model.judge = lambda **_kwargs: {
        "primary_intent": "query.resource_metric_series",
        "targets": [],
        "requested_facets": [
            "comparison",
            "incident_window",
            "backend_latency",
            "pod_latency",
            "saturation",
            "citation_only",
            "attributed_observations",
        ],
        "confidence": 0.95,
        "ambiguous": False,
        "action_posture": "advise_only",
        "action_subject": "none",
        "execution_authority": False,
    }
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=judgment_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Compare bound incident metrics.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000704",
            correlation_id="bound-metric-comparison",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_incident_metric_comparison_unavailable"
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.COMPARE
    assert outcome.frame.subject_constraints == ("Observation",)
    assert outcome.frame.temporal_scope == {"kind": "windowed"}
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.frame_calls == 0
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    "requested_facets",
    [
        ["request_path", "next_hop", "virtual_network_peering"],
        ["network_path", "next_hop", "virtual_network_peering_relationship"],
    ],
)
def test_network_path_judgment_builds_exact_resource_clarification(
    requested_facets: list[str],
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.ontology_relationships",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    result = build_network_path_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Trace the network path.",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("Resource",)
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "ontology_relationships"
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.execution_authority is False


def test_resource_activity_judgment_accepts_uncanonicalized_resource_kind() -> None:
    utterance = "Inspect Container App activity."
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_change_activity",
            "requested_facets": [
                "revision",
                "restart",
                "configuration_activity",
                "past_30_minutes",
            ],
            "targets": [
                {
                    "kind": "resource_kind",
                    "value": "Container App",
                    "canonical_value": None,
                    "source_start": 8,
                    "source_end": 21,
                }
            ],
        }
    )

    result = build_resource_activity_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance=utterance,
        context=(),
    )

    assert result is not None
    _proposal, frame = result
    assert frame.subject_constraints == ("Resource",)
    assert frame.execution_authority is False


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets", "canonical_target"),
    [
        ("query.resource_metric_series", ["request_path", "next_hop", "peering"], None),
        ("query.ontology_relationships", ["request_path", "peering"], None),
        ("query.ontology_relationships", ["not_request_path", "next_hop", "peering"], None),
        ("query.ontology_relationships", ["request_path", "next_hop", "peering"], "resource-a"),
    ],
)
def test_network_path_clarification_rejects_incomplete_or_concrete_judgment(
    primary_intent: str,
    requested_facets: list[str],
    canonical_target: str | None,
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": (
                []
                if canonical_target is None
                else [
                    {
                        "kind": "resource",
                        "value": "resource-a",
                        "canonical_value": canonical_target,
                        "source_start": 0,
                        "source_end": 10,
                    }
                ]
            ),
        }
    )

    result = build_network_path_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="resource-a network path.",
        context=(),
    )

    assert result is None


def test_network_path_judgment_clarifies_before_candidate_frame_model() -> None:
    manifest, _definition = _fixture(include_resource_type=True)
    model = _Model(frame=_frame(), plan=None)
    judgment_model = _OperatingSubjectJudgmentModel()
    judgment_model.judge = lambda **_kwargs: {
        "primary_intent": "query.ontology_relationships",
        "targets": [],
        "requested_facets": [
            "request_path",
            "next_hop",
            "virtual_network_peering",
            "missing_segments",
            "conflicting_segments",
        ],
        "confidence": 0.95,
        "ambiguous": False,
        "action_posture": "advise_only",
        "action_subject": "none",
        "execution_authority": False,
    }
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=judgment_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Trace the network path.")

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.reason == "semantic_clarification_required"
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Resource",)
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.frame_calls == 0
    assert model.plan_calls == 0


def test_model_network_path_frame_clarifies_when_judgment_is_unavailable() -> None:
    manifest, _definition = _fixture(include_resource_type=True)
    model = _Model(
        frame=_frame(
            measure_concepts=["request_path", "next_hop", "virtual_network_peering"],
            output_shape="topology_graph",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Trace the network path.")

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert is_network_path_clarification_frame(outcome.frame)
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.frame_calls == 1
    assert model.plan_calls == 0


def test_multi_object_topology_frame_clarifies_without_localized_facets() -> None:
    pod = OntologyObjectType(
        schema_version="1.0.0",
        name="Pod",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, _definition = _fixture(additional_object_types=(pod,))
    model = _Model(
        frame=_frame(
            subject_constraints=["Pod", "Resource"],
            output_shape="ontology_relationships",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="리소스 간 연결 경로를 확인해줘.")

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert is_network_path_clarification_frame(outcome.frame)
    assert outcome.frame.subject_constraints == ("Resource",)
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.execution_authority is False
    assert model.frame_calls == 1
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    "requested_facets",
    [
        ["service_objective", "recovery_objective", "measured_breaches", "missing_evidence"],
        ["service_objectives", "recovery_objectives", "measured_violation", "evidence_gap"],
        ["service_objectives", "recovery_objectives", "breaches", "missing_evidence"],
        ["service_objective", "recovery_objective", "violation", "evidence_gap"],
        ["service", "recovery_objective", "distinguish_measured_breaches", "missing_evidence"],
    ],
)
def test_operating_objective_judgment_builds_canonical_validation_frame(
    requested_facets: list[str],
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.target_health_assessment",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    frame = build_operating_objectives_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Validate operating objectives.",
        context=(),
    )

    assert frame is not None
    assert frame.operation is SemanticOperation.VALIDATE
    assert frame.subject_constraints == (
        "BusinessService",
        "RecoveryObjective",
        "ServiceObjective",
    )
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "evidence_validation"
    assert frame.execution_authority is False


def test_operating_objective_relationship_intent_builds_validation_frame() -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.service_has_recovery_objective",
            "requested_facets": [
                "service",
                "recovery_objective",
                "distinguish_measured_breaches",
                "missing_evidence",
            ],
            "targets": [],
        }
    )

    frame = build_operating_objectives_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Validate operating objectives.",
        context=(),
    )

    assert frame is not None
    assert frame.operation is SemanticOperation.VALIDATE
    assert frame.subject_constraints == (
        "BusinessService",
        "RecoveryObjective",
        "ServiceObjective",
    )


def test_model_operating_objectives_frame_holds_without_judgment() -> None:
    business_service = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    manifest, _definition = _fixture(additional_object_types=(business_service,))
    model = _Model(
        frame=_frame(
            operation="validate",
            measure_concepts=[
                "service_objective",
                "recovery_objective",
                "measured_breaches",
                "missing_evidence",
            ],
            temporal_scope={"kind": "current"},
            output_shape="evidence_validation",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Validate operating objectives.")

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == (
        "BusinessService",
        "RecoveryObjective",
        "ServiceObjective",
    )
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.frame_calls == 1
    assert model.plan_calls == 0


def test_incomplete_operating_objective_facets_do_not_normalize() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            operation="validate",
            measure_concepts=["service_objective", "recovery_objective", "missing_evidence"],
            output_shape="evidence_validation",
        )
    )
    frame = build_semantic_frame(proposal, utterance="Validate objectives.", context=())

    resolved, resolved_frame = normalize_operating_objectives_frame(
        proposal,
        frame,
        utterance="Validate objectives.",
        context=(),
    )

    assert resolved is proposal
    assert resolved_frame is frame


def test_historical_topology_frame_requires_exact_resource_before_planning() -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            operation="compare",
            subject_constraints=["Change"],
            measure_concepts=[
                "after",
                "before",
                "evidence_backed",
                "relationship_changes",
                "requested_cutoff",
                "retained_topology",
            ],
            temporal_scope={"kind": "windowed"},
            output_shape="temporal_comparison",
        ),
        plan=_plan(definition),
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Compare retained topology.")

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert is_historical_topology_clarification_frame(outcome.frame)
    assert outcome.frame.subject_constraints == ("Resource",)
    assert outcome.frame.temporal_scope == {"kind": "historical"}
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.frame_calls == 1
    assert model.plan_calls == 0


def test_typed_topology_comparison_requires_exact_resource_before_planning() -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            operation="compare",
            subject_constraints=["Resource"],
            measure_concepts=[],
            temporal_scope={"kind": "windowed"},
            output_shape="topology_graph",
        ),
        plan=_plan(definition),
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Compare retained topology.")

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.COMPARE
    assert outcome.frame.subject_constraints == ("Resource",)
    assert outcome.frame.temporal_scope == {"kind": "historical"}
    assert outcome.frame.output_shape == "temporal_comparison"
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.frame_calls == 1
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    ("operation", "output_shape", "temporal_scope", "subject_constraints"),
    [
        ("select", "topology_graph", {"kind": "windowed"}, ["Resource"]),
        ("compare", "resource_list", {"kind": "windowed"}, ["Resource"]),
        ("compare", "topology_graph", {"kind": "current"}, ["Resource"]),
        ("compare", "topology_graph", {"kind": "windowed"}, ["resource-a"]),
    ],
)
def test_typed_topology_comparison_does_not_capture_other_frame_shapes(
    operation: str,
    output_shape: str,
    temporal_scope: dict[str, str],
    subject_constraints: list[str],
) -> None:
    manifest, _definition = _fixture()
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            operation=operation,
            subject_constraints=subject_constraints,
            measure_concepts=[],
            temporal_scope=temporal_scope,
            output_shape=output_shape,
        )
    )
    frame = build_semantic_frame(
        proposal,
        utterance="Compare resource-a topology.",
        context=(),
    )

    resolved, resolved_frame = normalize_historical_topology_clarification(
        proposal,
        frame,
        utterance="Compare resource-a topology.",
        context=(),
        descriptors=manifest.descriptors,
    )

    assert resolved is proposal
    assert resolved_frame is frame


@pytest.mark.parametrize(
    "requested_facets",
    [
        [
            "comparison",
            "before",
            "after",
            "requested_cutoff",
            "retained_topology",
            "relationship_changes",
        ],
        [
            "comparison",
            "requested_timeframe",
            "preserve_topology",
            "relationship_changes",
        ],
        [
            "before_cutoff",
            "after_cutoff",
            "relationship_changes",
            "evidence_backed",
        ],
        [
            "comparison",
            "baseline_time_window",
            "private_endpoint_preservation_topology",
            "evidence_grounded_relationship_changes",
            "only_report_supported_changes",
        ],
        [
            "comparison",
            "requested_timeframe",
            "private_endpoint_retention_topology",
            "evidence_grounded_relationship_changes",
        ],
        [
            "comparison",
            "baseline_timeframe",
            "before_and_after",
            "private_endpoint",
            "preservation_topology",
            "evidence_grounded",
            "relationship_changes_only",
        ],
        [
            "comparison",
            "baseline",
            "current_state",
            "relationship_changes",
            "evidence_grounded_only",
            "private_endpoint_preservation_topology",
            "time_window_before_after",
        ],
        [
            "comparison",
            "requested_time_reference",
            "private_endpoint",
            "preservation_topology",
            "evidence_grounded_relations_only",
            "relation_changes",
        ],
    ],
)
def test_historical_topology_judgment_builds_resource_clarification(
    requested_facets: list[str],
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_change_activity",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    result = build_historical_topology_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Compare retained topology.",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert frame.operation is SemanticOperation.COMPARE
    assert frame.subject_constraints == ("Resource",)
    assert frame.temporal_scope == {"kind": "historical"}
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.execution_authority is False


def test_historical_topology_event_history_judgment_builds_clarification() -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_event_history",
            "requested_facets": [
                "compare",
                "retained_topology",
                "before",
                "after",
                "requested_cutoff",
                "evidence_backed_relationship_changes",
            ],
            "targets": [],
        }
    )

    result = build_historical_topology_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Compare retained topology.",
        context=(),
    )

    assert result is not None
    _proposal, frame = result
    assert frame.subject_constraints == ("Resource",)
    assert frame.temporal_scope == {"kind": "historical"}


def test_kubernetes_event_judgment_without_grounded_time_and_type_keeps_frame() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            operation="select",
            subject_constraints=["Resource", "example-cluster"],
            measure_concepts=["resource_event.kubernetes"],
            temporal_scope={
                "kind": "historical",
                "lookback_seconds": 3600,
                "order": "ascending",
            },
            output_shape="resource_event_history",
        )
    )
    frame = build_semantic_frame(proposal, utterance="cluster events", context=())
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_event_history",
            "requested_facets": ["kubernetes_events", "recent_window", "time_order"],
            "targets": [
                {
                    "kind": "resource",
                    "value": "cluster",
                    "source_start": 0,
                    "source_end": 7,
                }
            ],
        }
    )

    resolved, resolved_frame = resolve_semantic_judgment_bound_read(
        proposal,
        frame,
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=False,
        utterance="cluster events",
        context=(),
    )

    assert resolved is proposal
    assert resolved_frame is frame


def test_kubernetes_event_alias_facets_complete_the_canonical_measure() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            operation="select",
            subject_constraints=["Resource", "example-cluster"],
            measure_concepts=[],
            temporal_scope={"lookback_seconds": 3600},
            output_shape="resource_event_history",
        )
    )
    utterance = "cluster recent hour Kubernetes event"
    frame = build_semantic_frame(proposal, utterance=utterance, context=())
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_event_history",
            "requested_facets": [
                "kubernetes_events",
                "recent_1h",
                "time_order",
            ],
            "targets": [
                {
                    "kind": "resource",
                    "value": "cluster",
                    "source_start": 0,
                    "source_end": 7,
                },
                {
                    "kind": "time_range",
                    "value": "recent hour",
                    "canonical_value": "duration.PT1H",
                    "source_start": 8,
                    "source_end": 19,
                },
                {
                    "kind": "event_type",
                    "value": "Kubernetes event",
                    "source_start": 20,
                    "source_end": 36,
                },
            ],
        }
    )

    resolved, resolved_frame = resolve_semantic_judgment_bound_read(
        proposal,
        frame,
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=False,
        utterance=utterance,
        context=(),
    )

    assert resolved.measure_concepts == ("resource_event.kubernetes",)
    assert resolved_frame.measure_concepts == ("resource_event.kubernetes",)
    assert resolved_frame.execution_authority is False


def test_kubernetes_event_judgment_duration_must_match_frame_lookback() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            operation="select",
            subject_constraints=["Resource", "example-cluster"],
            measure_concepts=["resource_event.kubernetes"],
            temporal_scope={"lookback_seconds": 86_400},
            output_shape="resource_event_history",
        )
    )
    utterance = "cluster recent hour Kubernetes event"
    frame = build_semantic_frame(proposal, utterance=utterance, context=())
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_event_history",
            "requested_facets": ["kubernetes_events", "recent_1h", "time_order"],
            "targets": [
                {"kind": "resource", "value": "cluster", "source_start": 0, "source_end": 7},
                {
                    "kind": "time_range",
                    "value": "recent hour",
                    "canonical_value": "duration.PT1H",
                    "source_start": 8,
                    "source_end": 19,
                },
                {
                    "kind": "event_type",
                    "value": "Kubernetes event",
                    "source_start": 20,
                    "source_end": 36,
                },
            ],
        }
    )

    resolved, resolved_frame = resolve_semantic_judgment_bound_read(
        proposal,
        frame,
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=False,
        utterance=utterance,
        context=(),
    )

    assert resolved is proposal
    assert resolved_frame is frame


def test_incomplete_kubernetes_event_judgment_does_not_change_the_frame() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            operation="select",
            subject_constraints=["Resource", "example-cluster"],
            measure_concepts=[],
            temporal_scope={"lookback_seconds": 3600},
            output_shape="resource_event_history",
        )
    )
    frame = build_semantic_frame(proposal, utterance="cluster events", context=())
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_event_history",
            "requested_facets": ["kubernetes_events", "recent_window"],
            "targets": [
                {
                    "kind": "resource",
                    "value": "cluster",
                    "source_start": 0,
                    "source_end": 7,
                }
            ],
        }
    )

    resolved, resolved_frame = resolve_semantic_judgment_bound_read(
        proposal,
        frame,
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=False,
        utterance="cluster events",
        context=(),
    )

    assert resolved is proposal
    assert resolved_frame is frame


@pytest.mark.parametrize(
    "requested_facets",
    [
        [
            "baseline_time_window",
            "private_endpoint_preservation_topology",
            "evidence_grounded_relationship_changes",
        ],
        [
            "comparison",
            "private_endpoint_preservation_topology",
            "evidence_grounded_relationship_changes",
        ],
        [
            "comparison",
            "baseline_time_window",
            "evidence_grounded_relationship_changes",
        ],
        [
            "comparison",
            "baseline_time_window",
            "private_endpoint_preservation_topology",
        ],
    ],
)
def test_incomplete_baseline_topology_judgment_does_not_build_clarification(
    requested_facets: list[str],
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_change_activity",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    result = build_historical_topology_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Compare retained topology.",
        context=(),
    )

    assert result is None


def test_incomplete_historical_topology_facets_do_not_normalize() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            operation="compare",
            measure_concepts=[
                "before",
                "retained_topology",
                "requested_cutoff",
                "relationship_changes",
            ],
            output_shape="temporal_comparison",
        )
    )
    frame = build_semantic_frame(proposal, utterance="Compare topology.", context=())

    resolved, resolved_frame = normalize_historical_topology_clarification(
        proposal,
        frame,
        utterance="Compare topology.",
        context=(),
        descriptors=(),
    )

    assert resolved is proposal
    assert resolved_frame is frame


@pytest.mark.parametrize(
    "requested_facets",
    [
        ["revision", "restart", "configuration_activity", "past_30_minutes"],
        ["last_30_minutes", "revision", "restart", "configuration_activity", "list"],
        ["revision", "restart", "configuration", "last_30_minutes", "list"],
        ["resource_change_activity", "time_window", "resource_kind", "activity_types"],
    ],
)
def test_resource_activity_judgment_builds_exact_target_clarification(
    requested_facets: list[str],
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_change_activity",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    result = build_resource_activity_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Inspect bounded Resource activity.",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("Resource",)
    assert frame.temporal_scope == {"kind": "windowed"}
    assert frame.output_shape == "target_activity"
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.execution_authority is False


def test_resource_activity_judgment_accepts_resource_type_and_duration_targets() -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_change_activity",
            "requested_facets": [
                "revision",
                "restart",
                "configuration_activity",
                "container_app",
                "time_range",
                "ordering",
            ],
            "targets": [
                {
                    "kind": "resource_type",
                    "value": "Container App",
                    "canonical_value": "ResourceType",
                    "source_start": 0,
                    "source_end": 13,
                },
                {
                    "kind": "time_range",
                    "value": "past 30 minutes",
                    "canonical_value": "duration.PT30M",
                    "source_start": 14,
                    "source_end": 29,
                },
            ],
        }
    )

    result = build_resource_activity_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Container App past 30 minutes",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.output_shape == "target_activity"
    assert frame.temporal_scope == {"kind": "windowed"}


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets", "canonical_target"),
    [
        (
            "query.resource_event_history",
            ["revision", "restart", "configuration_activity", "past_30_minutes"],
            None,
        ),
        (
            "query.resource_change_activity",
            ["restart", "configuration_activity", "past_30_minutes"],
            None,
        ),
        (
            "query.resource_change_activity",
            ["revision", "configuration_activity", "past_30_minutes"],
            None,
        ),
        (
            "query.resource_change_activity",
            ["revision", "restart", "past_30_minutes"],
            None,
        ),
        (
            "query.resource_change_activity",
            ["revision", "restart", "configuration_activity"],
            None,
        ),
        (
            "query.resource_change_activity",
            ["time_window", "resource_kind", "activity_types"],
            None,
        ),
        (
            "query.resource_change_activity",
            ["resource_change_activity", "resource_kind", "activity_types"],
            None,
        ),
        (
            "query.resource_change_activity",
            ["resource_change_activity", "time_window", "activity_types"],
            None,
        ),
        (
            "query.resource_change_activity",
            ["resource_change_activity", "time_window", "resource_kind"],
            None,
        ),
        (
            "query.resource_change_activity",
            ["revision", "restart", "configuration_activity", "past_30_minutes"],
            "resource-a",
        ),
    ],
)
def test_resource_activity_clarification_rejects_incomplete_or_concrete_judgment(
    primary_intent: str,
    requested_facets: list[str],
    canonical_target: str | None,
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": (
                []
                if canonical_target is None
                else [
                    {
                        "kind": "resource",
                        "value": "resource-a",
                        "canonical_value": canonical_target,
                        "source_start": 0,
                        "source_end": 10,
                    }
                ]
            ),
        }
    )

    result = build_resource_activity_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="resource-a activity.",
        context=(),
    )

    assert result is None


def test_resource_activity_judgment_clarifies_before_invalid_frame_model() -> None:
    manifest, _definition = _fixture(include_resource_type=True)
    model = _Model(
        frame=_frame(operation="action_draft", output_shape="action_draft"),
        plan=None,
    )
    judgment_model = _OperatingSubjectJudgmentModel()
    judgment_model.judge = lambda **_kwargs: {
        "primary_intent": "query.resource_change_activity",
        "targets": [],
        "requested_facets": [
            "revision",
            "restart",
            "configuration_activity",
            "past_30_minutes",
        ],
        "confidence": 0.95,
        "ambiguous": False,
        "action_posture": "advise_only",
        "action_subject": "none",
        "execution_authority": False,
    }
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=judgment_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Inspect bounded Resource activity.")

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.SELECT
    assert outcome.frame.subject_constraints == ("Resource",)
    assert outcome.frame.temporal_scope == {"kind": "windowed"}
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.frame_calls == 0
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets"),
    [
        (
            "query.ontology_declaration",
            [
                "declaration_changes",
                "evidence_freshness",
                "completeness",
                "conflicts",
                "unavailable_sources",
            ],
        ),
        (
            "query.ontology_relationships",
            [
                "declaration_change",
                "evidence_freshness",
                "completeness",
                "conflict",
                "unavailable_source",
            ],
        ),
    ],
)
def test_ontology_release_health_judgment_builds_historical_validation_frame(
    primary_intent: str,
    requested_facets: list[str],
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    frame = build_ontology_release_health_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Validate retained release evidence.",
        context=(),
    )

    assert frame is not None
    assert frame.operation is SemanticOperation.VALIDATE
    assert frame.subject_constraints == ("Resource",)
    assert frame.temporal_scope == {"kind": "historical"}
    assert frame.output_shape == "ontology_release_evidence_health"
    assert frame.execution_authority is False


@pytest.mark.parametrize("canonical_target", ["Ontology", "PolicyArtifact", "Rule"])
def test_ontology_release_health_accepts_catalog_declaration_target(
    canonical_target: str,
) -> None:
    utterance = f"Validate {canonical_target} release evidence."
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.ontology_relationships",
            "requested_facets": [
                "declaration_change",
                "evidence_freshness",
                "completeness",
                "conflicts",
                "unavailable_sources",
            ],
            "targets": [
                {
                    "kind": "object_type",
                    "value": canonical_target,
                    "canonical_value": canonical_target,
                    "source_start": 9,
                    "source_end": 9 + len(canonical_target),
                }
            ],
        }
    )

    frame = build_ontology_release_health_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance=utterance,
        context=(),
    )

    assert frame is not None
    assert frame.subject_constraints == ("Resource",)
    assert frame.execution_authority is False


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets", "canonical_target"),
    [
        (
            "query.manifest",
            [
                "declaration_changes",
                "evidence_freshness",
                "completeness",
                "conflicts",
                "unavailable_sources",
            ],
            None,
        ),
        (
            "query.ontology_declaration",
            ["evidence_freshness", "completeness", "conflicts", "unavailable_sources"],
            None,
        ),
        (
            "query.ontology_declaration",
            ["declaration_changes", "completeness", "conflicts", "unavailable_sources"],
            None,
        ),
        (
            "query.ontology_declaration",
            [
                "declaration_changes",
                "evidence_freshness",
                "completeness",
                "conflicts",
                "unavailable_sources",
            ],
            "resource-a",
        ),
    ],
)
def test_ontology_release_health_rejects_incomplete_or_concrete_judgment(
    primary_intent: str,
    requested_facets: list[str],
    canonical_target: str | None,
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": (
                []
                if canonical_target is None
                else [
                    {
                        "kind": "resource",
                        "value": "resource-a",
                        "canonical_value": canonical_target,
                        "source_start": 0,
                        "source_end": 10,
                    }
                ]
            ),
        }
    )

    frame = build_ontology_release_health_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="resource-a release evidence.",
        context=(),
    )

    assert frame is None


def test_ontology_release_health_holds_before_invalid_frame_model() -> None:
    manifest, _definition = _fixture()
    model = _Model(
        frame=_frame(operation="action_draft", output_shape="action_draft"),
        plan=None,
    )
    judgment_model = _OperatingSubjectJudgmentModel()
    judgment_model.judge = lambda **_kwargs: {
        "primary_intent": "query.ontology_declaration",
        "targets": [],
        "requested_facets": [
            "declaration_changes",
            "evidence_freshness",
            "completeness",
            "conflicts",
            "unavailable_sources",
        ],
        "confidence": 0.95,
        "ambiguous": False,
        "action_posture": "advise_only",
        "action_subject": "none",
        "execution_authority": False,
    }
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=judgment_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Validate retained release evidence.")

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_ontology_release_evidence_health_unavailable"
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.VALIDATE
    assert outcome.frame.subject_constraints == ("Resource",)
    assert outcome.frame.temporal_scope == {"kind": "historical"}
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.frame_calls == 0
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    "requested_facets",
    [
        ["attached_to", "routes_to", "workload_depends_on"],
        [
            "connected_to",
            "observed_routing_relationship",
            "aks_pod_workload",
            "postgresql_dependency",
            "storage_dependency",
        ],
    ],
)
def test_private_connectivity_judgment_builds_resource_clarification(
    requested_facets: list[str],
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.ontology_relationships",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    result = build_private_connectivity_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Inspect private connectivity.",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("Resource",)
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "ontology_relationships"
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.execution_authority is False


def test_private_connectivity_accepts_catalog_targets() -> None:
    utterance = "Inspect Workload attached_to private connectivity."
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.ontology_relationships",
            "requested_facets": [
                "connected_to",
                "observed_routing_relationship",
                "aks_pod_workload",
                "postgresql_dependency",
                "storage_dependency",
            ],
            "targets": [
                {
                    "kind": "object_type",
                    "value": "Workload",
                    "canonical_value": "Workload",
                    "source_start": 8,
                    "source_end": 16,
                },
                {
                    "kind": "link_type",
                    "value": "attached_to",
                    "canonical_value": "attached_to",
                    "source_start": 17,
                    "source_end": 28,
                },
            ],
        }
    )

    result = build_private_connectivity_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance=utterance,
        context=(),
    )

    assert result is not None
    _proposal, frame = result
    assert frame.subject_constraints == ("Resource",)
    assert frame.execution_authority is False


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets", "canonical_target"),
    [
        (
            "query.resource_change_activity",
            ["attached_to", "routes_to", "workload_depends_on"],
            None,
        ),
        ("query.ontology_relationships", ["routes_to", "workload_depends_on"], None),
        ("query.ontology_relationships", ["attached_to", "workload_depends_on"], None),
        ("query.ontology_relationships", ["attached_to", "routes_to"], None),
        (
            "query.ontology_relationships",
            ["attached_to", "routes_to", "workload_depends_on"],
            "resource-a",
        ),
    ],
)
def test_private_connectivity_rejects_incomplete_or_concrete_judgment(
    primary_intent: str,
    requested_facets: list[str],
    canonical_target: str | None,
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": (
                []
                if canonical_target is None
                else [
                    {
                        "kind": "resource",
                        "value": "resource-a",
                        "canonical_value": canonical_target,
                        "source_start": 0,
                        "source_end": 10,
                    }
                ]
            ),
        }
    )

    result = build_private_connectivity_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="resource-a private connectivity.",
        context=(),
    )

    assert result is None


def test_private_connectivity_clarifies_before_generic_topology_plan() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(output_shape="topology_graph"), plan=_plan(definition))
    judgment_model = _OperatingSubjectJudgmentModel()
    judgment_model.judge = lambda **_kwargs: {
        "primary_intent": "query.ontology_relationships",
        "targets": [],
        "requested_facets": ["attached_to", "routes_to", "workload_depends_on"],
        "confidence": 0.95,
        "ambiguous": False,
        "action_posture": "advise_only",
        "action_subject": "none",
        "execution_authority": False,
    }
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=judgment_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Inspect private connectivity.")

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Resource",)
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.frame_calls == 0
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    "requested_facets",
    [
        ["causal_hypothesis", "resource_targets", "required_evidence", "approval"],
        ["causal_hypothesis", "target_resources", "evidence_required", "approval"],
        [
            "causal_hypothesis",
            "recovery_plan",
            "resources",
            "evidence_still_required",
            "approval",
        ],
        ["causal_hypothesis", "resources", "evidence_required_before_approval"],
        ["review", "approval_readiness", "additional_evidence_needed"],
    ],
)
def test_recovery_plan_judgment_builds_validation_clarification(
    requested_facets: list[str],
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.linked_artifact_targets",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    result = build_recovery_plan_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Review the recovery plan.",
        context=(),
    )

    assert result is not None
    proposal, frame = result
    assert frame.operation is SemanticOperation.VALIDATE
    assert frame.subject_constraints == ("RecoveryPlan",)
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "ontology_relationships"
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.execution_authority is False


def test_recovery_plan_target_health_judgment_builds_clarification() -> None:
    utterance = "Review CausalHypothesis RecoveryPlan Resource readiness."
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    targets = []
    for value in ("CausalHypothesis", "RecoveryPlan", "Resource"):
        start = utterance.index(value)
        targets.append(
            {
                "kind": "object_type",
                "value": value,
                "canonical_value": value,
                "source_start": start,
                "source_end": start + len(value),
            }
        )
    judgment_data.update(
        {
            "primary_intent": "query.target_health_assessment",
            "requested_facets": [
                "review",
                "approval_readiness",
                "additional_evidence_needed",
            ],
            "targets": targets,
        }
    )

    result = build_recovery_plan_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance=utterance,
        context=(),
    )

    assert result is not None
    _proposal, frame = result
    assert frame.operation is SemanticOperation.VALIDATE
    assert frame.subject_constraints == ("RecoveryPlan",)
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.execution_authority is False


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets", "canonical_target"),
    [
        (
            "query.ontology_relationships",
            ["causal_hypothesis", "resource_targets", "required_evidence", "approval"],
            None,
        ),
        (
            "query.linked_artifact_targets",
            ["resource_targets", "required_evidence", "approval"],
            None,
        ),
        (
            "query.linked_artifact_targets",
            ["causal_hypothesis", "required_evidence", "approval"],
            None,
        ),
        (
            "query.linked_artifact_targets",
            ["causal_hypothesis", "resource_targets", "approval"],
            None,
        ),
        (
            "query.linked_artifact_targets",
            ["causal_hypothesis", "resource_targets", "required_evidence", "approval"],
            "recovery-plan-a",
        ),
    ],
)
def test_recovery_plan_rejects_incomplete_or_concrete_judgment(
    primary_intent: str,
    requested_facets: list[str],
    canonical_target: str | None,
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": (
                []
                if canonical_target is None
                else [
                    {
                        "kind": "recovery_plan",
                        "value": "recovery-plan-a",
                        "canonical_value": canonical_target,
                        "source_start": 0,
                        "source_end": 15,
                    }
                ]
            ),
        }
    )

    result = build_recovery_plan_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="recovery-plan-a review.",
        context=(),
    )

    assert result is None


def test_recovery_plan_clarifies_before_generic_relationship_plan() -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            subject_constraints=["Approval", "CausalHypothesis", "RecoveryPlan"],
            temporal_scope={"kind": "current"},
            output_shape="ontology_relationships",
        ),
        plan=_plan(definition),
    )
    judgment_model = _OperatingSubjectJudgmentModel()
    judgment_model.judge = lambda **_kwargs: {
        "primary_intent": "query.linked_artifact_targets",
        "targets": [],
        "requested_facets": [
            "causal_hypothesis",
            "resource_targets",
            "required_evidence",
            "approval",
        ],
        "confidence": 0.95,
        "ambiguous": False,
        "action_posture": "advise_only",
        "action_subject": "none",
        "execution_authority": False,
    }
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=judgment_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Review the recovery plan.")

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.VALIDATE
    assert outcome.frame.subject_constraints == ("RecoveryPlan",)
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.frame_calls == 0
    assert model.plan_calls == 0


def test_resource_classification_judgment_builds_current_frame() -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_state_inventory",
            "requested_facets": [
                "resource_type_classifications",
                "mapped_types",
                "unmapped_native_type",
                "keep_unclassified",
            ],
            "targets": [],
        }
    )

    frame = build_resource_classification_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Inspect Resource classifications.",
        context=(),
    )

    assert frame is not None
    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("Resource",)
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "ontology_relationships"
    assert frame.execution_authority is False


@pytest.mark.parametrize(
    ("primary_intent", "direction_facet"),
    [
        ("query.resource_relationships", "preserve_ownership_direction"),
        ("query.resource_current_state", "non_reversed_ownership_direction"),
    ],
)
def test_resource_relationship_judgment_requests_exact_resource(
    primary_intent: str,
    direction_facet: str,
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": [
                "containing_parent",
                "managed_disks",
                "attached_network_interfaces",
                direction_facet,
            ],
            "targets": [],
        }
    )

    resolved = build_resource_relationship_clarification(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Inspect current Resource relationships.",
        context=(),
    )

    assert resolved is not None
    proposal, frame = resolved
    assert proposal.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("Resource",)
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "ontology_relationships"
    assert frame.execution_authority is False


@pytest.mark.parametrize(
    ("targets", "trace_facet", "limitation_facet"),
    [
        ([], "trace_relationships", "no_current_finding"),
        ([], "explore", "controlled"),
        ([], "relationships", "scope"),
        (["ActionType", "ResourceType", "Rule", "SignalType"], "trace", "governed"),
        (
            ["ActionType", "Resource", "ResourceType", "Rule", "Signal", "SignalType"],
            "trace",
            "governed",
        ),
        (
            ["ActionType", "ResourceType", "Rule", "SignalType"],
            "trace_relationships",
            "without_current_finding",
        ),
    ],
)
def test_ontology_trace_judgment_builds_schema_frame_without_current_finding(
    targets: list[str],
    trace_facet: str,
    limitation_facet: str,
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.ontology_relationships",
            "requested_facets": [
                "resource_type",
                "signal_type",
                "action_type",
                trace_facet,
                limitation_facet,
            ],
            "targets": [
                {
                    "kind": "object_type",
                    "value": target,
                    "canonical_value": target,
                    "source_start": 0,
                    "source_end": len(target),
                }
                for target in targets
            ],
        }
    )

    frame = build_ontology_trace_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Inspect schema traceability.",
        context=(),
    )

    assert frame is not None
    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("ActionType", "ResourceType", "Rule", "SignalType")
    assert frame.temporal_scope == {}
    assert frame.output_shape == "ontology_relationships"
    assert frame.execution_authority is False


def _service_agent_ownership_judgment(
    *,
    targets: tuple[str, ...] = ("Agent", "Resource", "Workload"),
    facets: tuple[str, ...] = (
        "business_services",
        "workloads",
        "resources",
        "declared_owning_agent",
        "ownership_not_execution_permission",
    ),
) -> SemanticJudgmentProposal:
    return SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.ontology_relationships",
            "targets": [
                {
                    "kind": "object_type",
                    "value": target,
                    "canonical_value": target,
                    "source_start": 0,
                    "source_end": len(target),
                }
                for target in targets
            ],
            "requested_facets": list(facets),
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "authority": "candidate_only",
            "execution_authority": False,
        }
    )


def test_business_capability_mapping_builds_typed_unsupported_boundary() -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.ontology_relationships",
            "targets": [
                {
                    "kind": "object_type",
                    "value": target,
                    "canonical_value": target,
                    "source_start": 0,
                    "source_end": len(target),
                }
                for target in ("BusinessCapability", "BusinessService")
            ],
            "requested_facets": ["reviewed_service_mappings", "unavailable_mapping"],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "authority": "candidate_only",
            "execution_authority": False,
        }
    )

    frame = build_business_capability_mapping_frame(
        judgment,
        utterance="Identify reviewed business capability service mappings.",
        context=(),
    )

    assert frame is not None
    assert frame.subject_constraints == ("BusinessCapability", "BusinessService")
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "ontology_relationships"
    assert frame.execution_authority is False


def test_business_capability_mapping_accepts_typed_facets_when_spans_are_unresolved() -> None:
    judgment = SemanticJudgmentProposal.model_validate(
        {
            "primary_intent": "query.ontology_relationships",
            "targets": [],
            "requested_facets": [
                "business_capabilities",
                "service_mappings",
                "mapping_availability",
            ],
            "confidence": 0.95,
            "ambiguous": False,
            "action_posture": "advise_only",
            "action_subject": "none",
            "authority": "candidate_only",
            "execution_authority": False,
        }
    )

    frame = build_business_capability_mapping_frame(
        judgment,
        utterance="Identify reviewed capability mappings.",
        context=(),
    )

    assert frame is not None
    assert frame.subject_constraints == ("BusinessCapability", "BusinessService")


def _service_agent_ownership_descriptors() -> tuple[dict[str, object], ...]:
    return (
        *(
            {"kind": "object", "name": name}
            for name in ("Agent", "BusinessService", "Resource", "Workload")
        ),
        {
            "kind": "link",
            "name": "implemented_by",
            "from_type": "BusinessService",
            "to_type": "Workload",
        },
        {
            "kind": "link",
            "name": "owns",
            "from_type": "Agent",
            "to_type": "Resource",
        },
        {
            "kind": "link",
            "name": "workload_runs_on",
            "from_type": "Workload",
            "to_type": "Resource",
        },
    )


@pytest.mark.parametrize(
    "targets",
    [
        ("Agent",),
        ("Agent", "Resource", "Workload"),
        ("Agent", "BusinessService", "Resource", "Workload"),
    ],
)
def test_service_agent_ownership_judgment_builds_exact_current_frame(
    targets: tuple[str, ...],
) -> None:
    frame = build_service_agent_ownership_frame(
        _service_agent_ownership_judgment(targets=targets),
        utterance="Inspect service ownership.",
        context=(),
        descriptors=_service_agent_ownership_descriptors(),
    )

    assert frame is not None
    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("Agent", "BusinessService", "Resource", "Workload")
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.output_shape == "ontology_relationships"
    assert frame.execution_authority is False


def test_service_agent_ownership_accepts_reviewed_authorization_context() -> None:
    frame = build_service_agent_ownership_frame(
        _service_agent_ownership_judgment(
            targets=("Agent", "AuthorizationPolicyAssignment", "Resource", "Workload"),
            facets=(
                "reviewed_business_services",
                "authorized_scope",
                "workloads",
                "resources",
                "declared_owning_agent",
                "ownership_not_execution_permission",
            ),
        ),
        utterance="Inspect service ownership.",
        context=(),
        descriptors=_service_agent_ownership_descriptors(),
    )

    assert frame is not None
    assert frame.subject_constraints == ("Agent", "BusinessService", "Resource", "Workload")
    assert frame.execution_authority is False


def test_service_agent_ownership_accepts_unbound_permission_contrast() -> None:
    frame = build_service_agent_ownership_frame(
        _service_agent_ownership_judgment(
            targets=(),
            facets=(
                "business_services",
                "authorized_scope",
                "workloads",
                "resources",
                "owning_agent",
                "ownership_vs_execution_permission",
            ),
        ),
        utterance="Inspect service ownership.",
        context=(),
        descriptors=_service_agent_ownership_descriptors(),
    )

    assert frame is not None
    assert frame.subject_constraints == ("Agent", "BusinessService", "Resource", "Workload")
    assert frame.execution_authority is False


@pytest.mark.parametrize(
    ("judgment", "descriptors"),
    [
        (
            _service_agent_ownership_judgment(
                facets=("business_services", "workloads", "resources", "declared_owning_agent")
            ),
            _service_agent_ownership_descriptors(),
        ),
        (
            _service_agent_ownership_judgment(
                targets=("Agent", "Ownership", "Resource", "Workload")
            ),
            _service_agent_ownership_descriptors(),
        ),
        (
            _service_agent_ownership_judgment(),
            tuple(
                descriptor
                for descriptor in _service_agent_ownership_descriptors()
                if descriptor.get("name") != "owns"
            ),
        ),
    ],
)
def test_service_agent_ownership_requires_complete_exact_typed_structure(
    judgment: SemanticJudgmentProposal,
    descriptors: tuple[dict[str, object], ...],
) -> None:
    assert (
        build_service_agent_ownership_frame(
            judgment,
            utterance="Inspect service ownership.",
            context=(),
            descriptors=descriptors,
        )
        is None
    )


def test_service_agent_ownership_builds_composite_instance_path_plan() -> None:
    utterance = "Inspect Agent Resource Workload ownership for BusinessService."

    class _OwnershipJudgmentModel:
        def judge(self, **_kwargs: Any) -> dict[str, object]:
            return {
                "primary_intent": "query.ontology_relationships",
                "targets": [
                    {
                        "kind": "object_type",
                        "value": target,
                        "canonical_value": target,
                        "source_start": utterance.index(target),
                        "source_end": utterance.index(target) + len(target),
                    }
                    for target in ("Agent", "Resource", "Workload")
                ],
                "requested_facets": [
                    "business_services",
                    "workloads",
                    "resources",
                    "declared_owning_agent",
                    "ownership_not_execution_permission",
                ],
                "confidence": 0.95,
                "ambiguous": False,
                "action_posture": "advise_only",
                "execution_authority": False,
            }

    def object_type(name: str) -> OntologyObjectType:
        return OntologyObjectType(
            schema_version="1.0.0",
            name=name,
            version="1.0.0",
            key="id",
            properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
        )

    manifest, _definition = _fixture(
        additional_object_types=tuple(
            object_type(name) for name in ("Agent", "BusinessService", "Workload")
        ),
        additional_link_types=(
            OntologyLinkType(
                schema_version="1.0.0",
                name="implemented_by",
                version="1.0.0",
                from_type="BusinessService",
                to_type="Workload",
                cardinality=LinkCardinality.ONE_TO_MANY,
            ),
            OntologyLinkType(
                schema_version="1.0.0",
                name="owns",
                version="1.0.0",
                from_type="Agent",
                to_type="Resource",
                cardinality=LinkCardinality.MANY_TO_MANY,
            ),
            OntologyLinkType(
                schema_version="1.0.0",
                name="workload_runs_on",
                version="1.0.0",
                from_type="Workload",
                to_type="Resource",
                cardinality=LinkCardinality.MANY_TO_MANY,
            ),
        ),
    )
    model = _Model(frame=_frame(), plan=None)
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_OwnershipJudgmentModel(),  # type: ignore[arg-type]
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.reason == "semantic_plan_verified"
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == (
        "Agent",
        "BusinessService",
        "Resource",
        "Workload",
    )
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.FUNCTION,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.ONTOLOGY_INSTANCE_PATH,
    )
    path = outcome.plan.nodes[-1]
    assert path.depends_on == (
        "ownership-schema-1",
        "ownership-schema-2",
        "ownership-schema-3",
    )
    assert path.arguments["root_selector"] == {
        "kind": "object_type",
        "name": "BusinessService",
    }
    assert [
        (
            step["link_type"],
            step["direction"],
            step["selector"]["name"],
        )
        for step in path.arguments["steps"]
    ] == [
        ("implemented_by", "outgoing", "Workload"),
        ("workload_runs_on", "outgoing", "Resource"),
        ("owns", "incoming", "Agent"),
    ]
    assert outcome.plan.output_node_ids == ("service-agent-paths",)
    assert outcome.execution_authority is False
    assert (model.frame_calls, model.plan_calls) == (0, 0)


def test_rule_trace_builds_three_pair_server_plan_without_model_planning() -> None:
    utterance = "Trace Rule ResourceType SignalType ActionType relationships."

    class _TraceJudgmentModel:
        def judge(self, **_kwargs: Any) -> dict[str, object]:
            return {
                "primary_intent": "query.ontology_relationships",
                "targets": [
                    {
                        "kind": "object_type",
                        "value": target,
                        "canonical_value": target,
                        "source_start": utterance.index(target),
                        "source_end": utterance.index(target) + len(target),
                    }
                    for target in ("Rule", "ResourceType", "SignalType", "ActionType")
                ],
                "requested_facets": ["trace_relationships", "without_current_finding"],
                "confidence": 0.95,
                "ambiguous": False,
                "action_posture": "advise_only",
                "execution_authority": False,
            }

    def object_type(name: str) -> OntologyObjectType:
        return OntologyObjectType(
            schema_version="1.0.0",
            name=name,
            version="1.0.0",
            key="id",
            properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
        )

    manifest, _definition = _fixture(
        include_rule=True,
        function_types=(
            ontology_declaration_function_type(),
            ontology_relationships_function_type(),
        ),
        additional_object_types=tuple(
            object_type(name) for name in ("ActionType", "ResourceType", "SignalType")
        ),
        additional_link_types=(
            OntologyLinkType(
                schema_version="1.0.0",
                name="applies_to",
                version="1.0.0",
                from_type="Rule",
                to_type="ResourceType",
                cardinality=LinkCardinality.MANY_TO_MANY,
            ),
            OntologyLinkType(
                schema_version="1.0.0",
                name="remediates",
                version="1.0.0",
                from_type="Rule",
                to_type="ActionType",
                cardinality=LinkCardinality.MANY_TO_MANY,
            ),
            OntologyLinkType(
                schema_version="1.0.0",
                name="triggered_by",
                version="1.0.0",
                from_type="Rule",
                to_type="SignalType",
                cardinality=LinkCardinality.MANY_TO_MANY,
            ),
        ),
    )
    model = _Model(frame=_frame(), plan=None)
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_TraceJudgmentModel(),  # type: ignore[arg-type]
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.FUNCTION,)),
        now=lambda: NOW,
    )

    outcome = _run(service, utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert len(outcome.plan.nodes) == 4
    assert {
        tuple(node.arguments["arguments"]["object_types"])
        for node in outcome.plan.nodes
        if node.arguments.get("function_name") == "query.ontology_relationships"
    } == {
        ("ActionType", "Rule"),
        ("ResourceType", "Rule"),
        ("Rule", "SignalType"),
    }
    assert {
        node.arguments.get("function_name")
        for node in outcome.plan.nodes
        if node.kind is QueryNodeKind.FUNCTION
    } == {"query.ontology_declaration", "query.ontology_relationships"}
    assert "declaration-rule" not in outcome.plan.output_node_ids
    assert (model.frame_calls, model.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    ("trace_facet", "limitation_facet"),
    [
        ("trace", "without_asserting_current_finding"),
        ("trace_relationships", "without_current_finding"),
    ],
)
def test_complete_ontology_trace_frame_allows_unrelated_identifier_shaped_token(
    trace_facet: str,
    limitation_facet: str,
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["ActionType", "ResourceType", "Rule", "SignalType"],
            measure_concepts=[
                "action_type",
                "resource_type",
                "signal_type",
                trace_facet,
                limitation_facet,
            ],
            output_shape="ontology_relationships",
        )
    )

    _validate_frame_proposal(
        proposal,
        utterance="Trace declarations for provider-native-three-part terminology.",
        descriptors=(),
    )


def test_incomplete_ontology_trace_frame_keeps_runtime_instance_guard() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["ActionType", "ResourceType", "Rule", "SignalType"],
            measure_concepts=["resource_type", "trace_relationships"],
            output_shape="ontology_relationships",
        )
    )

    with pytest.raises(
        ValueError,
        match="schema-level semantic frame names a runtime resource instance",
    ):
        _validate_frame_proposal(
            proposal,
            utterance="Inspect exact-runtime-three-part",
            descriptors=(),
        )


def test_advise_only_ontology_trace_demotes_action_draft_candidate() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            operation="action_draft",
            subject_constraints=["ActionType", "ResourceType", "Rule", "SignalType"],
            output_shape="action_draft",
        )
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.ontology_relationships",
            "requested_facets": [
                "resource_type",
                "signal_type",
                "action_type",
                "trace",
                "governed",
            ],
            "targets": [],
        }
    )

    _resolved, frame = resolve_semantic_judgment_action_draft(
        proposal,
        build_semantic_frame(proposal, utterance="", context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="",
        context=(),
    )

    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("ActionType", "ResourceType", "Rule", "SignalType")
    assert frame.temporal_scope == {}
    assert frame.output_shape == "ontology_relationships"
    assert frame.execution_authority is False


@pytest.mark.parametrize(
    ("requested_facets", "subject_constraints", "expected_temporal_scope"),
    [
        (
            ["resource_type", "signal_type", "controlled_action_type"],
            ["ActionType", "ResourceType", "Rule", "SignalType"],
            {},
        ),
        (
            ["resource_type", "signal_type", "action_type", "scope", "relationships"],
            ["ActionType", "ResourceType", "Rule", "SignalType"],
            {},
        ),
        (
            ["resource_type", "signal_type", "action_type", "relationships"],
            ["ActionType", "ResourceType", "SignalType"],
            {"kind": "current"},
        ),
    ],
)
def test_controlled_action_trace_normalizes_only_exact_schema_subjects(
    requested_facets: list[str],
    subject_constraints: list[str],
    expected_temporal_scope: dict[str, str],
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=subject_constraints,
            temporal_scope={"kind": "current"},
            output_shape="ontology_relationships",
        )
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.ontology_relationships",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    _resolved, frame = normalize_ontology_trace_frame(
        proposal,
        build_semantic_frame(proposal, utterance="", context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="",
        context=(),
    )
    _resolved, frame = normalize_operating_relationship_temporal_scope(
        _resolved,
        frame,
        utterance="",
        context=(),
        descriptors=tuple(
            {"kind": "object", "name": name}
            for name in ("ActionType", "ResourceType", "Rule", "SignalType")
        ),
    )

    assert frame.temporal_scope == expected_temporal_scope
    assert frame.execution_authority is False
    assert is_ontology_trace_frame(frame) is (expected_temporal_scope == {})


@pytest.mark.parametrize(
    ("subject_constraints", "expected_temporal_scope"),
    [
        (["ActionType", "ResourceType", "Rule", "SignalType"], {}),
        (["ActionType", "ResourceType", "SignalType"], {"kind": "current"}),
    ],
)
def test_candidate_only_trace_normalizes_only_exact_schema_subjects(
    subject_constraints: list[str],
    expected_temporal_scope: dict[str, str],
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=subject_constraints,
            measure_concepts=["resource_type", "signal_type", "controlled_action_type"],
            temporal_scope={"kind": "current"},
            output_shape="ontology_relationships",
        )
    )

    _resolved, frame = normalize_ontology_trace_frame(
        proposal,
        build_semantic_frame(proposal, utterance="", context=()),
        judgment=None,
        utterance="",
        context=(),
    )

    assert frame.temporal_scope == expected_temporal_scope
    assert frame.execution_authority is False
    assert is_ontology_trace_frame(frame) is (expected_temporal_scope == {})


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets"),
    [
        (
            "query.ontology_relationships",
            ["resource_type_classifications", "unclassified_native_type"],
        ),
        (
            "query.resource_state_inventory",
            [
                "reviewed_resourcetype_classification",
                "mapping",
                "native_unclassified_state",
                "explicit_unclassified_retention",
            ],
        ),
        (
            "query.ontology_relationships",
            ["resource_type_classifications", "unmapped_native_type_unclassified"],
        ),
        (
            "query.resource_state_inventory",
            [
                "resource_type_classification",
                "unmapped_native_types",
                "keep_unclassified",
            ],
        ),
        (
            "query.resource_state_inventory",
            [
                "reviewed_resource_type_classification",
                "mapping",
                "unmapped_native_types",
                "explicit_unclassified_state",
            ],
        ),
        (
            "query.resource_state_inventory",
            [
                "resource_type_classification",
                "reviewed_classification",
                "native_unmapped_types",
                "unclassified_state",
                "mapping",
            ],
        ),
        (
            "query.ontology_relationships",
            [
                "reviewed_resource_type_classification",
                "mapping_status",
                "native_types_unclassified",
            ],
        ),
        (
            "query.resource_classified_as",
            [
                "reviewed",
                "resourcetype_classification",
                "mapping",
                "native_type",
                "unclassified_state",
            ],
        ),
        (
            "query.resource_state_inventory",
            [
                "reviewed_resource_type_classification",
                "explicit_unclassified_native_types",
                "mapping_status",
            ],
        ),
    ],
)
def test_resource_classification_accepts_typed_variants(
    primary_intent: str,
    requested_facets: list[str],
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    frame = build_resource_classification_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="Inspect Resource classifications.",
        context=(),
    )

    assert frame is not None
    assert frame.subject_constraints == ("Resource",)
    assert frame.temporal_scope == {"kind": "current"}
    assert frame.execution_authority is False


@pytest.mark.parametrize(
    ("primary_intent", "requested_facets", "canonical_target"),
    [
        (
            "query.manifest",
            [
                "resource_type_classifications",
                "mapped_types",
                "unmapped_native_type",
                "keep_unclassified",
            ],
            None,
        ),
        (
            "query.resource_state_inventory",
            ["mapped_types", "unmapped_native_type", "keep_unclassified"],
            None,
        ),
        (
            "query.resource_state_inventory",
            ["resource_type_classifications", "mapped_types", "keep_unclassified"],
            None,
        ),
        (
            "query.resource_state_inventory",
            [
                "resource_type_classifications",
                "mapped_types",
                "unmapped_native_type",
                "keep_unclassified",
            ],
            "resource-a",
        ),
    ],
)
def test_resource_classification_rejects_incomplete_or_concrete_judgment(
    primary_intent: str,
    requested_facets: list[str],
    canonical_target: str | None,
) -> None:
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": primary_intent,
            "requested_facets": requested_facets,
            "targets": (
                []
                if canonical_target is None
                else [
                    {
                        "kind": "resource",
                        "value": "resource-a",
                        "canonical_value": canonical_target,
                        "source_start": 0,
                        "source_end": 10,
                    }
                ]
            ),
        }
    )

    frame = build_resource_classification_frame(
        SemanticJudgmentProposal.model_validate(judgment_data),
        utterance="resource-a classification.",
        context=(),
    )

    assert frame is None


def test_resource_classification_holds_before_generic_type_exists_plan() -> None:
    manifest, definition = _fixture(include_resource_type=True)
    model = _Model(
        frame=_frame(output_shape="property_filtered_resources"),
        plan=_plan(definition),
    )
    judgment_model = _OperatingSubjectJudgmentModel()
    judgment_model.judge = lambda **_kwargs: {
        "primary_intent": "query.resource_state_inventory",
        "targets": [],
        "requested_facets": [
            "resource_type_classifications",
            "mapped_types",
            "unmapped_native_type",
            "keep_unclassified",
        ],
        "confidence": 0.95,
        "ambiguous": False,
        "action_posture": "advise_only",
        "action_subject": "none",
        "execution_authority": False,
    }
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=judgment_model,
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=model,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Inspect Resource classifications.")

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_resource_classification_unsupported"
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Resource",)
    assert outcome.frame.temporal_scope == {"kind": "current"}
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.frame_calls == 0
    assert model.plan_calls == 0


def test_model_classification_facets_normalize_to_current_resource_frame() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["Resource", "ResourceType"],
            measure_concepts=[
                "reviewed_resource_type_classification",
                "mapping",
                "unmapped_native_types",
                "explicit_unclassified_state",
            ],
            output_shape="ontology_relationships",
        )
    )
    frame = build_semantic_frame(proposal, utterance="Inspect classifications.", context=())

    _resolved, resolved_frame = normalize_resource_classification_frame(
        proposal,
        frame,
        utterance="Inspect classifications.",
        context=(),
    )

    assert is_resource_classification_frame(resolved_frame)
    assert resolved_frame.subject_constraints == ("Resource",)
    assert resolved_frame.temporal_scope == {"kind": "current"}
    assert resolved_frame.execution_authority is False


def test_incomplete_model_classification_facets_do_not_normalize() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["Resource", "ResourceType"],
            measure_concepts=["reviewed_resource_type_classification", "mapping"],
            output_shape="ontology_relationships",
        )
    )
    frame = build_semantic_frame(proposal, utterance="Inspect classifications.", context=())

    resolved, resolved_frame = normalize_resource_classification_frame(
        proposal,
        frame,
        utterance="Inspect classifications.",
        context=(),
    )

    assert resolved is proposal
    assert resolved_frame is frame


@pytest.mark.parametrize("subject_constraints", [[], ["resource-a"]])
def test_model_classification_facets_do_not_widen_subject_scope(
    subject_constraints: list[str],
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=subject_constraints,
            measure_concepts=["resource_type_classification", "unmapped_native_types"],
            output_shape="ontology_relationships",
        )
    )
    frame = build_semantic_frame(proposal, utterance="Inspect classifications.", context=())

    resolved, resolved_frame = normalize_resource_classification_frame(
        proposal,
        frame,
        utterance="Inspect classifications.",
        context=(),
    )

    assert resolved is proposal
    assert resolved_frame is frame


@pytest.mark.parametrize(
    "measure_concepts",
    [
        ["request_path", "virtual_network_peering"],
        ["not_request_path", "next_hop", "virtual_network_peering"],
    ],
)
def test_incomplete_model_network_path_frame_is_not_normalized(
    measure_concepts: list[str],
) -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(measure_concepts=measure_concepts, output_shape="ontology_relationships")
    )
    frame = build_semantic_frame(proposal, utterance="Trace topology.", context=())

    resolved, resolved_frame = normalize_network_path_clarification(
        proposal,
        frame,
        utterance="Trace topology.",
        context=(),
        descriptors=(),
    )

    assert resolved is proposal
    assert resolved_frame is frame


def test_targetless_resource_topology_normalizes_without_value_filter() -> None:
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["PostgreSQL", "Resource", "Storage"],
            measure_concepts=[],
            output_shape="topology_graph",
        )
    )
    frame = build_semantic_frame(proposal, utterance="Inspect private topology.", context=())

    resolved, resolved_frame = normalize_network_path_clarification(
        proposal,
        frame,
        utterance="Inspect private topology.",
        context=(),
        descriptors=(),
    )

    assert resolved.operation is SemanticOperation.SELECT
    assert resolved_frame.subject_constraints == ("Resource",)
    assert resolved_frame.temporal_scope == {"kind": "current"}
    assert resolved_frame.output_shape == "ontology_relationships"
    assert resolved.clarification_requirements == (ClarificationRequirement.SUBJECT,)
    assert resolved_frame.execution_authority is False


@pytest.mark.parametrize(
    "requested_facets",
    [
        ["configuration_drift", "evidence_supporting_hypotheses"],
        ["configuration_drift", "evidence_refuting_hypotheses"],
        ["configuration_drift", "supporting_refutation"],
        [
            "configuration_drift",
            "support_not_available",
            "evidence_refuting_hypotheses",
        ],
    ],
)
def test_incomplete_configuration_drift_evidence_does_not_normalize(
    requested_facets: list[str],
) -> None:
    utterance = "Inspect configuration drift evidence."
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=["CausalHypothesis"],
            output_shape="ontology_relationships",
        )
    )
    judgment_data = _OperatingSubjectJudgmentModel().judge(
        utterance="Show the cost objective for a business service."
    )
    judgment_data.update(
        {
            "primary_intent": "query.resource_error_activity_correlation",
            "requested_facets": requested_facets,
            "targets": [],
        }
    )

    _resolved, frame = resolve_semantic_judgment_bound_read(
        proposal,
        build_semantic_frame(proposal, utterance=utterance, context=()),
        judgment=SemanticJudgmentProposal.model_validate(judgment_data),
        bound_incident=False,
        utterance=utterance,
        context=(),
    )

    assert frame.operation is SemanticOperation.SELECT
    assert frame.subject_constraints == ("CausalHypothesis",)
    assert frame.output_shape == "ontology_relationships"


def test_configuration_drift_validation_holds_before_plan_execution() -> None:
    manifest, _definition = _fixture(
        property_values=_container_app_property_values(),
        include_resource_type=True,
    )
    model = _Model(
        frame=_frame(
            operation="validate",
            subject_constraints=["Resource"],
            measure_concepts=[
                "configuration_drift",
                "evidence_supporting_hypotheses",
                "evidence_refuting_hypotheses",
            ],
            temporal_scope={"kind": "current"},
            output_shape="evidence_validation",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance="Validate configuration drift evidence for a container app.",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNAVAILABLE
    assert outcome.reason == "semantic_configuration_drift_evidence_unavailable"
    assert outcome.execution_authority is False
    assert outcome.plan is None
    assert model.plan_calls == 0


def test_bound_read_ignores_every_identity_the_frame_and_proposal_carry() -> None:
    """Only the binding may name the incident, however many the turn puts in reach."""
    manifest = _anchored_fixture()
    model = _Model(
        frame=_frame(
            output_shape="incident_evidence",
            subject_constraints=[
                "00000000-0000-0000-0000-000000000703",
                "frame-supplied-incident",
            ],
        ),
        plan=_incident_evidence_plan(
            incident_id="00000000-0000-0000-0000-000000000704",
            correlation_id="proposal-supplied-incident",
        ),
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Report what the evidence for this incident establishes.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.plan_calls == 0
    assert _incident_arguments(outcome) == {
        "incident_id": "00000000-0000-0000-0000-000000000702",
        "correlation_id": "bound-incident",
        "limit": INCIDENT_EVIDENCE_MAX_RECORDS,
    }


@pytest.mark.parametrize(
    ("incident_id", "correlation_id"),
    [
        ("", "bound-incident"),
        ("   ", "bound-incident"),
        ("00000000-0000-0000-0000-000000000702", ""),
        ("00000000-0000-0000-0000-000000000702", "   "),
    ],
)
def test_bound_incident_refuses_an_identity_it_cannot_anchor(
    incident_id: str, correlation_id: str
) -> None:
    """A blank identity would anchor the read to every incident at once."""
    with pytest.raises(ValueError):
        BoundIncident(incident_id=incident_id, correlation_id=correlation_id)


def test_unanchored_incident_frame_still_asks_the_planner() -> None:
    manifest = _anchored_fixture()
    service, model = _anchored_service(
        manifest,
        _incident_evidence_plan(
            incident_id="00000000-0000-0000-0000-000000000701",
            correlation_id="another-incident",
        ),
    )

    outcome = service.plan(
        utterance="Report what the evidence for incident 0701 establishes.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.plan_calls == 1
    assert _incident_arguments(outcome)["correlation_id"] == "another-incident"


def test_anchored_turn_about_something_else_still_asks_the_planner() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Which storage accounts allow public network access?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.plan_calls == 1
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].kind.value == "object_set"


def test_anchored_turn_never_asks_which_incident_it_is_already_anchored_to() -> None:
    manifest = _anchored_fixture()
    model = _Model(
        frame=_frame(
            output_shape="incident_evidence",
            unresolved_terms=["this incident"],
            clarification_requirements=["incident_reference"],
            clarification="Which incident should I investigate?",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="이 인시던트의 근거로 확인되는 사실을 보고해줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.clarification is None


def test_anchored_turn_still_clarifies_a_requirement_the_binding_cannot_answer() -> None:
    manifest = _anchored_fixture()
    model = _Model(
        frame=_frame(
            output_shape="incident_evidence",
            unresolved_terms=["this incident", "requests"],
            clarification_requirements=["incident_reference", "measure"],
            clarification="Do you mean HTTP requests or support requests?",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Report what this incident did to requests.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.clarification == "Do you mean HTTP requests or support requests?"


def test_anchored_turn_keeps_an_incident_question_for_another_output_shape() -> None:
    """Only a read of the anchored incident is answered by the binding."""
    manifest = _anchored_fixture()
    model = _Model(
        frame=_frame(
            output_shape="resource_list",
            unresolved_terms=["this incident"],
            clarification_requirements=["incident_reference"],
            clarification="Which incident should I investigate?",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Which resources did this incident touch?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.clarification == "Which incident should I investigate?"


def test_aggregation_frame_requires_aggregate_plan() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(operation="aggregate", output_shape="aggregation_table"),
        plan=_plan(definition),
    )
    t2 = _Model(frame=_frame(), plan=_aggregate_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Count matching resources.")

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_listing_frame_rejects_an_aggregate_plan() -> None:
    manifest, definition = _fixture()
    listing_frame = _frame(
        operation="select",
        subject_constraints=["Resource"],
        output_shape="resource_list",
    )
    t1 = _Model(frame=listing_frame, plan=_aggregate_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance="현재 범위에서 볼 수 있는 리소스 클래스를 보여 주세요.",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_aggregation_words_do_not_rewrite_a_self_consistent_select_frame() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            operation="select",
            subject_constraints=["Resource"],
            measure_concepts=["health"],
            output_shape="property_filtered_resources",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(
        frame=_frame(
            operation="aggregate",
            subject_constraints=["Resource"],
            measure_concepts=["health"],
            output_shape="aggregation_table",
        ),
        plan=_aggregate_plan(definition),
    )
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="Group resources by health.")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.SELECT
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    "utterance",
    (
        "Group readable resources by health status.",
        "읽기 가능한 리소스를 상태별로 그룹화해 주세요.",
        "읽기 가능한 리소스를 상태별로 그루핑해 주세요.",
        "조회 가능한 리소스의 상태별 합계를 보여 주세요.",
    ),
)
def test_aggregation_words_do_not_lexically_veto_a_verified_select_frame(
    utterance: str,
) -> None:
    manifest, definition = _fixture()
    invalid_frame = _frame(
        operation="select",
        subject_constraints=["Resource"],
        measure_concepts=["type"],
        output_shape="property_filtered_resources",
    )
    t1 = _Model(frame=invalid_frame, plan=_plan(definition))
    t2 = _Model(frame=invalid_frame, plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest), utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.operation is SemanticOperation.SELECT
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    "utterance",
    (
        "Show resources with a declared type.",
        "Find the network security group rule.",
    ),
)
def test_nonaggregation_request_does_not_require_an_aggregate_frame(
    utterance: str,
) -> None:
    manifest, definition = _fixture()
    frame = _frame(output_shape="property_filtered_resources")
    t1 = _Model(frame=frame, plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(
        _service(t1, t2, manifest),
        utterance=utterance,
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    "utterance",
    (
        "Show ontology objects in the current inventory generation.",
        "현재 인벤토리 세대의 온톨로지 객체를 보여 주세요.",
    ),
)
def test_listing_words_do_not_lexically_veto_a_verified_aggregate_frame(
    utterance: str,
) -> None:
    manifest, definition = _fixture()
    invalid_frame = _frame(
        operation="aggregate",
        subject_constraints=["Resource"],
        measure_concepts=["count"],
        output_shape="aggregation_table",
    )
    t1 = _Model(frame=invalid_frame, plan=_aggregate_plan(definition))
    t2 = _Model(frame=invalid_frame, plan=_aggregate_plan(definition))

    outcome = _run(_service(t1, t2, manifest), utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    "utterance",
    (
        "Show the number of visible resources by class.",
        "조회 가능한 리소스의 클래스별 합계를 보여 주세요.",
    ),
)
def test_listing_word_does_not_override_an_explicit_aggregation_request(
    utterance: str,
) -> None:
    manifest, definition = _fixture()
    aggregate_frame = _frame(operation="aggregate", output_shape="aggregation_table")
    t1 = _Model(frame=aggregate_frame, plan=_aggregate_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    ("operation", "output_shape"),
    (
        ("select", "aggregation_table"),
        ("aggregate", "property_filtered_resources"),
    ),
)
def test_aggregation_operation_and_output_shape_must_match(
    operation: str,
    output_shape: str,
) -> None:
    manifest, definition = _fixture()
    invalid_frame = _frame(operation=operation, output_shape=output_shape)
    t1 = _Model(frame=invalid_frame, plan=_plan(definition))
    t2 = _Model(frame=invalid_frame, plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_manifest_function_may_feed_declaration_aggregate_output() -> None:
    manifest, definition = _fixture()
    aggregate_plan = _manifest_aggregate_plan()
    t1 = _Model(
        frame=_frame(
            operation="aggregate",
            subject_constraints=["object"],
            measure_concepts=["count"],
            output_shape="aggregation_table",
        ),
        plan=aggregate_plan,
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="How many object declarations are available?")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_manifest_declaration_count_uses_server_owned_plan() -> None:
    manifest, definition = _fixture(function_types=(ontology_manifest_function_type(),))
    frame = _frame(
        operation="aggregate",
        subject_constraints=["action"],
        measure_concepts=["count"],
        output_shape="aggregation_table",
    )
    t1 = _Model(frame=frame, plan=None)
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(QueryNodeKind.FUNCTION, QueryNodeKind.AGGREGATE),
        ),
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="How many action declarations are available?")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["arguments"]["kinds"] == ["action"]
    assert outcome.plan.nodes[1].arguments["group_by"] == ["kind"]
    assert outcome.plan.output_node_ids == ("declaration-count",)
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    ("judgment_target", "include_domain_target", "frame_subjects"),
    (
        (None, False, ("ActionType", "Ontology")),
        ("ActionTypes", False, ("LinkType",)),
        ("ActionTypes", True, ("LinkType",)),
    ),
)
def test_manifest_count_normalizes_the_validated_declaration_intent(
    judgment_target: str | None,
    include_domain_target: bool,
    frame_subjects: tuple[str, ...],
) -> None:
    class _DeclarationCountJudgmentModel:
        def judge(self, *, utterance: str, **_kwargs: Any) -> dict[str, object]:
            targets: list[dict[str, object]] = []
            if judgment_target is not None:
                source_start = utterance.index(judgment_target)
                targets.append(
                    {
                        "kind": "object_type",
                        "value": judgment_target,
                        "canonical_value": "ActionType",
                        "source_start": source_start,
                        "source_end": source_start + len(judgment_target),
                    }
                )
            if include_domain_target:
                value = "ontology"
                source_start = utterance.index(value)
                targets.append(
                    {
                        "kind": "question_domain",
                        "value": value,
                        "canonical_value": value,
                        "source_start": source_start,
                        "source_end": source_start + len(value),
                    }
                )
            return {
                "primary_intent": "query.ontology_declaration",
                "targets": targets,
                "requested_facets": [
                    "count",
                    "visibility",
                    "read_only_verification_source",
                    "scope",
                ],
                "confidence": 0.95,
                "ambiguous": False,
                "action_posture": "advise_only",
                "action_subject": "none",
                "execution_authority": False,
            }

    manifest, definition = _fixture(function_types=(ontology_manifest_function_type(),))
    frame = _frame(
        operation="aggregate",
        subject_constraints=list(frame_subjects),
        measure_concepts=["count", "visibility", "read_only_verification_source", "scope"],
        temporal_scope={"kind": "current"},
        output_shape="aggregation_table",
    )
    t1 = _Model(frame=frame, plan=None)
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    judgment = SemanticJudgmentBoundary(
        profile_id="semantic-planning.test",
        profile_version="1.0.0",
        primary=SemanticJudgmentBinding(
            tier=SemanticJudgmentTier.T1,
            model=_DeclarationCountJudgmentModel(),
            model_config_digest=DIGEST,
            prompt_digest=DIGEST,
        ),
    )
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        semantic_judgment=judgment,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(QueryNodeKind.FUNCTION, QueryNodeKind.AGGREGATE),
        ),
        now=lambda: NOW,
    )

    outcome = _run(
        service,
        utterance="How many ActionTypes are currently visible in this ontology scope?",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("action",)
    assert outcome.frame.measure_concepts == ("count",)
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["arguments"]["kinds"] == ["action"]
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_manifest_aggregate_kinds_are_bound_to_frame_subjects() -> None:
    manifest, _definition = _fixture()
    frame = _frame(
        operation="aggregate",
        subject_constraints=["object"],
        measure_concepts=["count"],
        output_shape="aggregation_table",
    )
    t1 = _Model(frame=frame, plan=_manifest_aggregate_plan(kinds=("action",)))
    t2 = _Model(frame=frame, plan=_manifest_aggregate_plan())
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance="How many object declarations are available?")

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["arguments"]["kinds"] == ["object"]
    assert (t1.plan_calls, t2.plan_calls) == (1, 0)


@pytest.mark.parametrize(
    ("utterance", "subject"),
    (
        ("현재 열려 있는 인시던트가 몇 건이야?", "Incident"),
        ("감사 로그 전체 행 수가 몇 개야?", "audit_log"),
        ("감사 로그에 기록된 전체 행 수를 세어줘", "audit_log"),
    ),
)
def test_operational_count_never_aggregates_the_declaration_manifest(
    utterance: str,
    subject: str,
) -> None:
    manifest, _definition = _fixture()
    frame = _frame(
        operation="aggregate",
        subject_constraints=[subject],
        measure_concepts=["count"],
        output_shape="aggregation_table",
    )
    aggregate_plan = _manifest_aggregate_plan()
    t1 = _Model(frame=frame, plan=aggregate_plan)
    t2 = _Model(frame=frame, plan=aggregate_plan)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service, utterance=utterance)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.plan is None
    assert (t1.plan_calls, t2.plan_calls) == (1, 0)


def test_property_filter_frame_requires_object_set_predicate() -> None:
    manifest, definition = _fixture()
    unfiltered = definition.model_copy(update={"predicates": ()})
    t1 = _Model(
        frame=_frame(output_shape="property_filtered_resources"),
        plan=_plan(unfiltered),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_property_filter_binds_missing_exact_frame_property() -> None:
    manifest, definition = _fixture(include_resource_type=True)
    unfiltered = definition.model_copy(update={"predicates": ()})
    t1 = _Model(
        frame=_frame(
            output_shape="property_filtered_resources",
            subject_constraints=["Resource"],
            measure_concepts=["type"],
        ),
        plan=_plan(unfiltered),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {"property": "type", "operator": "exists"}
    ]
    assert (t1.plan_calls, t2.plan_calls) == (1, 0)


@pytest.mark.parametrize("measure_concepts", (["id"], ["type", "id"]))
def test_property_filter_does_not_bind_a_nonclosed_frame(
    measure_concepts: list[str],
) -> None:
    manifest, definition = _fixture(include_resource_type=True)
    unfiltered = definition.model_copy(update={"predicates": ()})
    t1 = _Model(
        frame=_frame(
            output_shape="property_filtered_resources",
            subject_constraints=["Resource"],
            measure_concepts=measure_concepts,
        ),
        plan=_plan(unfiltered),
    )
    t2 = _Model(frame=_frame(), plan=_plan(unfiltered))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert (t1.plan_calls, t2.plan_calls) == (1, 0)


def test_scope_denial_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    hidden = definition.model_copy(
        update={"predicates": (ObjectPredicate(property="secret", equals="value"),)}
    )
    t1 = _Model(frame=_frame(), plan=_plan(hidden))
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_scope_denied"
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


async def test_evidence_execution_hold_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    runtime = SemanticConversationRuntime(
        planner=_service(t1, t2, manifest),
        executor=OntologyQueryPlanExecutor(handlers={}, now=lambda: NOW),
    )

    result = await runtime.handle(
        utterance="Show matching resources",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )

    assert result.disposition == "held"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_composition_separates_t1_and_t2_candidates() -> None:
    resolved = ResolvedModels(
        schema_version="1.0.0",
        region="example-region",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000000",
        mixed_model_mode="hil-only",
        capabilities=(
            ResolvedCapability(
                name="t1.judge",
                status=CapabilityStatus.RESOLVED,
                publisher="OpenAI",
                family="gpt-5.4-mini",
                sku="Standard",
                capacity_tpm=1000,
                invocation="always",
            ),
            ResolvedCapability(
                name="t2.reasoner.primary",
                status=CapabilityStatus.RESOLVED,
                publisher="OpenAI",
                family="gpt-4.1",
                sku="Standard",
                capacity_tpm=1000,
                invocation="always",
            ),
            ResolvedCapability(
                name="t2.reasoner.secondary",
                status=CapabilityStatus.RESOLVED,
                publisher="Anthropic",
                family="claude-opus-4",
                sku="Standard",
                capacity_tpm=1000,
                invocation="always",
            ),
        ),
        narrator_candidates=(
            NarratorCandidate(
                endpoint="https://models.example.com",
                deployment="narrator-gpt-5-4-mini",
            ),
        ),
    )

    t1 = t1_model_targets(resolved, endpoint="https://models.example.com", endpoint_resolver=None)
    t2 = t2_model_targets(resolved, endpoint="https://models.example.com", endpoint_resolver=None)

    assert [target.deployment for target in t1] == ["narrator-gpt-5-4-mini"]
    assert [target.deployment for target in t2] == ["t2.reasoner.primary"]
