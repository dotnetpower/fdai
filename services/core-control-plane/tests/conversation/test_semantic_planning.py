"""Schema-constrained semantic planning and intent graph tests."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

import pytest
from fdai.core.conversation.coordinator import ConversationCoordinator, CoordinatorConfig
from fdai.core.conversation.intent_graph import build_intent_graph_evidence
from fdai.core.conversation.semantic_manifest import CatalogQueryManifestProvider
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import (
    SemanticFrameProposal,
    SemanticPlanningDisposition,
)
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import ConversationSession, Principal, Role, Turn
from fdai.core.conversation.tools import ToolResult
from fdai.core.ontology_platform import (
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
    QueryNodeKind,
    TaskStatus,
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


def test_unresolved_meaning_returns_one_clarification_without_plan() -> None:
    manifest, definition = _fixture()
    model = _Model(
        frame=_frame(
            unresolved_terms=["requests"],
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


def test_unbound_incident_reference_clarifies_without_model_work() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _service(model, manifest).plan(
        utterance=(
            "Investigate this incident using the available evidence and report the cause, "
            "gaps, and next safe step."
        ),
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.reason == "semantic_clarification_required"
    assert outcome.clarification == "Which incident should I investigate?"
    assert outcome.plan is None
    assert outcome.execution_authority is False
    assert model.frame_calls == 0
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


def test_frame_proposal_rejects_noncanonical_evidence_requirement() -> None:
    with pytest.raises(ValidationError):
        SemanticFrameProposal.model_validate(
            _frame(evidence_requirements=["read only configuration evidence"])
        )


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
    assert "Show matching resources" not in caplog.text


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
