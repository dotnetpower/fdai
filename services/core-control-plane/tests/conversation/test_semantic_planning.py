"""Schema-constrained semantic planning and intent graph tests."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest
from fdai.core.conversation.conversation_preflight import (
    ContextDependency,
    ConversationPreflightProposal,
    ConversationPreflightResult,
    OperationalPreflightFamily,
    OperationalSignal,
    SocialAct,
)
from fdai.core.conversation.coordinator import ConversationCoordinator, CoordinatorConfig
from fdai.core.conversation.intent_graph import (
    build_intent_graph_evidence,
    resolve_execution_authority,
)
from fdai.core.conversation.semantic_judgment import SemanticJudgmentObservation
from fdai.core.conversation.semantic_manifest import CatalogQueryManifestProvider
from fdai.core.conversation.semantic_planning import (
    SemanticPlanningService,
    _descriptors_for_judgment,
    _plan_node_summary,
)
from fdai.core.conversation.semantic_planning_alignment import verify_frame_plan_alignment
from fdai.core.conversation.semantic_planning_frame_checks import (
    _normalize_gateway_diagnostic_time_scope,
    deterministic_pre_frame_outcome,
)
from fdai.core.conversation.semantic_planning_frame_core import build_semantic_frame
from fdai.core.conversation.semantic_planning_models import (
    BoundResourceContext,
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningDisposition,
    SemanticPlanningModelResponse,
)
from fdai.core.conversation.semantic_resource_state_planning import (
    normalize_resource_state_proposal,
)
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import ConversationSession, Principal, Role, Turn
from fdai.core.conversation.tools import ToolResult
from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectPredicateOperator,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanExecutor,
    OntologyQueryPlanVerifier,
    QueryNodeResult,
    QueryPlanExecution,
    build_query_manifest,
)
from fdai.core.ontology_platform.contextual_resource_queries import (
    contextual_resource_function_type,
)
from fdai.core.ontology_platform.governed_document_queries import (
    GOVERNED_DOCUMENT_FUNCTION_NAME,
    governed_document_function_type,
)
from fdai.core.ontology_platform.property_values import PropertyValueDomain, PropertyValueGroup
from fdai.core.ontology_platform.query_execution import QueryNodeProgress
from fdai.core.ontology_platform.resource_event_queries import (
    RESOURCE_EVENT_FUNCTION_NAME,
    resource_event_function_type,
)
from fdai.core.ontology_platform.resource_health_queries import (
    RESOURCE_HEALTH_FUNCTION_NAME,
    resource_health_function_type,
)
from fdai.core.ontology_platform.resource_metric_queries import (
    RESOURCE_METRIC_FUNCTION_NAME,
    resource_metric_function_type,
)
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    RESOURCE_STATE_OBSERVED_CONCEPT,
    resource_state_function_type,
)
from fdai.core.ontology_platform.service_health_queries import (
    SERVICE_HEALTH_FUNCTION_NAME,
    SERVICE_HEALTH_MEASURE_CONCEPTS,
    service_health_function_type,
)
from fdai.core.ontology_platform.state_transitions import (
    RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
    resource_state_transitions_function_type,
)
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    QueryEvidenceAuthority,
    QueryTerms,
    QueryValues,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts import context_selection_digest
from fdai_service_contracts.ontology_query import (
    EvidenceAuthority,
    GoalEvidenceMode,
    GoalTaskReceipt,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    TaskStatus,
    canonical_json,
    content_digest,
)
from fdai_service_contracts.semantic_judgment import (
    SemanticDocumentEvidenceMode,
    SemanticJudgmentProposal,
    SemanticTarget,
)
from pydantic import ValidationError

DIGEST = "sha256:" + ("a" * 64)
NOW = datetime(2026, 8, 10, tzinfo=UTC)


class _ManifestProvider:
    def __init__(self, manifest: Any) -> None:
        self.manifest = manifest

    def manifest_for(self, *, principal: Principal, purpose: str):  # type: ignore[no-untyped-def]
        assert principal.role is Role.READER
        assert purpose == "operations-review"
        return self.manifest


class _Model:
    def __init__(self, *, frame: dict[str, object], plan: dict[str, object] | None) -> None:
        self.frame = frame
        self.plan = plan
        self.frame_calls = 0
        self.plan_calls = 0
        self.utterance = ""

    def propose_frame(self, **kwargs: Any) -> dict[str, object]:
        self.frame_calls += 1
        self.utterance = kwargs["utterance"]
        descriptors = kwargs["descriptors"]
        descriptors[0]["name"] = "mutated-copy"
        return self.frame

    def propose_plan(self, **kwargs: Any) -> dict[str, object] | None:
        self.plan_calls += 1
        return self.plan


class _InventoryTool:
    name = "query_inventory"
    description = "read inventory"
    rbac_floor = Role.READER
    side_effect_class = "read"

    def call(self, **_kwargs: Any) -> ToolResult:
        return ToolResult(status="ok", preview="inventory result")


def _fixture() -> tuple[Any, ObjectSetDefinition]:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "secret": PropertyDecl(
                type=PropertyType.STRING,
                access_scope=CeilingRole.OWNER,
            ),
        },
    )
    release = build_ontology_release(object_types=(resource,))
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
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
        "investigation": None,
        "clarification": None,
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


def _service(
    model: _Model,
    manifest: Any,
    *,
    inventory_query_language: InventoryQueryLanguageRegistry | None = None,
    metric_concepts: tuple[str, ...] = (),
    semantic_judgment: Any = None,
) -> SemanticPlanningService:
    return SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(QueryNodeKind.OBJECT_SET, QueryNodeKind.FUNCTION)
        ),
        now=lambda: NOW,
        inventory_query_language=inventory_query_language,
        metric_concepts=metric_concepts,
        semantic_judgment=semantic_judgment,
    )


class _JudgmentBoundary:
    def __init__(self, proposal: SemanticJudgmentProposal) -> None:
        self._proposal = proposal

    def preflight(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            observations=(),
            failure_kind=None,
            proposal=None,
        )

    def judge(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            accepted=True,
            observations=(),
            proposal=self._proposal,
            receipt=SimpleNamespace(
                disposition=SimpleNamespace(value="accepted"),
                tier=SimpleNamespace(value="t1"),
            ),
        )


def test_whole_turn_model_proposal_becomes_verified_server_owned_plan() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="현재 선택된 대상과 의미상 같은 운영 객체를 보여줘",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.execution_authority is False
    assert outcome.frame is not None and outcome.plan is not None
    assert outcome.frame.input_digest.startswith("sha256:")
    assert outcome.plan.ontology_release_digest == manifest.release_digest
    assert outcome.intent_graph is not None
    assert outcome.intent_graph.goals[0].goal_id == "goal-1"
    assert outcome.intent_graph.goals[0].arguments["definition"]["purpose"] == "operations-review"
    assert model.utterance.startswith("현재")
    assert manifest.descriptors[0]["name"] == "Resource"


def test_planning_model_observations_cover_frame_and_plan_calls() -> None:
    manifest, definition = _fixture()

    class ObservedModel(_Model):
        def propose_frame(self, **kwargs: Any) -> SemanticPlanningModelResponse:
            proposal = super().propose_frame(**kwargs)
            return SemanticPlanningModelResponse(
                proposal=proposal,
                observation=SemanticJudgmentObservation(
                    model="planning-model",
                    usage=None,
                    trace_call={
                        "kind": "semantic-planning-frame",
                        "duration_ms": 11,
                        "redacted": True,
                    },
                ),
            )

        def propose_plan(self, **kwargs: Any) -> SemanticPlanningModelResponse:
            proposal = super().propose_plan(**kwargs)
            assert proposal is not None
            return SemanticPlanningModelResponse(
                proposal=proposal,
                observation=SemanticJudgmentObservation(
                    model="planning-model",
                    usage=None,
                    trace_call={
                        "kind": "semantic-planning-plan",
                        "duration_ms": 13,
                        "redacted": True,
                    },
                ),
            )

    outcome = _service(
        ObservedModel(frame=_frame(), plan=_plan(definition)),
        manifest,
    ).plan(
        utterance="Show current resources.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert [item.trace_call["kind"] for item in outcome.model_observations] == [
        "semantic-planning-frame",
        "semantic-planning-plan",
    ]


def test_object_set_cutoff_is_rebound_to_trusted_server_time() -> None:
    manifest, definition = _fixture()
    stale = definition.model_copy(update={"as_of": datetime(2020, 1, 1, tzinfo=UTC)})
    model = _Model(frame=_frame(), plan=_plan(stale))

    outcome = _service(model, manifest).plan(
        utterance="Show current resources.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.plan is not None
    definition_json = outcome.plan.nodes[0].arguments["definition"]
    assert definition_json["as_of"] == NOW.isoformat()


def test_object_set_cutoff_is_refreshed_after_model_planning() -> None:
    manifest, definition = _fixture()
    execution_time = NOW + timedelta(seconds=10)
    clock_reads = iter((NOW, execution_time))
    model = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        now=lambda: next(clock_reads),
    )

    outcome = service.plan(
        utterance="Show current resources.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.plan is not None
    definition_json = outcome.plan.nodes[0].arguments["definition"]
    assert definition_json["as_of"] == execution_time.isoformat()


def test_unresolved_meaning_returns_one_clarification_without_plan() -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            unresolved_terms=["requests"],
            clarification_requirements=["measure"],
            clarification="Do you mean HTTP requests or support requests?",
        ),
        plan=_plan(definition),
    )

    outcome = _service(model, manifest).plan(
        utterance="Why did requests increase?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.clarification == "Do you mean HTTP requests or support requests?"
    assert outcome.plan is None
    assert model.plan_calls == 0


def test_resource_list_clears_a_contradictory_resource_identity_clarification() -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            temporal_scope={"kind": "historical"},
            unresolved_terms=["resource_identity"],
            clarification_requirements=["resource_identity"],
            clarification="Please clarify these unresolved concepts: resource_identity?",
        ),
        plan=_plan(definition),
    )

    outcome = _service(model, manifest).plan(
        utterance="이 구독의 리소스를 모두 보여줘",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == SemanticOutputShape.RESOURCE_LIST
    assert outcome.frame.unresolved_terms == ()
    assert outcome.plan is not None


@pytest.mark.parametrize(
    "utterance",
    [
        "Investigate this incident and report the cause, gaps, and next safe step.",
        "이 인시던트의 근거로 확인되는 사실과 다음 안전한 조치를 보고해줘.",
    ],
)
def test_unbound_incident_reference_clarifies_through_the_typed_frame(utterance: str) -> None:
    """Both locales reach one disposition; no utterance substring decides a route."""
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            unresolved_terms=["this incident"],
            clarification_requirements=["incident_reference"],
            clarification="Which incident should I investigate?",
        ),
        plan=_plan(definition),
    )

    outcome = _service(model, manifest).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.reason == "semantic_clarification_required"
    assert outcome.clarification == "Which incident should I investigate?"
    assert outcome.plan is None
    assert outcome.execution_authority is False
    assert model.plan_calls == 0


def test_incident_reference_with_prior_context_reaches_semantic_planning() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance=(
            "Investigate this incident using the available evidence and report the cause, "
            "gaps, and next safe step."
        ),
        prior_turns=(
            Turn(
                turn_id="incident-context",
                direction="system",
                content="Selected incident: incident-42.",
            ),
        ),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.execution_authority is False
    assert model.frame_calls == 1
    assert model.plan_calls == 1


@pytest.mark.parametrize(
    ("utterance", "expected"),
    (
        (
            "Why does this change need human approval, and who approves it?",
            "Which change do you mean? Provide its change ID or exact target?",
        ),
        (
            "이 변경에 사람 승인이 필요한 이유와 승인자를 알려줘.",
            "어떤 변경을 말하는지 변경 ID나 정확한 대상을 알려주세요?",
        ),
    ),
)
def test_first_turn_change_reference_clarifies_before_model(
    utterance: str,
    expected: str,
) -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            unresolved_terms=["change_reference"],
            clarification_requirements=["subject"],
            clarification=expected,
        ),
        plan=_plan(definition),
    )

    outcome = _service(model, manifest).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.reason == "semantic_clarification_required"
    assert outcome.clarification == expected
    assert outcome.execution_authority is False
    assert (model.frame_calls, model.plan_calls) == (1, 0)


def test_change_reference_with_prior_context_reaches_semantic_planning() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="Why does this change need approval?",
        prior_turns=(
            Turn(
                turn_id="change-context",
                direction="system",
                content="Selected change: change-42.",
            ),
        ),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (model.frame_calls, model.plan_calls) == (1, 1)


def test_generic_changes_question_does_not_trigger_demonstrative_clarification() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="Show changes from the last hour.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.frame_calls == 1


@pytest.mark.parametrize(
    ("utterance", "expected"),
    (
        (
            "Cancel the ongoing investigation and tell me what scope stopped.",
            "Which investigation should I cancel? Provide its exact investigation ID?",
        ),
        (
            "진행 중인 조사를 취소하고 중단된 범위를 알려줘.",
            "어떤 조사를 취소할지 정확한 조사 ID를 알려주세요?",
        ),
    ),
)
def test_first_turn_investigation_cancellation_requires_exact_identity(
    utterance: str,
    expected: str,
) -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            unresolved_terms=["investigation_reference"],
            clarification_requirements=["subject"],
            clarification=expected,
        ),
        plan=_plan(definition),
    )

    outcome = _service(model, manifest).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.reason == "semantic_clarification_required"
    assert outcome.clarification == expected
    assert outcome.execution_authority is False
    assert (model.frame_calls, model.plan_calls) == (1, 0)


def test_investigation_cancellation_with_prior_context_reaches_planning() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="Cancel the ongoing investigation.",
        prior_turns=(
            Turn(
                turn_id="investigation-context",
                direction="system",
                content="Selected investigation: investigation-42.",
            ),
        ),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (model.frame_calls, model.plan_calls) == (1, 1)


def test_investigation_cancellation_with_exact_id_reaches_planning() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="Cancel investigation-42.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.frame_calls == 1


@pytest.mark.parametrize(
    ("utterance", "expected"),
    (
        (
            "Separate verified facts from limitations when one data source fails.",
            "Which event or request should I review, and which data source failed?",
        ),
        (
            "한 데이터 원본이 실패해도 확인된 사실과 한계를 구분해줘.",
            "어떤 사건이나 요청을 검토할지와 실패한 데이터 원본을 알려주세요?",
        ),
    ),
)
def test_first_turn_failed_source_request_requires_event_and_source_context(
    utterance: str,
    expected: str,
) -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            unresolved_terms=["event_reference", "failed_source"],
            clarification_requirements=["subject", "measure"],
            clarification=expected,
        ),
        plan=_plan(definition),
    )

    outcome = _service(model, manifest).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.reason == "semantic_clarification_required"
    assert outcome.clarification == expected
    assert outcome.execution_authority is False
    assert (model.frame_calls, model.plan_calls) == (1, 0)


def test_failed_source_request_with_prior_context_reaches_planning() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="Separate verified facts from limitations when one data source fails.",
        prior_turns=(
            Turn(
                turn_id="source-context",
                direction="system",
                content="Selected incident incident-42; metrics source failed.",
            ),
        ),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (model.frame_calls, model.plan_calls) == (1, 1)


def test_partial_source_question_does_not_trigger_failed_source_clarification() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="Show data source limitations.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.frame_calls == 1


@pytest.mark.parametrize(
    ("utterance", "expected"),
    (
        (
            "Verify the mitigation outcome against explicit recovery criteria.",
            (
                "Which mitigation and exact target should I verify, and what recovery criteria "
                "should I use?"
            ),
        ),
        (
            "완화 결과를 명시된 복구 기준에 따라 검증해줘.",
            "검증할 완화 조치와 정확한 대상, 적용할 복구 기준을 알려주세요?",
        ),
        (
            "Check whether the mitigation result meets the recovery criterion.",
            (
                "Which mitigation and exact target should I verify, and what recovery criteria "
                "should I use?"
            ),
        ),
        (
            "완화 조치가 복구 기준을 충족하는지 평가해줘.",
            "검증할 완화 조치와 정확한 대상, 적용할 복구 기준을 알려주세요?",
        ),
    ),
)
def test_first_turn_recovery_verification_requires_mitigation_target_and_criteria(
    utterance: str,
    expected: str,
) -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            unresolved_terms=["mitigation", "target", "recovery_criteria"],
            clarification_requirements=["subject", "measure", "comparison_baseline"],
            clarification=expected,
        ),
        plan=_plan(definition),
    )

    outcome = _service(model, manifest).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.reason == "semantic_clarification_required"
    assert outcome.clarification == expected
    assert outcome.execution_authority is False
    assert (model.frame_calls, model.plan_calls) == (1, 0)


def test_recovery_verification_with_prior_context_reaches_planning() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="Verify the mitigation outcome against explicit recovery criteria.",
        prior_turns=(
            Turn(
                turn_id="recovery-context",
                direction="system",
                content=(
                    "Selected mitigation change-42 for service-42; recover when error rate "
                    "stays below 1 percent for 30 minutes."
                ),
            ),
        ),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (model.frame_calls, model.plan_calls) == (1, 1)


def test_generic_recovery_history_does_not_trigger_criteria_clarification() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="Show recovery history for recent deployments.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.frame_calls == 1


def test_recovery_criteria_listing_does_not_trigger_verification_clarification() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="List mitigation outcomes and recovery criteria.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.frame_calls == 1


@pytest.mark.parametrize(
    ("utterance", "expected"),
    (
        (
            "Recommend the runbook with exact citations.",
            (
                "Which incident or exact target is this recommendation for, and which approved "
                "runbook source should I search?"
            ),
        ),
        (
            "Suggest a playbook with references.",
            (
                "Which incident or exact target is this recommendation for, and which approved "
                "runbook source should I search?"
            ),
        ),
        (
            "정확한 출처와 함께 런북을 추천해줘.",
            "어떤 사건이나 정확한 대상을 위한 추천인지와 검색할 승인된 런북 원본을 알려주세요?",
        ),
    ),
)
def test_first_turn_cited_runbook_recommendation_requires_target_and_source(
    utterance: str,
    expected: str,
) -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            unresolved_terms=["recommendation_target", "approved_source"],
            clarification_requirements=["subject", "measure"],
            clarification=expected,
        ),
        plan=_plan(definition),
    )

    outcome = _service(model, manifest).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.reason == "semantic_clarification_required"
    assert outcome.clarification == expected
    assert outcome.execution_authority is False
    assert (model.frame_calls, model.plan_calls) == (1, 0)


def test_cited_runbook_recommendation_with_prior_context_reaches_planning() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="Recommend the runbook with exact citations.",
        prior_turns=(
            Turn(
                turn_id="runbook-context",
                direction="system",
                content=(
                    "Selected incident incident-42 for service-42; search the approved SRE "
                    "runbook collection."
                ),
            ),
        ),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (model.frame_calls, model.plan_calls) == (1, 1)


def test_runbook_listing_without_citation_request_reaches_planning() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance="List available runbooks.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.frame_calls == 1


def test_frame_proposal_rejects_noncanonical_evidence_requirement() -> None:
    with pytest.raises(ValidationError):
        SemanticFrameProposal.model_validate(
            _frame(evidence_requirements=["read only configuration evidence"])
        )


def test_frame_proposal_rejects_free_form_output_shape() -> None:
    with pytest.raises(ValidationError):
        SemanticFrameProposal.model_validate(_frame(output_shape="whatever_the_model_wants"))


def test_model_cannot_select_server_owned_target_candidates() -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(output_shape="resource_target_candidates"),
        plan=_plan(definition),
    )

    outcome = _service(model, manifest).plan(
        utterance="Show possible targets.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.plan is None
    assert outcome.execution_authority is False
    assert model.plan_calls == 0


def _typed_fixture(
    *,
    groups: tuple[PropertyValueGroup, ...],
    extra_values: tuple[str, ...] = (),
    include_resource_health: bool = False,
    include_resource_event: bool = False,
    include_resource_metric: bool = False,
    include_resource_state: bool = False,
    include_state_transitions: bool = False,
    include_service_health: bool = False,
    include_contextual_resource: bool = False,
    include_governed_document: bool = False,
    include_parent_id: bool = False,
) -> tuple[Any, ObjectSetDefinition]:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "type": PropertyDecl(type=PropertyType.STRING, required=True),
            "name": PropertyDecl(type=PropertyType.STRING),
            **({"parent_id": PropertyDecl(type=PropertyType.STRING)} if include_parent_id else {}),
        },
    )
    function_types = tuple(
        function
        for function in (
            contextual_resource_function_type() if include_contextual_resource else None,
            governed_document_function_type() if include_governed_document else None,
            resource_event_function_type() if include_resource_event else None,
            resource_health_function_type() if include_resource_health else None,
            resource_metric_function_type() if include_resource_metric else None,
            resource_state_function_type() if include_resource_state else None,
            resource_state_transitions_function_type() if include_state_transitions else None,
            service_health_function_type() if include_service_health else None,
        )
        if function is not None
    )
    release = build_ontology_release(
        object_types=(resource,),
        function_types=function_types,
    )
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
        functions=function_types,
        bound_function_names=tuple(function.name for function in function_types),
        property_values=(
            PropertyValueDomain(
                object_type="Resource",
                property_name="type",
                values=tuple(
                    sorted(
                        {"compute.vm", "resource-group", "storage.account"}
                        | {value for group in groups for value in group.values}
                        | set(extra_values)
                    )
                ),
                groups=groups,
            ),
        ),
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(ObjectPredicate(property="type", operator=ObjectPredicateOperator.EXISTS),),
        as_of=NOW,
        purpose="operations-review",
        limit=1000,
    )
    return manifest, definition


_RESOURCE_GROUP_GROUP = PropertyValueGroup(
    id="resource-group",
    values=("resource-group",),
    terms=("resource group", "resource groups", "리소스 그룹", "리소스그룹"),
)
_VM_GROUP = PropertyValueGroup(
    id="compute-vm",
    values=("compute.vm",),
    terms=("vm", "가상 머신"),
)
_POSTGRES_GROUP = PropertyValueGroup(
    id="postgresql-server",
    values=("postgresql-server",),
    terms=("postgres", "postgres db", "postgresql"),
)


def _inventory_query_language() -> InventoryQueryLanguageRegistry:
    return InventoryQueryLanguageRegistry(
        schema_version="1.1.0",
        version="1.1.0",
        default_scope="subscription",
        default_activity_lookback_seconds=604800,
        current_requires_fresh=True,
        suffixes=("를",),
        signals={
            "service_health_advisory": QueryTerms(
                terms=("health advisory", "health advisories", "상태 권고")
            )
        },
        query_kinds={},
        groupings={},
        projections={},
        scopes={"subscription": QueryTerms(terms=("subscription", "우리 구독"))},
        states={
            "inactive": QueryValues(
                terms=("not running", "실행 중이 아닌", "실행 중이 아니"),
                values=("stopped", "deallocated"),
            ),
            "not_ready": QueryValues(
                terms=("not ready", "준비되지 않은"),
                values=("failed", "degraded", "unavailable"),
                evidence_authority=QueryEvidenceAuthority.SUBSCRIPTION_HEALTH,
            ),
            "running": QueryValues(
                terms=("running", "실행 중"),
                values=("running",),
            ),
            "stopped": QueryValues(
                terms=("stopped", "중지된"),
                values=("stopped", "deallocated"),
            ),
        },
        operations={},
        time_units={},
    )


def _summary_judgment(
    primary_intent: str,
    *,
    secondary_intents: tuple[str, ...] = (),
) -> SemanticJudgmentProposal:
    return SemanticJudgmentProposal(
        primary_intent=primary_intent,
        secondary_intents=secondary_intents,
        targets=(),
        requested_facets=(),
        confidence=0.76,
        ambiguous=False,
        alternatives=(),
        unresolved_terms=(),
        clarification=None,
        direct_response=None,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )


@pytest.mark.parametrize(
    ("utterance", "primary_intent", "secondary_intents", "output_shape"),
    (
        (
            "Show resources that are currently not running.",
            RESOURCE_STATE_FUNCTION_NAME,
            (),
            "resource_state_list",
        ),
        (
            "현재 실행 중이 아닌 리소스를 보여줘.",
            RESOURCE_STATE_FUNCTION_NAME,
            (),
            "resource_state_list",
        ),
        (
            "Show resources that are currently not running or not ready.",
            RESOURCE_STATE_FUNCTION_NAME,
            (RESOURCE_HEALTH_FUNCTION_NAME,),
            "resource_condition_sections",
        ),
        (
            "실행 중이 아니거나 준비되지 않은 리소스를 보여줘.",
            RESOURCE_STATE_FUNCTION_NAME,
            (RESOURCE_HEALTH_FUNCTION_NAME,),
            "resource_condition_sections",
        ),
        (
            "Show resources that are currently not ready.",
            RESOURCE_HEALTH_FUNCTION_NAME,
            (),
            "resource_health_list",
        ),
        (
            "현재 준비되지 않은 리소스를 보여줘.",
            RESOURCE_HEALTH_FUNCTION_NAME,
            (),
            "resource_health_list",
        ),
        (
            "Show PostgreSQL databases that are currently not running.",
            RESOURCE_STATE_FUNCTION_NAME,
            (),
            "resource_state_list",
        ),
        (
            "현재 실행 중이 아닌 PostgreSQL 데이터베이스를 보여줘.",
            RESOURCE_STATE_FUNCTION_NAME,
            (),
            "resource_state_list",
        ),
        (
            "Show current service-health advisories for the authorized subscription.",
            SERVICE_HEALTH_FUNCTION_NAME,
            (),
            "subscription_service_health",
        ),
        (
            "권한이 있는 구독의 현재 서비스 상태 권고를 보여줘.",
            SERVICE_HEALTH_FUNCTION_NAME,
            (),
            "subscription_service_health",
        ),
    ),
)
def test_function_backed_starter_skips_frame_model(
    utterance: str,
    primary_intent: str,
    secondary_intents: tuple[str, ...],
    output_shape: str,
) -> None:
    manifest, _definition = _typed_fixture(
        groups=(_POSTGRES_GROUP,),
        include_resource_health=True,
        include_resource_state=True,
        include_service_health=True,
    )
    model = _Model(frame=_frame(), plan=None)
    outcome = _service(
        model,
        manifest,
        inventory_query_language=_inventory_query_language(),
        semantic_judgment=_JudgmentBoundary(
            _summary_judgment(
                primary_intent,
                secondary_intents=secondary_intents,
            )
        ),
    ).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None and outcome.frame.output_shape == output_shape
    assert outcome.plan is not None
    assert outcome.execution_authority is False
    assert model.plan_calls == 0
    if output_shape == "subscription_service_health":
        assert outcome.plan.nodes[0].arguments["arguments"] == {"event_types": ["health_advisory"]}


def test_function_backed_starter_checks_the_complete_principal_manifest() -> None:
    manifest, _definition = _typed_fixture(
        groups=(),
        include_resource_state=True,
    )
    model = _Model(frame=_frame(), plan=None)

    class ObjectOnlySelector:
        def select(self, **kwargs: Any) -> tuple[dict[str, Any], ...]:
            return tuple(
                descriptor
                for descriptor in kwargs["manifest"].descriptors
                if descriptor.get("kind") == "object"
            )

    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(QueryNodeKind.OBJECT_SET, QueryNodeKind.FUNCTION)
        ),
        descriptor_selector=ObjectOnlySelector(),
        semantic_judgment=_JudgmentBoundary(_summary_judgment(RESOURCE_STATE_FUNCTION_NAME)),
        inventory_query_language=_inventory_query_language(),
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="현재 실행 중이 아닌 리소스를 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert outcome.plan.nodes[-1].arguments["function_name"] == RESOURCE_STATE_FUNCTION_NAME
    assert model.frame_calls == 0
    assert model.plan_calls == 0


def _state_inspection_query_language() -> InventoryQueryLanguageRegistry:
    return _inventory_query_language().model_copy(
        update={
            "suffixes": ("에", "를"),
            "signals": {
                "diagnosis": QueryTerms(terms=("why", "원인")),
                "health_history": QueryTerms(terms=("health history", "상태 이력")),
                "platform_health": QueryTerms(terms=("platform issue", "플랫폼 장애")),
                "state_inspection": QueryTerms(
                    terms=("status", "current state", "상태", "현재 상태")
                ),
            },
        }
    )


def _grounded_predicates(
    model: _Model,
    manifest: Any,
    utterance: str,
    *,
    semantic_judgment: Any = None,
) -> list[dict[str, Any]]:
    outcome = _service(model, manifest, semantic_judgment=semantic_judgment).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )
    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    predicates = outcome.plan.nodes[0].arguments["definition"]["predicates"]
    assert isinstance(predicates, list)
    return predicates


def test_stated_value_narrows_an_existence_predicate_to_the_declared_value() -> None:
    manifest, definition = _typed_fixture(groups=(_RESOURCE_GROUP_GROUP, _VM_GROUP))
    model = _Model(frame=_frame(output_shape="property_filtered_resources"), plan=_plan(definition))

    predicates = _grounded_predicates(model, manifest, "현재구독의 리소스그룹 모두 알려줘")

    assert predicates == [{"property": "type", "operator": "equals", "equals": "resource-group"}]


def test_named_resource_group_membership_filters_parent_instead_of_group_type() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_RESOURCE_GROUP_GROUP,),
        extra_values=("authorization.role-assignment",),
        include_parent_id=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "rg-example"],
            measure_concepts=["parent_id", "type"],
            output_shape="property_filtered_resources",
        ),
        plan=None,
    )

    predicates = _grounded_predicates(
        model,
        manifest,
        "rg-example 리소스 그룹에 있는 리소스의 상세 정보를 알려줘",
    )

    assert predicates == [
        {
            "property": "parent_id",
            "operator": "contains",
            "equals": "rg-example",
        },
        {
            "property": "type",
            "operator": "not_equals",
            "equals": "authorization.role-assignment",
        },
    ]
    assert model.frame_calls == 1
    assert model.plan_calls == 0


@pytest.mark.parametrize("measures", (["name"], ["name", "type"], ["parent_id"]))
def test_named_group_judgment_stabilizes_repeated_membership_frames(
    measures: list[str],
) -> None:
    utterance = "rg-example 리소스 그룹에 있는 리소스의 상세 정보를 알려줘"
    manifest, _definition = _typed_fixture(
        groups=(_RESOURCE_GROUP_GROUP,),
        extra_values=("authorization.role-assignment",),
        include_parent_id=True,
    )
    judgment = SemanticJudgmentProposal(
        primary_intent="query.contextual_resources",
        targets=(
            SemanticTarget(
                kind="resource_group",
                value="rg-example",
                source_start=0,
                source_end=len("rg-example"),
            ),
        ),
        requested_facets=("details", "name_filter"),
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "rg-example"],
            measure_concepts=measures,
            output_shape="property_filtered_resources",
        ),
        plan=None,
    )

    predicates = _grounded_predicates(
        model,
        manifest,
        utterance,
        semantic_judgment=_JudgmentBoundary(judgment),
    )

    assert predicates == [
        {
            "property": "parent_id",
            "operator": "contains",
            "equals": "rg-example",
        },
        {
            "property": "type",
            "operator": "not_equals",
            "equals": "authorization.role-assignment",
        },
    ]
    assert model.frame_calls == 0
    assert model.plan_calls == 0


def test_named_group_normalization_preserves_required_document_evidence() -> None:
    utterance = "rg-example 리소스 그룹의 런북 요구 사항과 리소스를 알려줘"
    manifest, _definition = _typed_fixture(
        groups=(_RESOURCE_GROUP_GROUP,),
        extra_values=("authorization.role-assignment",),
        include_governed_document=True,
        include_parent_id=True,
    )
    judgment = SemanticJudgmentProposal(
        primary_intent="query.contextual_resources",
        targets=(
            SemanticTarget(
                kind="resource_group",
                value="rg-example",
                source_start=0,
                source_end=len("rg-example"),
            ),
        ),
        requested_facets=("details", "name_filter"),
        document_evidence_mode=SemanticDocumentEvidenceMode.REQUIRED,
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "rg-example"],
            measure_concepts=["parent_id", "type"],
            output_shape="property_filtered_resources",
        ),
        plan=None,
    )

    outcome = _service(
        model,
        manifest,
        semantic_judgment=_JudgmentBoundary(judgment),
    ).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert "governed_documents.required" in outcome.frame.evidence_requirements
    assert outcome.plan is not None
    assert outcome.plan.nodes[-1].arguments["function_name"] == GOVERNED_DOCUMENT_FUNCTION_NAME


def test_document_judgment_builds_action_draft_without_frame_model_call() -> None:
    manifest, _definition = _fixture()
    judgment = SemanticJudgmentProposal(
        primary_intent="create.document",
        targets=(),
        requested_facets=("complete_content", "download"),
        confidence=0.98,
        ambiguous=False,
        action_posture="draft_only",
        action_subject="Document",
        authority="candidate_only",
        execution_authority=False,
    )
    model = _Model(frame=None, plan=None)

    outcome = _service(
        model,
        manifest,
        semantic_judgment=_JudgmentBoundary(judgment),
    ).plan(
        utterance="문서로 만들어줄래",
        prior_turns=(
            Turn(
                turn_id="source-answer",
                direction="outbound",
                content="Verified result with 24 complete rows.",
            ),
        ),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.ACTION_DRAFT
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Document",)
    assert outcome.frame.measure_concepts == ()
    assert outcome.execution_authority is False
    assert model.frame_calls == 0
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    "utterance",
    (
        "구독에 배포된 리소스 상세 정보를 문서화하자.",
        "현재 구독의 리소스를 빠짐없이 정리해서 내려받을 문서로 작성해 주세요.",
        "리소스 현황 문서가 필요해. 이 구독에 있는 것들을 자세히 정리해 줘.",
        "배포 자산별 세부 정보가 담긴 구독 인벤토리 문서를 부탁드립니다.",
        "Document the deployed resources in the current subscription.",
        "Prepare a downloadable inventory covering every resource in this subscription.",
        "Can you write up the details of our authorized subscription's deployed assets?",
        "I need the subscription resource inventory as a complete document.",
    ),
)
def test_inventory_document_judgment_reads_current_inventory_without_model_plan(
    utterance: str,
) -> None:
    """Synthetic judgments exercise paraphrase-independent dispatch, not live model quality."""
    manifest, _definition = _fixture()
    judgment = SemanticJudgmentProposal(
        primary_intent="create.document",
        targets=(),
        requested_facets=("download", "subscription", "complete_content", "resource_inventory"),
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )
    model = _Model(frame=None, plan=None)

    outcome = _service(model, manifest, semantic_judgment=_JudgmentBoundary(judgment)).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_list"
    assert set(outcome.frame.measure_concepts) == {"complete_content", "download"}
    assert outcome.plan is not None
    assert len(outcome.plan.nodes) == 1
    node = outcome.plan.nodes[0]
    assert node.kind is QueryNodeKind.OBJECT_SET
    definition = ObjectSetDefinition.model_validate(json.loads(node.arguments_json)["definition"])
    assert definition.selector.name == "Resource"
    assert definition.predicates == ()
    assert definition.include_relationships is False
    assert definition.limit == 1000
    assert outcome.execution_authority is False
    assert model.frame_calls == model.plan_calls == 0


def test_verified_inventory_preflight_skips_full_semantic_judgment() -> None:
    manifest, _definition = _fixture()
    model = _Model(frame=None, plan=None)
    utterance = "Prepare a complete downloadable inventory for the current subscription."

    class _NoFullJudgment:
        def judge(self, **_kwargs: Any) -> Any:
            raise AssertionError("full semantic judgment must be skipped")

    preflight = ConversationPreflightResult(
        proposal=ConversationPreflightProposal(
            social_act=SocialAct.NONE,
            operational_signal=OperationalSignal.EXPLICIT,
            context_dependency=ContextDependency.NONE,
            operational_family=OperationalPreflightFamily.INVENTORY_DOCUMENT,
            operational_facets=(
                "resource_inventory",
                "subscription",
                "complete_content",
                "download",
            ),
            confidence=0.99,
        ),
        attempted=True,
        input_digest=content_digest({"utterance": utterance}),
        model_config_digest=DIGEST,
        prompt_digest=DIGEST,
    )
    assert preflight.proposal is not None
    preflight = replace(
        preflight,
        proposal_digest=content_digest(preflight.proposal.model_dump(mode="json")),
    )

    outcome = _service(
        model,
        manifest,
        semantic_judgment=_NoFullJudgment(),
    ).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        preflight_result=preflight,
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_list"
    assert model.frame_calls == model.plan_calls == 0


@pytest.mark.parametrize(
    "updates",
    (
        {"primary_intent": "query.governed_documents"},
        {"action_posture": "draft_only", "action_subject": "Document"},
        {"secondary_intents": ("execute.action",)},
        {"requested_facets": ("resource_inventory", "subscription", "download", "upload")},
        {"discourse_mode": "quoted"},
        {
            "targets": (
                SemanticTarget(
                    kind="resource_group",
                    value="example",
                    source_start=0,
                    source_end=7,
                ),
            )
        },
    ),
)
def test_inventory_document_frame_does_not_drop_distinct_meaning(
    updates: dict[str, object],
) -> None:
    from fdai.core.conversation.semantic_planning_frame_normalization import (
        build_inventory_document_frame,
    )

    judgment = SemanticJudgmentProposal(
        primary_intent="create.document",
        targets=(),
        requested_facets=("resource_inventory", "subscription", "complete_content", "download"),
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    ).model_copy(update=updates)

    assert (
        build_inventory_document_frame(
            judgment=judgment,
            utterance="example",
            context=(),
            descriptors=({"kind": "object", "name": "Resource"},),
        )
        is None
    )


def test_inventory_document_pre_frame_requires_accepted_judgment() -> None:
    from fdai.core.conversation.semantic_planning_frame_checks import (
        deterministic_pre_frame_selection,
    )

    judgment = SemanticJudgmentProposal(
        primary_intent="create.document",
        targets=(),
        requested_facets=("resource_inventory", "subscription", "complete_content", "download"),
        confidence=0.2,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )

    assert (
        deterministic_pre_frame_selection(
            judgment=judgment,
            judgment_accepted=False,
            utterance="Document the subscription inventory.",
            context=(),
            descriptors=({"kind": "object", "name": "Resource"},),
        )
        is None
    )


@pytest.mark.parametrize(
    "primary_intent,expected_names",
    (
        ("create.document", {"Resource"}),
        (
            "query.resource_configuration_changes",
            {
                "Resource",
                "query.resource_configuration_changes",
                "query.resource_configuration_snapshot",
            },
        ),
        (
            "query.gateway_diagnostic_evidence",
            {
                "Resource",
                "routes_to",
                "query.gateway_diagnostic_evidence",
                "query.resource_configuration_changes",
                "query.resource_configuration_snapshot",
            },
        ),
    ),
)
def test_known_operational_judgment_narrows_model_descriptors(
    primary_intent: str,
    expected_names: set[str],
) -> None:
    descriptors = tuple(
        {"kind": "function" if name.startswith("query.") else "object", "name": name}
        for name in (
            "Resource",
            "routes_to",
            "query.gateway_diagnostic_evidence",
            "query.resource_configuration_changes",
            "query.resource_configuration_snapshot",
            "unrelated-large-capability",
        )
    )
    judgment = SemanticJudgmentProposal(
        primary_intent=primary_intent,
        targets=(),
        requested_facets=(),
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )

    selected = _descriptors_for_judgment(descriptors, judgment)

    assert {item["name"] for item in selected} == expected_names
    assert "unrelated-large-capability" not in {item["name"] for item in selected}


def test_unknown_judgment_preserves_complete_descriptor_fallback() -> None:
    descriptors = ({"kind": "object", "name": "Resource"},)
    judgment = SemanticJudgmentProposal(
        primary_intent="query.other",
        targets=(),
        requested_facets=(),
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )

    assert _descriptors_for_judgment(descriptors, judgment) is descriptors


@pytest.mark.parametrize(
    "primary_intent,output_shape",
    (
        ("query.resource_configuration_changes", "resource_configuration_changes"),
        ("query.gateway_diagnostic_evidence", "gateway_diagnostic_evidence"),
    ),
)
def test_operational_comparison_without_exact_resource_requires_clarification(
    primary_intent: str,
    output_shape: str,
) -> None:
    judgment = SemanticJudgmentProposal(
        primary_intent=primary_intent,
        targets=(),
        requested_facets=("comparison",),
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )

    outcome = deterministic_pre_frame_outcome(
        judgment=judgment,
        utterance="Compare the selected deployment.",
        context=(),
        descriptors=(),
        manifest_digest="sha256:" + "a" * 64,
        bound_incident=False,
    )

    assert outcome is not None
    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.output_shape == output_shape
    assert outcome.frame.unresolved_terms == ("resource_identity",)


def test_ambiguous_gateway_judgment_with_generic_resource_skips_frame_model() -> None:
    utterance = "Compare the APIM gateway and backend 500 responses."
    judgment = SemanticJudgmentProposal(
        primary_intent="query.gateway_diagnostic_evidence",
        targets=(
            SemanticTarget(
                kind="resource",
                value="APIM",
                source_start=12,
                source_end=16,
            ),
        ),
        requested_facets=("gateway", "backend", "status_500"),
        unresolved_terms=("resource_identity",),
        clarification="Which exact gateway resource should I inspect?",
        confidence=0.98,
        ambiguous=True,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )

    outcome = deterministic_pre_frame_outcome(
        judgment=judgment,
        utterance=utterance,
        context=(),
        descriptors=(),
        manifest_digest="sha256:" + "a" * 64,
        bound_incident=False,
    )

    assert outcome is not None
    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.unresolved_terms == ("resource_identity",)


def test_gateway_judgment_binds_past_hour_to_frame_window() -> None:
    utterance = "Compare agw-example latency over the last hour."
    judgment = SemanticJudgmentProposal(
        primary_intent="query.gateway_diagnostic_evidence",
        targets=(
            SemanticTarget(kind="resource", value="agw-example", source_start=8, source_end=19),
            SemanticTarget(
                kind="time_range",
                value="last hour",
                canonical_value="duration.PT1H",
                source_start=37,
                source_end=46,
            ),
        ),
        requested_facets=("latency", "last_hour"),
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            temporal_scope={},
            output_shape="gateway_diagnostic_evidence",
        )
    )
    frame = build_semantic_frame(proposal, utterance=utterance, context=())

    normalized, normalized_frame = _normalize_gateway_diagnostic_time_scope(
        proposal,
        frame,
        judgment=judgment,
        utterance=utterance,
        context=(),
    )

    assert normalized.temporal_scope == {"window_seconds": 3_600}
    assert normalized_frame.temporal_scope == {"window_seconds": 3_600}


@pytest.mark.parametrize(
    "primary_intent,output_shape",
    (
        ("query.resource_configuration_changes", "resource_configuration_changes"),
        ("query.gateway_diagnostic_evidence", "gateway_diagnostic_evidence"),
    ),
)
def test_future_hour_judgment_requires_temporal_clarification(
    primary_intent: str,
    output_shape: str,
) -> None:
    utterance = "Compare deployment-a one hour from now."
    judgment = SemanticJudgmentProposal(
        primary_intent=primary_intent,
        targets=(
            SemanticTarget(kind="resource", value="deployment-a", source_start=8, source_end=20),
            SemanticTarget(
                kind="time_range",
                value="one hour",
                canonical_value="duration.PT1H",
                source_start=21,
                source_end=29,
            ),
        ),
        requested_facets=("comparison",),
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )

    outcome = deterministic_pre_frame_outcome(
        judgment=judgment,
        utterance=utterance,
        context=(),
        descriptors=(),
        manifest_digest="sha256:" + "a" * 64,
        bound_incident=False,
    )

    assert outcome is not None
    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.frame is not None
    assert outcome.frame.output_shape == output_shape
    assert outcome.frame.unresolved_terms == ("temporal_scope",)


@pytest.mark.parametrize(
    "utterance",
    (
        "fdai 와 관련있는 리소스 그룹은?",
        "Which resource groups are related to fdai?",
    ),
)
def test_stated_type_and_name_fragment_ground_all_filters(utterance: str) -> None:
    manifest, definition = _typed_fixture(groups=(_RESOURCE_GROUP_GROUP, _VM_GROUP))
    name_exists = definition.model_copy(
        update={
            "predicates": (
                ObjectPredicate(property="name", operator=ObjectPredicateOperator.EXISTS),
            )
        }
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "fdai"],
            output_shape="property_filtered_resources",
        ),
        plan=_plan(name_exists),
    )

    predicates = _grounded_predicates(model, manifest, utterance)

    assert predicates == [
        {"property": "name", "operator": "contains", "equals": "fdai"},
        {"property": "type", "operator": "equals", "equals": "resource-group"},
    ]


def test_unstated_frame_subject_never_becomes_a_filter_operand() -> None:
    manifest, definition = _typed_fixture(groups=(_RESOURCE_GROUP_GROUP, _VM_GROUP))
    name_exists = definition.model_copy(
        update={
            "predicates": (
                ObjectPredicate(property="name", operator=ObjectPredicateOperator.EXISTS),
            )
        }
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "fdai"],
            output_shape="property_filtered_resources",
        ),
        plan=_plan(name_exists),
    )

    predicates = _grounded_predicates(model, manifest, "리소스 그룹을 모두 보여줘")

    assert predicates == [
        {"property": "type", "operator": "equals", "equals": "resource-group"},
    ]
    assert model.plan_calls == 0


def test_related_resource_filter_holds_when_model_drops_the_relation_target() -> None:
    manifest, definition = _typed_fixture(groups=(_RESOURCE_GROUP_GROUP, _VM_GROUP))
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            measure_concepts=["type"],
            output_shape="property_filtered_resources",
        ),
        plan=_plan(definition),
    )
    query_language = _inventory_query_language().model_copy(
        update={"signals": {"resource_name_relation": QueryTerms(terms=("관련",))}}
    )

    outcome = _service(
        model,
        manifest,
        inventory_query_language=query_language,
    ).plan(
        utterance="FDAI 관련 리소스 그룹이 뭐가 있어?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.reason == "semantic_clarification_required"
    assert "이름이나 태그" in (outcome.clarification or "")


def test_stated_value_group_with_several_values_narrows_to_a_membership_predicate() -> None:
    manifest, definition = _typed_fixture(
        groups=(
            PropertyValueGroup(
                id="containers",
                values=("compute.vm", "storage.account"),
                terms=("infrastructure",),
            ),
        )
    )
    model = _Model(frame=_frame(output_shape="property_filtered_resources"), plan=_plan(definition))

    predicates = _grounded_predicates(model, manifest, "List every infrastructure record.")

    assert predicates == [
        {"property": "type", "operator": "in", "values": ["compute.vm", "storage.account"]}
    ]


def test_stated_subtype_narrows_an_overbroad_membership_predicate() -> None:
    container_app = PropertyValueGroup(
        id="compute-container-app",
        values=("compute.container-app",),
        terms=("container app", "container apps"),
    )
    manifest, definition = _typed_fixture(
        groups=(container_app,),
        extra_values=("compute.container-app-environment", "compute.container-app-job"),
    )
    overbroad = definition.model_copy(
        update={
            "predicates": (
                ObjectPredicate(
                    property="type",
                    operator=ObjectPredicateOperator.IN,
                    values=(
                        "compute.container-app",
                        "compute.container-app-environment",
                        "compute.container-app-job",
                    ),
                ),
            )
        }
    )
    model = _Model(
        frame=_frame(output_shape="property_filtered_resources"),
        plan=_plan(overbroad),
    )

    predicates = _grounded_predicates(model, manifest, "내 Container Apps 목록을 모두 보여줘.")

    assert predicates == [
        {"property": "type", "operator": "equals", "equals": "compute.container-app"}
    ]


@pytest.mark.parametrize(
    "output_shape",
    ("property_filtered_resources", "resource_list"),
)
def test_stated_subtype_builds_a_model_free_filter_plan(output_shape: str) -> None:
    container_app = PropertyValueGroup(
        id="compute-container-app",
        values=("compute.container-app",),
        terms=("container app", "container apps"),
    )
    manifest, _definition = _typed_fixture(groups=(container_app,))
    model = _Model(
        frame=_frame(output_shape=output_shape),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="내 Container Apps 목록을 모두 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {"property": "type", "operator": "equals", "equals": "compute.container-app"}
    ]
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    ("utterance", "subject"),
    (
        (
            "내 Container App의 인그레스 구성은 어떻게 되어 있어?",
            "내 Container App",
        ),
        (
            "How is ingress configured for my Container App?",
            "my Container App",
        ),
    ),
)
def test_target_scoped_subtype_query_discovers_exact_resource_candidates(
    utterance: str,
    subject: str,
) -> None:
    container_app = PropertyValueGroup(
        id="compute-container-app",
        values=("compute.container-app",),
        terms=("container app", "container apps"),
    )
    manifest, _definition = _typed_fixture(groups=(container_app,))
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", subject],
            measure_concepts=["ingress"],
            output_shape="property_filtered_resources",
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.reason == "semantic_plan_verified"
    assert outcome.clarification is None
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
    assert outcome.execution_authority is False
    assert model.plan_calls == 0


def test_resource_identity_clarification_discovers_verified_candidates() -> None:
    container_app = PropertyValueGroup(
        id="compute-container-app",
        values=("compute.container-app",),
        terms=("container app", "container apps"),
    )
    manifest, _definition = _typed_fixture(groups=(container_app,))
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            unresolved_terms=["resource_identity"],
            clarification_requirements=["resource_identity"],
            clarification="Which exact resource should I inspect?",
            output_shape="property_filtered_resources",
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="내 Container App의 인그레스 구성은 어떻게 되어 있어?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_target_candidates"
    assert outcome.plan is not None
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_subject_and_measure_clarification_discovers_verified_candidates() -> None:
    container_app = PropertyValueGroup(
        id="compute-container-app",
        values=("compute.container-app",),
        terms=("container app", "container apps"),
    )
    manifest, _definition = _typed_fixture(groups=(container_app,))
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            unresolved_terms=["Container App", "ingress configuration"],
            clarification_requirements=["subject", "measure"],
            clarification="Which target and configuration should I inspect?",
            output_shape="property_filtered_resources",
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="내 Container App의 인그레스 구성은 어떻게 되어 있어?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_target_candidates"
    assert outcome.plan is not None
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_temporal_subtype_query_discovers_exact_resource_candidates() -> None:
    container_app = PropertyValueGroup(
        id="compute-container-app",
        values=("compute.container-app",),
        terms=("container app", "container apps"),
    )
    manifest, _definition = _typed_fixture(groups=(container_app,))
    model = _Model(
        frame=_frame(
            operation="compare",
            subject_constraints=["Resource", "Container App"],
            temporal_scope={"lookback_seconds": 604800},
            output_shape="temporal_comparison",
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="지난 1주일 동안 내 Container App에서 무엇이 변경됐어?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.reason == "semantic_plan_verified"
    assert outcome.clarification is None
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_target_candidates"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (QueryNodeKind.OBJECT_SET,)
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {
            "property": "type",
            "operator": "equals",
            "equals": "compute.container-app",
        }
    ]
    assert outcome.execution_authority is False
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    ("utterance", "frame_overrides"),
    (
        (
            "내 Container App에서 현재 활성화된 리비전은 무엇이야?",
            {
                "subject_constraints": ["Resource", "Container App"],
                "measure_concepts": ["active_revision"],
                "output_shape": "target_current_state",
            },
        ),
        (
            "지난 1주일간 내 Container App의 메모리 사용률(%)을 시각화해 줘.",
            {
                "subject_constraints": ["Resource", "내 Container App"],
                "measure_concepts": ["resource.memory.available_pct"],
                "temporal_scope": {"lookback_seconds": 604800},
                "output_shape": "resource_metric_list",
            },
        ),
        (
            "내 Container App이 activation failed 상태에서 멈춰 있어. 원인을 조사해 줘.",
            {
                "operation": "explain_change",
                "subject_constraints": ["Resource", "Container App"],
                "measure_concepts": ["activation_state"],
                "output_shape": "causal_evidence",
            },
        ),
        (
            "내 Container App 요청이 시간 초과되는 이유는 무엇이야?",
            {
                "operation": "explain_change",
                "subject_constraints": ["Resource", "Container App"],
                "measure_concepts": ["request_timeout"],
                "output_shape": "causal_evidence",
            },
        ),
        (
            "내 Container App에서 HTTP 500 오류가 발생하는 이유는 무엇이야?",
            {
                "operation": "explain_change",
                "subject_constraints": ["Resource", "Container App"],
                "measure_concepts": ["http_500"],
                "output_shape": "causal_evidence",
            },
        ),
    ),
)
def test_targetless_sre_examples_discover_verified_container_app_candidates(
    utterance: str,
    frame_overrides: dict[str, object],
) -> None:
    container_app = PropertyValueGroup(
        id="compute-container-app",
        values=("compute.container-app",),
        terms=("container app", "container apps"),
    )
    manifest, _definition = _typed_fixture(groups=(container_app,))
    model = _Model(frame=_frame(**frame_overrides), plan=None)

    outcome = _service(model, manifest).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_target_candidates"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (QueryNodeKind.OBJECT_SET,)
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {
            "property": "type",
            "operator": "equals",
            "equals": "compute.container-app",
        }
    ]
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_targetless_rollout_diagnosis_discovers_kubernetes_deployment_candidates() -> None:
    kubernetes_deployment = PropertyValueGroup(
        id="kubernetes-deployment",
        values=("kubernetes.deployment",),
        terms=(
            "kubernetes deployment",
            "kubernetes deployments",
            "rollout",
            "rollouts",
            "롤아웃",
            "쿠버네티스 디플로이먼트",
            "쿠버네티스 배포",
        ),
    )
    manifest, _definition = _typed_fixture(groups=(kubernetes_deployment,))
    model = _Model(
        frame=_frame(
            operation="explain_change",
            subject_constraints=["Resource", "배포"],
            measure_concepts=["deployment.rollout.stall"],
            output_shape="causal_evidence",
            investigation={
                "operation": "explain_change",
                "entities": [
                    {
                        "mention_id": "target",
                        "span": {"text": "배포", "start": 0, "end": 2},
                        "role": "affected_target",
                        "object_type_candidates": ["Resource"],
                    }
                ],
                "symptom_measures": [
                    {
                        "measure_id": "rollout",
                        "span": {"text": "rollout", "start": 0, "end": 7},
                        "target_mention_id": "target",
                        "concept_id": "deployment.rollout.stall",
                        "direction": "decrease",
                    }
                ],
                "primary_symptom_measure_id": "rollout",
                "temporal_cues": [
                    {
                        "cue_id": "after_deployment",
                        "span": {"text": "이후", "start": 0, "end": 2},
                        "role": "change_point",
                    }
                ],
                "relationship_intents": [
                    {
                        "relationship_id": "invalid",
                        "span": {"text": "이후", "start": 0, "end": 2},
                        "source_mention_id": "target",
                        "target_mention_id": None,
                        "query_side_candidates": ["missing.outgoing"],
                    }
                ],
                "hypotheses": [
                    {
                        "hypothesis_id": "rollout_controller",
                        "span": {"text": "원인", "start": 0, "end": 2},
                        "relationship_id": "invalid",
                        "cause_measure_concept": "deployment.change",
                        "effect_measure_id": "rollout",
                        "competing_explanations": ["pod_capacity"],
                    },
                    {
                        "hypothesis_id": "pod_capacity",
                        "span": {"text": "복구안", "start": 0, "end": 3},
                        "relationship_id": "invalid",
                        "cause_measure_concept": "resource.cpu.saturation",
                        "effect_measure_id": "rollout",
                        "competing_explanations": ["rollout_controller"],
                    },
                ],
                "evidence_standard": "support_and_refutation",
                "answer_shape": "diagnosis",
                "confidence": 0.8,
            },
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
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
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_broad_subtype_measure_query_does_not_require_an_exact_resource() -> None:
    container_app = PropertyValueGroup(
        id="compute-container-app",
        values=("compute.container-app",),
        terms=("container app", "container apps"),
    )
    manifest, _definition = _typed_fixture(groups=(container_app,))
    model = _Model(
        frame=_frame(
            measure_concepts=["cpu"],
            output_shape="property_filtered_resources",
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="Show CPU telemetry for all Container Apps.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.clarification is None
    assert outcome.execution_authority is False
    assert model.plan_calls == 0


@pytest.mark.parametrize(
    ("utterance", "initial_output_shape", "expected_concepts"),
    (
        (
            "중지된 데이터베이스 있어?",
            "property_filtered_resources",
            ["resource_state.stopped"],
        ),
        (
            "현재 중지된 데이터베이스가 있나요?",
            "resource_state_list",
            ["resource_state.stopped"],
        ),
        (
            "현재 멈춰 있는 DB를 종류별로 보여줘.",
            "resource_state_list",
            ["resource_state.stopped"],
        ),
        (
            "중지된 데이터베이스 서비스와 일시 중지된 데이터베이스 서비스를 구분해서 보여줘.",
            "property_filtered_resources",
            ["resource_state.paused", "resource_state.stopped"],
        ),
        (
            "실패 상태인 Azure 리소스가 있어?",
            "property_filtered_resources",
            ["resource_state.failed"],
        ),
        (
            "실패, 성능 저하 또는 사용 불가능 상태인 리소스를 보여줘.",
            "resource_state_list",
            [
                "resource_state.degraded",
                "resource_state.failed",
                "resource_state.unavailable",
            ],
        ),
    ),
)
def test_broad_resource_state_query_uses_a_collection_capability(
    utterance: str,
    initial_output_shape: str,
    expected_concepts: list[str],
) -> None:
    database = PropertyValueGroup(
        id="database",
        values=("mysql-server", "postgresql-server", "sql-database"),
        terms=("database", "databases", "db", "데이터베이스"),
    )
    manifest, _definition = _typed_fixture(
        groups=(database,),
        include_resource_state=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "database"],
            measure_concepts=["resource_state.running", "status"],
            output_shape=initial_output_shape,
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.clarification is None
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_state_list"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.nodes[1].arguments["function_name"] == RESOURCE_STATE_FUNCTION_NAME
    assert outcome.plan.nodes[1].arguments["arguments"] == {"state_concepts": expected_concepts}
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


@pytest.mark.parametrize(
    ("utterance", "initial_output_shape"),
    (
        (
            "안녕, 우리 구독에 postgres db 상태 알려줄래?",
            "subscription_service_health",
        ),
        (
            "안녕, 우리 구독에 postgres db 상태 알려줄래?",
            "target_current_state",
        ),
        (
            "Show the PostgreSQL database status in our subscription.",
            "subscription_service_health",
        ),
    ),
)
def test_typed_subscription_state_query_uses_observed_resource_state(
    utterance: str,
    initial_output_shape: str,
) -> None:
    manifest, _definition = _typed_fixture(
        groups=(_POSTGRES_GROUP,),
        include_resource_state=True,
        include_service_health=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            measure_concepts=list(SERVICE_HEALTH_MEASURE_CONCEPTS),
            output_shape=initial_output_shape,
        ),
        plan=None,
    )

    outcome = _service(
        model,
        manifest,
        inventory_query_language=_state_inspection_query_language(),
    ).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_state_list"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {
            "property": "type",
            "operator": "equals",
            "equals": "postgresql-server",
        }
    ]
    assert outcome.plan.nodes[1].arguments["arguments"] == {
        "state_concepts": [RESOURCE_STATE_OBSERVED_CONCEPT]
    }
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_typed_platform_health_query_stays_on_subscription_health() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_POSTGRES_GROUP,),
        include_resource_state=True,
        include_service_health=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            measure_concepts=list(SERVICE_HEALTH_MEASURE_CONCEPTS),
            output_shape="subscription_service_health",
        ),
        plan=None,
    )

    outcome = _service(
        model,
        manifest,
        inventory_query_language=_state_inspection_query_language(),
    ).plan(
        utterance="우리 구독의 postgres 플랫폼 장애 상태를 알려줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "subscription_service_health"
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["function_name"] == SERVICE_HEALTH_FUNCTION_NAME
    assert outcome.execution_authority is False


def test_typed_subscription_state_prefers_a_concrete_state_filter() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_POSTGRES_GROUP,),
        include_resource_state=True,
        include_service_health=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            measure_concepts=list(SERVICE_HEALTH_MEASURE_CONCEPTS),
            output_shape="subscription_service_health",
        ),
        plan=None,
    )

    outcome = _service(
        model,
        manifest,
        inventory_query_language=_state_inspection_query_language(),
    ).plan(
        utterance="우리 구독에 중지된 postgres db 상태를 알려줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_state_list"
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.nodes[1].arguments["arguments"] == {
        "state_concepts": ["resource_state.deallocated", "resource_state.stopped"]
    }


@pytest.mark.parametrize(
    ("utterance", "subject_constraints"),
    (
        ("postgres db 상태를 알려줘.", ("Resource",)),
        (
            "우리 구독의 postgres psql-example-prod 상태를 알려줘.",
            ("Resource", "psql-example-prod"),
        ),
    ),
)
def test_collection_state_correction_requires_scope_and_no_exact_target(
    utterance: str,
    subject_constraints: tuple[str, ...],
) -> None:
    manifest, _definition = _typed_fixture(
        groups=(_POSTGRES_GROUP,),
        include_resource_state=True,
        include_service_health=True,
    )
    proposal = SemanticFrameProposal.model_validate(
        _frame(
            subject_constraints=list(subject_constraints),
            measure_concepts=list(SERVICE_HEALTH_MEASURE_CONCEPTS),
            output_shape="target_current_state",
        )
    )

    normalized = normalize_resource_state_proposal(
        proposal,
        utterance=utterance,
        descriptors=manifest.descriptors,
        inventory_query_language=_state_inspection_query_language(),
    )

    assert normalized.output_shape == "target_current_state"
    assert normalized.measure_concepts == SERVICE_HEALTH_MEASURE_CONCEPTS


def test_current_resource_state_cannot_substitute_for_historical_events() -> None:
    database = PropertyValueGroup(
        id="database",
        values=("mysql-server", "postgresql-server", "sql-database"),
        terms=("database", "databases", "db", "데이터베이스"),
    )
    manifest, _definition = _typed_fixture(
        groups=(database,),
        include_resource_state=True,
    )
    model = _Model(
        frame=_frame(
            measure_concepts=["resource_state.running"],
            temporal_scope={"lookback_seconds": 86400},
            output_shape="resource_state_list",
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="지난 24시간의 리소스 상태 이벤트를 시간순으로 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.plan is None
    assert outcome.execution_authority is False
    assert model.plan_calls == 0


def test_resource_health_history_uses_exact_event_function() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_VM_GROUP,),
        include_resource_event=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "compute-vm"],
            measure_concepts=["resource_event.resource_health"],
            temporal_scope={"lookback_seconds": 86400},
            output_shape="resource_event_history",
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="지난 24시간의 가상 머신 Resource Health 이벤트를 시간순으로 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.nodes[1].arguments["function_name"] == RESOURCE_EVENT_FUNCTION_NAME
    assert outcome.plan.nodes[1].arguments["arguments"] == {
        "event_families": ["resource_event.resource_health"],
        "lookback_seconds": 86400,
    }
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_kubernetes_history_uses_exact_event_function() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_VM_GROUP,),
        include_resource_event=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "kubernetes-cluster"],
            measure_concepts=["resource_event.kubernetes"],
            temporal_scope={"lookback_seconds": 3600},
            output_shape="resource_event_history",
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="Show Kubernetes events for this cluster from the last hour.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert outcome.plan.nodes[1].arguments["function_name"] == RESOURCE_EVENT_FUNCTION_NAME
    assert outcome.plan.nodes[1].arguments["arguments"] == {
        "event_families": ["resource_event.kubernetes"],
        "lookback_seconds": 3600,
    }
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_kubernetes_history_preserves_one_source_grounded_target() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_VM_GROUP,),
        include_resource_event=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "api-backend"],
            measure_concepts=["resource_event.kubernetes"],
            temporal_scope={"lookback_seconds": 3600},
            output_shape="resource_event_history",
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="Show api-backend Kubernetes events from the last hour.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    definition = ObjectSetDefinition.model_validate(outcome.plan.nodes[0].arguments["definition"])
    assert tuple(
        (predicate.property, predicate.operator.value, predicate.equals)
        for predicate in definition.predicates
    ) == (
        ("type", "exists", None),
        ("name", "equals", "api-backend"),
    )
    assert definition.limit == 2
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_platform_impact_uses_server_scoped_service_health_function() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_VM_GROUP,),
        include_service_health=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource"],
            measure_concepts=["service_health.active_event"],
            output_shape="subscription_service_health",
        ),
        plan=None,
    )

    query_language = _inventory_query_language().model_copy(
        update={
            "suffixes": ("나", "가"),
            "signals": {
                "service_health_issue": QueryTerms(terms=("서비스 장애",)),
                "service_health_maintenance": QueryTerms(terms=("예정된 유지 관리",)),
            },
        }
    )
    outcome = _service(
        model,
        manifest,
        inventory_query_language=query_language,
    ).plan(
        utterance="현재 Azure 구독에 활성 서비스 장애나 예정된 유지 관리가 있어?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (QueryNodeKind.FUNCTION,)
    assert outcome.plan.nodes[0].arguments == {
        "function_name": SERVICE_HEALTH_FUNCTION_NAME,
        "arguments": {"event_types": ["planned_maintenance", "service_issue"]},
        "dependency_arguments": {},
    }
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_historical_power_state_uses_durable_transition_function() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_VM_GROUP,),
        include_resource_event=True,
        include_state_transitions=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "compute-vm"],
            measure_concepts=["resource_event.resource_health"],
            temporal_scope={"lookback_seconds": 3600},
            output_shape="resource_event_history",
        ),
        plan=None,
    )

    outcome = _service(
        model,
        manifest,
        inventory_query_language=_inventory_query_language(),
    ).plan(
        utterance="Show virtual machines that transitioned to stopped in the last hour.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_state_transitions"
    assert outcome.frame.measure_concepts == (
        "resource_state.deallocated",
        "resource_state.stopped",
    )
    assert outcome.plan is not None
    assert outcome.plan.nodes[1].arguments["function_name"] == (
        RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME
    )
    assert outcome.plan.nodes[1].arguments["arguments"]["to_states"] == [
        "deallocated",
        "stopped",
    ]
    assert outcome.execution_authority is False


def test_mixed_inventory_state_and_health_preserves_the_health_family() -> None:
    application_service = PropertyValueGroup(
        id="application-service",
        values=("app-service",),
        terms=("app service", "앱 서비스"),
    )
    manifest, _definition = _typed_fixture(
        groups=(application_service,),
        include_resource_health=True,
        include_resource_state=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "application-service"],
            measure_concepts=["resource_state.running"],
            output_shape="resource_state_list",
        ),
        plan=None,
    )

    outcome = _service(
        model,
        manifest,
        inventory_query_language=_inventory_query_language(),
    ).plan(
        utterance="실행 중이 아니거나 준비되지 않은 앱 서비스를 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_condition_sections"
    assert outcome.frame.measure_concepts == (
        "resource_health.not_ready",
        "resource_state.deallocated",
        "resource_state.stopped",
    )
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.nodes[1].arguments["function_name"] == RESOURCE_STATE_FUNCTION_NAME
    assert outcome.plan.nodes[1].arguments["arguments"] == {
        "state_concepts": ["resource_state.deallocated", "resource_state.stopped"],
    }
    assert outcome.plan.nodes[2].arguments["function_name"] == RESOURCE_HEALTH_FUNCTION_NAME
    assert outcome.plan.nodes[2].arguments["arguments"] == {
        "health_concepts": ["resource_health.not_ready"],
        "state_concepts": [],
    }
    assert outcome.plan.output_node_ids == (
        "resource-condition-power",
        "resource-condition-health",
    )
    assert outcome.intent_graph is not None
    authorities = (
        EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        EvidenceAuthority.SERVER_RESOURCE_HEALTH,
    )
    receipts = tuple(
        GoalTaskReceipt(
            task_id=f"query:{node.node_id}",
            goal_id=node.node_id,
            intent=node.kind.value,
            capability=f"query.{node.kind.value}",
            evidence_mode=GoalEvidenceMode.OPERATIONAL,
            status=TaskStatus.COMPLETED,
            duration_ms=1,
            evidence_refs=(f"evidence:{index}",),
            authority=authority,
            authority_inputs=(
                (EvidenceAuthority.SERVER_INVENTORY_GRAPH,)
                if authority is EvidenceAuthority.SERVER_RESOURCE_HEALTH
                else ()
            ),
            started_at=NOW,
            completed_at=NOW,
        )
        for index, (node, authority) in enumerate(
            zip(outcome.plan.nodes, authorities, strict=True),
            start=1,
        )
    )
    execution = QueryPlanExecution(
        plan_digest=outcome.plan.plan_digest,
        status="completed",
        results=MappingProxyType(
            {
                node.node_id: QueryNodeResult(
                    value={},
                    evidence_refs=receipt.evidence_refs,
                    authority=receipt.authority,
                )
                for node, receipt in zip(outcome.plan.nodes, receipts, strict=True)
            }
        ),
        receipts=receipts,
        output_node_ids=outcome.plan.output_node_ids,
    )
    assert resolve_execution_authority(
        execution,
        frame=outcome.frame,
        plan=outcome.plan,
    ) == (None, "verified")
    document_node = OntologyQueryNode(
        node_id="governed-documents",
        kind=QueryNodeKind.FUNCTION,
        arguments_json=canonical_json(
            {
                "function_name": "query.governed_documents",
                "arguments": {"query": "recovery", "evidence_mode": "optional"},
                "dependency_arguments": {},
            }
        ),
        output_kind="query.table",
    )
    document_plan = outcome.plan.model_copy(
        update={
            "nodes": (*outcome.plan.nodes, document_node),
            "output_node_ids": (*outcome.plan.output_node_ids, document_node.node_id),
            "plan_digest": DIGEST,
        }
    )
    document_frame = outcome.frame.model_copy(
        update={
            "evidence_requirements": (
                *outcome.frame.evidence_requirements,
                "governed_documents.optional",
            )
        }
    )
    document_receipt = GoalTaskReceipt(
        task_id="query:governed-documents",
        goal_id="governed-documents",
        intent="function",
        capability="query.function",
        evidence_mode=GoalEvidenceMode.DOCUMENT,
        status=TaskStatus.COMPLETED,
        duration_ms=1,
        evidence_refs=("document:sha256:" + ("d" * 64),),
        authority=EvidenceAuthority.SERVER_GOVERNED_DOCUMENT,
        started_at=NOW,
        completed_at=NOW,
    )
    document_execution = replace(
        execution,
        plan_digest=document_plan.plan_digest,
        results=MappingProxyType(
            {
                **dict(execution.results),
                document_node.node_id: QueryNodeResult(
                    value={},
                    evidence_refs=document_receipt.evidence_refs,
                    authority=document_receipt.authority,
                ),
            }
        ),
        receipts=(*execution.receipts, document_receipt),
        output_node_ids=document_plan.output_node_ids,
    )
    assert resolve_execution_authority(
        document_execution,
        frame=document_frame,
        plan=document_plan,
    ) == (None, "verified")
    evidence = build_intent_graph_evidence(
        graph=outcome.intent_graph,
        plan=outcome.plan,
        execution=execution,
        frame=outcome.frame,
    )
    assert evidence.status == "completed"
    assert {goal.authority for goal in evidence.goals if goal.evidence_refs} == set(authorities)
    same_authority = replace(
        execution,
        receipts=tuple(
            receipt.model_copy(
                update={
                    "authority": EvidenceAuthority.SERVER_INVENTORY_GRAPH,
                    "authority_inputs": (),
                }
            )
            for receipt in execution.receipts
        ),
    )
    assert resolve_execution_authority(
        same_authority,
        frame=outcome.frame,
        plan=outcome.plan,
    ) == (None, "conflict")
    swapped = replace(
        execution,
        receipts=(
            execution.receipts[0],
            execution.receipts[1].model_copy(
                update={
                    "authority": EvidenceAuthority.SERVER_RESOURCE_HEALTH,
                    "authority_inputs": (EvidenceAuthority.SERVER_INVENTORY_GRAPH,),
                }
            ),
            execution.receipts[2].model_copy(
                update={
                    "authority": EvidenceAuthority.SERVER_INVENTORY_GRAPH,
                    "authority_inputs": (),
                }
            ),
        ),
    )
    assert resolve_execution_authority(
        swapped,
        frame=outcome.frame,
        plan=outcome.plan,
    ) == (None, "conflict")
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_mixed_inventory_state_and_health_holds_when_health_function_is_unbound() -> None:
    application_service = PropertyValueGroup(
        id="application-service",
        values=("app-service",),
        terms=("app service", "앱 서비스"),
    )
    manifest, _definition = _typed_fixture(
        groups=(application_service,),
        include_resource_state=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "application-service"],
            measure_concepts=["resource_state.running"],
            output_shape="resource_state_list",
        ),
        plan=None,
    )

    outcome = _service(
        model,
        manifest,
        inventory_query_language=_inventory_query_language(),
    ).plan(
        utterance="실행 중이 아니거나 준비되지 않은 앱 서비스를 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_condition_sections"
    assert outcome.plan is None
    assert outcome.execution_authority is False


def test_broad_resource_metric_query_uses_reviewed_metric_function() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_VM_GROUP,),
        include_resource_metric=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "compute-vm"],
            measure_concepts=["resource.saturation"],
            temporal_scope={"lookback_seconds": 1800},
            output_shape="resource_metric_list",
        ),
        plan=None,
    )

    outcome = _service(
        model,
        manifest,
        metric_concepts=("resource.saturation",),
    ).plan(
        utterance="지난 30분 동안 가상 머신 CPU 사용률을 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert tuple(node.kind for node in outcome.plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
    )
    assert outcome.plan.nodes[1].arguments["function_name"] == RESOURCE_METRIC_FUNCTION_NAME
    assert outcome.plan.nodes[1].arguments["arguments"] == {
        "metric_concepts": ["resource.saturation"],
        "window_seconds": 1800,
    }
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_broad_resource_metric_query_rejects_unreviewed_concept() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_VM_GROUP,),
        include_resource_metric=True,
    )
    model = _Model(
        frame=_frame(
            measure_concepts=["resource.memory.pressure"],
            output_shape="resource_metric_list",
        ),
        plan=None,
    )

    outcome = _service(
        model,
        manifest,
        metric_concepts=("resource.saturation",),
    ).plan(
        utterance="메모리 압력이 있는 리소스를 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.plan is None
    assert outcome.execution_authority is False


def test_broad_memory_observation_uses_reviewed_available_percentage() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_VM_GROUP,),
        include_resource_metric=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "compute-vm"],
            measure_concepts=["resource.memory.available_pct"],
            output_shape="resource_metric_list",
        ),
        plan=None,
    )

    outcome = _service(
        model,
        manifest,
        metric_concepts=("resource.memory.available_pct",),
    ).plan(
        utterance="가상 머신의 현재 가용 메모리 비율을 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert outcome.plan.nodes[1].arguments["arguments"] == {
        "metric_concepts": ["resource.memory.available_pct"],
        "window_seconds": 900,
    }
    assert outcome.execution_authority is False


def test_catalog_current_state_group_stays_on_the_state_capability() -> None:
    database = PropertyValueGroup(
        id="database",
        values=("mysql-server", "postgresql-server", "sql-database"),
        terms=("database", "db", "데이터베이스"),
    )
    manifest, _definition = _typed_fixture(
        groups=(database,),
        include_resource_state=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "database"],
            measure_concepts=["resource_state.running"],
            output_shape="resource_state_list",
        ),
        plan=None,
    )

    outcome = _service(
        model,
        manifest,
        inventory_query_language=_inventory_query_language(),
    ).plan(
        utterance="현재 실행 중이 아닌 DB를 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_state_list"
    assert outcome.plan is not None
    assert outcome.plan.nodes[1].arguments["arguments"] == {
        "state_concepts": ["resource_state.deallocated", "resource_state.stopped"]
    }
    assert outcome.execution_authority is False


def test_resource_state_collection_does_not_promote_subject_phrase_to_name_filter() -> None:
    manifest, _definition = _typed_fixture(
        groups=(_VM_GROUP,),
        include_resource_state=True,
    )
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "할당 해제된 가상 머신"],
            measure_concepts=["resource_state.deallocated"],
            output_shape="resource_state_list",
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="할당 해제된 가상 머신을 모두 찾아줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {"property": "type", "operator": "equals", "equals": "compute.vm"}
    ]
    assert outcome.execution_authority is False


@pytest.mark.parametrize(
    "output_shape",
    (
        "contextual_resource_list",
        "resource_event_history",
        "resource_health_list",
        "resource_metric_list",
    ),
)
def test_specialized_collection_family_rejects_a_generic_object_set(
    output_shape: str,
) -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(output_shape=output_shape),
        plan=_plan(definition),
    )

    outcome = _service(model, manifest).plan(
        utterance="Review the requested specialized resource evidence.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is (
        SemanticPlanningDisposition.CLARIFICATION
        if output_shape == "contextual_resource_list"
        else SemanticPlanningDisposition.UNSUPPORTED
    )
    assert outcome.plan is None
    assert outcome.execution_authority is False
    assert model.plan_calls == (0 if output_shape == "contextual_resource_list" else 1)


@pytest.mark.parametrize(
    "utterance",
    ("Which resources are on this screen?", "이 화면의 리소스를 보여줘."),
)
def test_contextual_collection_uses_exact_bound_screen_scope(utterance: str) -> None:
    manifest, _definition = _typed_fixture(include_contextual_resource=True, groups=())
    model = _Model(frame=_frame(output_shape="contextual_resource_list"), plan=None)

    outcome = _service(model, manifest).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_resource_context=_bound_context(
            ("resource-a", "resource-b"),
            release_digest=manifest.release_digest,
            principal_scope_digest=manifest.coverage_receipt.principal_scope_digest,
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.plan is not None
    definition = outcome.plan.nodes[0].arguments["definition"]
    assert definition["predicates"] == [
        {"property": "id", "operator": "in", "values": ["resource-a", "resource-b"]}
    ]
    assert outcome.plan.nodes[1].arguments["function_name"] == "query.contextual_resources"
    assert (
        outcome.plan.nodes[1].arguments["arguments"]["selection_token"]
        == "context-selection:" + "a" * 32
    )
    assert outcome.execution_authority is False


def test_contextual_collection_intersects_explicit_type_and_name_filters() -> None:
    manifest, _definition = _typed_fixture(
        include_contextual_resource=True,
        groups=(_RESOURCE_GROUP_GROUP,),
    )
    model = _Model(
        frame=_frame(
            output_shape="contextual_resource_list",
            subject_constraints=["Resource", "fdai"],
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="Which fdai resource groups are on this screen?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_resource_context=_bound_context(
            ("resource-a", "resource-b"),
            release_digest=manifest.release_digest,
            principal_scope_digest=manifest.coverage_receipt.principal_scope_digest,
        ),
    )

    assert outcome.plan is not None
    predicates = outcome.plan.nodes[0].arguments["definition"]["predicates"]
    assert predicates == [
        {"property": "id", "operator": "in", "values": ["resource-a", "resource-b"]},
        {"property": "type", "operator": "equals", "equals": "resource-group"},
        {"property": "name", "operator": "contains", "equals": "fdai"},
    ]


@pytest.mark.parametrize(
    "utterance",
    ("Which resources are on this screen?", "이 화면의 리소스를 보여줘."),
)
def test_contextual_collection_without_bound_scope_clarifies(utterance: str) -> None:
    manifest, _definition = _typed_fixture(include_contextual_resource=True, groups=())
    model = _Model(frame=_frame(output_shape="contextual_resource_list"), plan=None)

    outcome = _service(model, manifest).plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.reason == "contextual_resource_scope_required"
    assert outcome.plan is None


def test_contextual_specialized_function_cannot_be_a_disconnected_model_node() -> None:
    frame = SimpleNamespace(
        operation="select",
        output_shape="contextual_resource_list",
        measure_concepts=(),
        temporal_scope={},
        subject_constraints=(),
    )
    plan = SimpleNamespace(
        nodes=(
            SimpleNamespace(
                kind=QueryNodeKind.FUNCTION,
                node_id="forged-context",
                arguments_json='{"function_name":"query.contextual_resources"}',
            ),
        ),
        output_node_ids=("forged-context",),
    )

    with pytest.raises(ValueError, match="bound-context output plan"):
        verify_frame_plan_alignment(frame, plan, descriptors=())


def _bound_context(
    resource_ids: tuple[str, ...],
    *,
    release_digest: str,
    principal_scope_digest: str,
) -> BoundResourceContext:
    identity = {
        "principal_id": "operator",
        "principal_scope_digest": principal_scope_digest,
        "ontology_release_digest": release_digest,
        "source_generation": "generation-1",
        "complete": True,
    }
    digest = context_selection_digest(
        kind="screen",
        screen_id="ontology-instances",
        resource_group_id=None,
        resource_ids=resource_ids,
        **identity,
    )
    return BoundResourceContext(
        kind="screen",
        screen_id="ontology-instances",
        resource_ids=resource_ids,
        selection_digest=digest,
        selection_token="context-selection:" + "a" * 32,
        **identity,
    )


def test_property_filter_rejects_multiple_existence_only_predicates() -> None:
    manifest, definition = _typed_fixture(groups=(_RESOURCE_GROUP_GROUP, _VM_GROUP))
    broad = definition.model_copy(
        update={
            "predicates": tuple(
                ObjectPredicate(property=property_name, operator=ObjectPredicateOperator.EXISTS)
                for property_name in ("type", "name", "properties")
            )
        }
    )
    model = _Model(
        frame=_frame(
            measure_concepts=["type", "location", "state"],
            output_shape="property_filtered_resources",
        ),
        plan=_plan(broad),
    )

    outcome = _service(model, manifest).plan(
        utterance="List this group's resources with type, region, and state.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.plan is None
    assert outcome.execution_authority is False
    assert model.plan_calls == 1


def test_property_filter_rejects_unstated_declared_value_operand() -> None:
    manifest, definition = _typed_fixture(groups=(_RESOURCE_GROUP_GROUP, _VM_GROUP))
    narrowed = definition.model_copy(
        update={
            "predicates": (
                ObjectPredicate(
                    property="type",
                    operator=ObjectPredicateOperator.EQUALS,
                    equals="resource-group",
                ),
            )
        }
    )
    model = _Model(
        frame=_frame(output_shape="property_filtered_resources"),
        plan=_plan(narrowed),
    )

    outcome = _service(model, manifest).plan(
        utterance="List this group's resources with type, region, and state.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.plan is None
    assert outcome.execution_authority is False
    assert model.plan_calls == 1


def test_optional_document_augmentation_still_rejects_unstated_filter_operand() -> None:
    manifest, definition = _typed_fixture(
        groups=(_RESOURCE_GROUP_GROUP, _VM_GROUP),
        include_governed_document=True,
    )
    narrowed = definition.model_copy(
        update={
            "predicates": (
                ObjectPredicate(
                    property="type",
                    operator=ObjectPredicateOperator.EQUALS,
                    equals="resource-group",
                ),
            )
        }
    )
    model = _Model(
        frame=_frame(output_shape="property_filtered_resources"),
        plan=_plan(narrowed),
    )
    judgment = SemanticJudgmentProposal(
        primary_intent="query.contextual_resources",
        targets=(),
        requested_facets=("details",),
        document_evidence_mode=SemanticDocumentEvidenceMode.OPTIONAL,
        confidence=0.98,
        ambiguous=False,
        action_posture="advise_only",
        action_subject="none",
        authority="candidate_only",
        execution_authority=False,
    )

    outcome = _service(
        model,
        manifest,
        semantic_judgment=_JudgmentBoundary(judgment),
    ).plan(
        utterance="Show typed resources and consult the runbook.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.plan is None
    assert outcome.execution_authority is False
    assert model.plan_calls == 1


def test_target_health_without_identity_discovers_verified_candidates() -> None:
    container_app = PropertyValueGroup(
        id="compute-container-app",
        values=("compute.container-app",),
        terms=("container app", "container apps"),
    )
    manifest, _definition = _typed_fixture(groups=(container_app,))
    model = _Model(
        frame=_frame(
            operation="validate",
            subject_constraints=["Resource", "my Container App"],
            measure_concepts=["health", "readiness"],
            output_shape="target_health_assessment",
            evidence_requirements=["application_health", "evidence_gaps"],
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="Is my Container App healthy?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.clarification is None
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
    assert outcome.execution_authority is False
    assert model.plan_calls == 0


def test_target_scoped_subtype_query_with_exact_name_continues_planning() -> None:
    container_app = PropertyValueGroup(
        id="compute-container-app",
        values=("compute.container-app",),
        terms=("container app", "container apps"),
    )
    manifest, _definition = _typed_fixture(groups=(container_app,))
    model = _Model(
        frame=_frame(
            subject_constraints=["Resource", "orders-api-prod"],
            measure_concepts=["ingress"],
            output_shape="property_filtered_resources",
        ),
        plan=None,
    )

    outcome = _service(model, manifest).plan(
        utterance="orders-api-prod Container App의 인그레스 구성을 보여줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.clarification is None
    assert outcome.execution_authority is False
    assert model.plan_calls == 0


def test_unstated_value_leaves_the_existence_predicate_unchanged() -> None:
    manifest, definition = _typed_fixture(groups=(_RESOURCE_GROUP_GROUP, _VM_GROUP))
    model = _Model(frame=_frame(output_shape="property_filtered_resources"), plan=_plan(definition))

    predicates = _grounded_predicates(model, manifest, "Show every typed resource.")

    assert predicates == [{"property": "type", "operator": "exists"}]


def test_two_stated_value_groups_leave_the_plan_to_the_planner() -> None:
    manifest, definition = _typed_fixture(groups=(_RESOURCE_GROUP_GROUP, _VM_GROUP))
    model = _Model(frame=_frame(output_shape="property_filtered_resources"), plan=_plan(definition))

    predicates = _grounded_predicates(model, manifest, "리소스그룹 안의 가상 머신을 보여줘")

    assert predicates == [{"property": "type", "operator": "exists"}]


def test_stated_subtype_wins_over_its_broader_category_group() -> None:
    database_group = PropertyValueGroup(
        id="database",
        values=("mysql-server", "postgresql-server"),
        terms=("database", "db"),
    )
    mysql_group = PropertyValueGroup(
        id="mysql-server",
        values=("mysql-server",),
        terms=("mysql",),
    )
    manifest, definition = _typed_fixture(groups=(database_group, mysql_group))
    model = _Model(frame=_frame(output_shape="property_filtered_resources"), plan=_plan(definition))

    predicates = _grounded_predicates(model, manifest, "DB 지연과 MySQL 포화를 조사해줘")

    assert predicates == [{"property": "type", "operator": "equals", "equals": "mysql-server"}]


@pytest.mark.parametrize(
    "utterance",
    (
        "Show the deployed LLMs.",
        "List the GPT models.",
        "배포된 LLM 목록을 보여줘.",
        "GPT 모델 목록을 알려줘.",
    ),
)
def test_llm_inventory_phrases_select_model_deployment_instances(utterance: str) -> None:
    deployment_group = PropertyValueGroup(
        id="llm-model-deployment",
        values=("llm-model-deployment",),
        terms=tuple(
            sorted(
                (
                    "deployed LLMs",
                    "GPT models",
                    "배포된 LLM 목록",
                    "GPT 모델 목록",
                )
            )
        ),
    )
    manifest, definition = _typed_fixture(groups=(deployment_group,))
    model = _Model(frame=_frame(output_shape="property_filtered_resources"), plan=_plan(definition))

    predicates = _grounded_predicates(model, manifest, utterance)

    assert predicates == [
        {
            "property": "type",
            "operator": "equals",
            "equals": "llm-model-deployment",
        }
    ]


def test_a_term_inside_a_longer_word_does_not_ground_a_filter() -> None:
    manifest, definition = _typed_fixture(groups=(_VM_GROUP,))
    model = _Model(frame=_frame(output_shape="property_filtered_resources"), plan=_plan(definition))

    predicates = _grounded_predicates(model, manifest, "Show records for vmss-prod-01.")

    assert predicates == [{"property": "type", "operator": "exists"}]


def test_stated_subtype_bypasses_a_conflicting_planner_filter() -> None:
    manifest, definition = _typed_fixture(groups=(_RESOURCE_GROUP_GROUP, _VM_GROUP))
    narrow = definition.model_copy(
        update={
            "predicates": (
                ObjectPredicate(
                    property="type",
                    operator=ObjectPredicateOperator.EQUALS,
                    equals="storage.account",
                ),
            )
        }
    )
    model = _Model(frame=_frame(output_shape="property_filtered_resources"), plan=_plan(narrow))

    predicates = _grounded_predicates(model, manifest, "리소스그룹 모두 알려줘")

    assert predicates == [{"property": "type", "operator": "equals", "equals": "resource-group"}]
    assert model.plan_calls == 0


def test_hidden_property_plan_is_rejected_before_execution() -> None:
    manifest, definition = _fixture()
    hidden = definition.model_copy(
        update={"predicates": (ObjectPredicate(property="secret", equals="value"),)}
    )
    model = _Model(frame=_frame(), plan=_plan(hidden))

    outcome = _service(model, manifest).plan(
        utterance="Show matching resources",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_scope_denied"
    assert outcome.plan is None


def test_invalid_plan_logs_only_rejection_stage_and_failure_type(caplog) -> None:
    manifest, _definition = _fixture()
    model = _Model(frame=_frame(), plan={"nodes": [], "output_node_ids": []})

    with caplog.at_level(logging.WARNING):
        outcome = _service(model, manifest).plan(
            utterance="Show matching resources",
            prior_turns=(),
            principal=Principal(id="operator", role=Role.READER),
            purpose="operations-review",
        )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    rejection = next(
        record for record in caplog.records if record.message == "semantic_plan_rejected"
    )
    assert rejection.stage == "plan_validation"
    assert rejection.failure_type == "ValidationError"
    assert "Show matching resources" not in caplog.text


def test_successful_plan_logs_only_stage_progress(caplog) -> None:
    manifest, definition = _fixture()

    with caplog.at_level(logging.INFO):
        outcome = _service(_Model(frame=_frame(), plan=_plan(definition)), manifest).plan(
            utterance="Show matching resources",
            prior_turns=(),
            principal=Principal(id="operator", role=Role.READER),
            purpose="operations-review",
        )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    stages = [
        record.stage
        for record in caplog.records
        if record.message == "semantic_planning_stage_completed"
    ]
    assert stages == ["manifest", "frame_proposal", "frame_build", "plan_proposal", "plan_verify"]
    verify = next(
        record
        for record in caplog.records
        if record.message == "semantic_planning_stage_completed" and record.stage == "plan_verify"
    )
    assert verify.plan_nodes == "object_set[Resource;id equals]"
    frame = next(
        record
        for record in caplog.records
        if record.message.startswith("semantic_planning_frame_observed")
    )
    assert frame.output_shape == "resource_list"
    assert frame.getMessage() == (
        "semantic_planning_frame_observed operation=select output_shape=resource_list "
        "subject_types=Resource measure_concepts= unresolved_count=0 "
        "structured_investigation=False"
    )
    assert "Show matching resources" not in caplog.text
    # A predicate operand can carry a tenant identifier, so the shape names the
    # filtered property and its operator and never the value it compares.
    assert "resource-a" not in caplog.text


def test_plan_node_summary_names_selected_functions() -> None:
    digest = f"sha256:{'a' * 64}"
    nodes = (
        OntologyQueryNode(
            node_id="evidence",
            kind=QueryNodeKind.FUNCTION,
            arguments_json='{"function_name":"query.incident_evidence"}',
            output_kind="query.value",
        ),
        OntologyQueryNode(
            node_id="resources",
            kind=QueryNodeKind.OBJECT_SET,
            output_kind="query.table",
        ),
    )
    plan_fields: dict[str, Any] = {
        "ontology_release_digest": digest,
        "semantic_catalog_digest": digest,
        "problem_frame_digest": digest,
        "purpose": "operations-review",
        "caller_role": "reader",
        "nodes": nodes,
        "output_node_ids": ("evidence",),
    }
    plan = OntologyQueryPlan(
        **plan_fields,
        plan_digest=content_digest(
            {
                "schema_version": "1.0.0",
                **{
                    key: value
                    for key, value in plan_fields.items()
                    if key not in {"nodes", "output_node_ids"}
                },
                "nodes": [node.model_dump(mode="json") for node in nodes],
                "output_node_ids": ("evidence",),
                "execution_authority": False,
            }
        ),
    )

    assert _plan_node_summary(plan) == "function:query.incident_evidence,object_set"


def test_execution_receipts_bind_to_intent_goal_ids() -> None:
    manifest, definition = _fixture()
    outcome = _service(_Model(frame=_frame(), plan=_plan(definition)), manifest).plan(
        utterance="Show matching resources",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )
    assert outcome.plan is not None and outcome.intent_graph is not None
    receipt = GoalTaskReceipt(
        task_id="query:resources",
        goal_id="resources",
        intent="object_set",
        capability="query.object_set",
        evidence_mode=GoalEvidenceMode.OPERATIONAL,
        status=TaskStatus.COMPLETED,
        duration_ms=1,
        evidence_refs=("ontology-object-set:sha256:" + ("b" * 64),),
        authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        started_at=NOW,
        completed_at=NOW,
    )
    execution = QueryPlanExecution(
        plan_digest=outcome.plan.plan_digest,
        status="completed",
        results=MappingProxyType({"resources": QueryNodeResult(value={})}),
        receipts=(receipt,),
        output_node_ids=("resources",),
    )

    evidence = build_intent_graph_evidence(
        graph=outcome.intent_graph,
        plan=outcome.plan,
        execution=execution,
    )

    assert evidence.status == "completed"
    assert evidence.goals[0].goal_id == "goal-1"
    assert evidence.goals[0].evidence_refs == receipt.evidence_refs


def test_execution_evidence_preserves_failure_and_truncation_reasons() -> None:
    manifest, definition = _fixture()
    outcome = _service(_Model(frame=_frame(), plan=_plan(definition)), manifest).plan(
        utterance="Show matching resources",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )
    assert outcome.plan is not None and outcome.intent_graph is not None
    receipt = GoalTaskReceipt(
        task_id="query:resources",
        goal_id="resources",
        intent="object_set",
        capability="query.object_set",
        evidence_mode=GoalEvidenceMode.OPERATIONAL,
        status=TaskStatus.FAILED,
        duration_ms=1,
        reason="capability_failed",
        evidence_refs=tuple(f"evidence:{index}" for index in range(13)),
        started_at=NOW,
        completed_at=NOW,
    )
    execution = QueryPlanExecution(
        plan_digest=outcome.plan.plan_digest,
        status="failed",
        results=MappingProxyType({}),
        receipts=(receipt,),
        output_node_ids=("resources",),
    )

    evidence = build_intent_graph_evidence(
        graph=outcome.intent_graph,
        plan=outcome.plan,
        execution=execution,
    )

    assert evidence.goals[0].reason == "capability_failed+evidence_refs_truncated"
    assert len(evidence.goals[0].evidence_refs) == 12


def test_coordinator_shadow_plan_does_not_change_compatibility_result() -> None:
    manifest, definition = _fixture()
    planner = _service(_Model(frame=_frame(), plan=_plan(definition)), manifest)
    coordinator = ConversationCoordinator(
        tools=[_InventoryTool()],
        config=CoordinatorConfig(semantic_planning_mode="shadow"),
        semantic_planner=planner,
    )
    session = ConversationSession(
        session_id="session-1",
        principal=Principal(id="operator", role=Role.READER),
        channel_id="web",
    )

    result = coordinator.handle_turn(session=session, message="query_inventory Resource")

    assert result == ToolResult(status="ok", preview="inventory result")
    shadow_turn = next(
        turn for turn in session.turns if turn.content.startswith("semantic planning")
    )
    assert "disposition=planned" in shadow_turn.content
    assert "plan=sha256:" in shadow_turn.content


def test_catalog_manifest_provider_filters_role_and_rejects_break_glass() -> None:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "secret": PropertyDecl(
                type=PropertyType.STRING,
                access_scope=CeilingRole.OWNER,
            ),
        },
    )
    release = build_ontology_release(object_types=(resource,))
    provider = CatalogQueryManifestProvider(release=release, object_types=(resource,))

    manifest = provider.manifest_for(
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert set(manifest.descriptors[0]["properties"]) == {"id"}
    with pytest.raises(PermissionError, match="break-glass"):
        provider.manifest_for(
            principal=Principal(id="operator", role=Role.BREAK_GLASS),
            purpose="operations-review",
        )


async def test_semantic_runtime_executes_verified_plan_and_projects_terminal_graph() -> None:
    manifest, definition = _fixture()
    planner = _service(_Model(frame=_frame(), plan=_plan(definition)), manifest)
    observed: list[QueryNodeProgress] = []

    async def object_set_handler(node, dependencies):  # type: ignore[no-untyped-def]
        assert node.kind is QueryNodeKind.OBJECT_SET
        assert dependencies == {}
        return QueryNodeResult(
            value={"rows": ["resource-a"]},
            evidence_refs=("inventory:1",),
            authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
        )

    async def observe(progress: QueryNodeProgress) -> None:
        observed.append(progress)

    runtime = SemanticConversationRuntime(
        planner=planner,
        executor=OntologyQueryPlanExecutor(
            handlers={QueryNodeKind.OBJECT_SET: object_set_handler},
            now=lambda: NOW,
        ),
    )

    result = await runtime.handle(
        utterance="현재 운영 객체를 보여줘",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        progress_observer=observe,
    )

    assert [item.status for item in observed] == ["running", TaskStatus.COMPLETED]
    assert result.disposition == "answered"
    assert result.execution_authority is False
    assert result.intent_graph is not None
    assert result.intent_graph["schema_version"] == 2
    assert result.intent_graph_evidence is not None
    assert result.intent_graph_evidence["schema_version"] == 2
    assert result.intent_graph_evidence["status"] == "completed"
    assert result.intent_graph_evidence["goals"][0]["authority"] == "server_inventory_graph"
    assert result.intent_graph_evidence["goals"][0]["evidence_refs"] == ["inventory:1"]
