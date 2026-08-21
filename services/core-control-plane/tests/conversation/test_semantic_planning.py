"""Schema-constrained semantic planning and intent graph tests."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

import pytest
from fdai.core.conversation.coordinator import ConversationCoordinator, CoordinatorConfig
from fdai.core.conversation.intent_graph import build_intent_graph_evidence
from fdai.core.conversation.semantic_manifest import CatalogQueryManifestProvider
from fdai.core.conversation.semantic_planning import SemanticPlanningService, _plan_node_summary
from fdai.core.conversation.semantic_planning_models import (
    SemanticFrameProposal,
    SemanticPlanningDisposition,
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
from fdai.core.ontology_platform.property_values import PropertyValueDomain, PropertyValueGroup
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import (
    GoalEvidenceMode,
    GoalTaskReceipt,
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    TaskStatus,
    content_digest,
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


def _service(model: _Model, manifest: Any) -> SemanticPlanningService:
    return SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        now=lambda: NOW,
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


def _typed_fixture(*, groups: tuple[PropertyValueGroup, ...]) -> tuple[Any, ObjectSetDefinition]:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "type": PropertyDecl(type=PropertyType.STRING, required=True),
            "name": PropertyDecl(type=PropertyType.STRING),
        },
    )
    release = build_ontology_release(object_types=(resource,))
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
        property_values=(
            PropertyValueDomain(
                object_type="Resource",
                property_name="type",
                values=("compute.vm", "resource-group", "storage.account"),
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


def _grounded_predicates(model: _Model, manifest: Any, utterance: str) -> list[dict[str, Any]]:
    outcome = _service(model, manifest).plan(
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
        {"operator": "exists", "property": "name"},
        {"property": "type", "operator": "equals", "equals": "resource-group"},
    ]


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


def test_a_term_inside_a_longer_word_does_not_ground_a_filter() -> None:
    manifest, definition = _typed_fixture(groups=(_VM_GROUP,))
    model = _Model(frame=_frame(output_shape="property_filtered_resources"), plan=_plan(definition))

    predicates = _grounded_predicates(model, manifest, "Show records for vmss-prod-01.")

    assert predicates == [{"property": "type", "operator": "exists"}]


def test_a_planner_supplied_value_filter_is_never_rewritten() -> None:
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

    assert predicates == [{"property": "type", "operator": "equals", "equals": "storage.account"}]


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

    async def object_set_handler(node, dependencies):  # type: ignore[no-untyped-def]
        assert node.kind is QueryNodeKind.OBJECT_SET
        assert dependencies == {}
        return QueryNodeResult(value={"rows": ["resource-a"]}, evidence_refs=("inventory:1",))

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
    )

    assert result.disposition == "answered"
    assert result.execution_authority is False
    assert result.intent_graph is not None
    assert result.intent_graph["schema_version"] == 2
    assert result.intent_graph_evidence is not None
    assert result.intent_graph_evidence["status"] == "completed"
    assert result.intent_graph_evidence["goals"][0]["evidence_refs"] == ["inventory:1"]
