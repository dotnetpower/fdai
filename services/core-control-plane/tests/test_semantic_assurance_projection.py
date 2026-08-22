"""Focused typed semantic assurance projection tests."""

from __future__ import annotations

from types import MappingProxyType, SimpleNamespace
from typing import Any, cast

from fdai.core.conversation.semantic_runtime import (
    SemanticTurnResult as RuntimeSemanticTurnResult,
)
from fdai.core.ontology_platform import QueryNodeResult, QueryPlanExecution
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai_core_service.semantic_assurance_projection import project_semantic_assurance
from fdai_service_contracts.ontology_query import (
    GoalEvidenceMode,
    GoalTaskReceipt,
    SemanticOperation,
    TaskStatus,
)

_DIGEST = "sha256:" + ("a" * 64)


def test_project_semantic_assurance_uses_verified_plan_and_typed_result_only() -> None:
    object_node = SimpleNamespace(
        node_id="resource",
        kind=SimpleNamespace(value="object_set"),
        depends_on=(),
        arguments={"definition": {"selector": {"kind": "object_type", "name": "Resource"}}},
    )
    function_node = SimpleNamespace(
        node_id="state",
        kind=SimpleNamespace(value="function"),
        depends_on=("resource",),
        arguments={"function_name": "query.resource_current_state", "arguments": {}},
    )
    result = _runtime_result(nodes=(object_node, function_node))

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.frame is not None
    assert observation.frame.subject_types == ("Resource",)
    assert observation.capabilities == ("function", "object_set", "resource_current_state")
    assert observation.object_types == ("Resource",)
    assert observation.function_types == ("query.resource_current_state",)
    assert observation.evidence_posture == "fresh"
    assert observation.fact_kinds == ()
    assert observation.read_performed is True


def test_project_semantic_assurance_ignores_unregistered_output_metadata() -> None:
    result = _runtime_result(
        nodes=(),
        value={
            "semantic_assurance": {
                "schema_version": "1.0.0",
                "fact_kinds": ["resource.identity"],
                "limitation_kinds": ["missing_runtime_evidence"],
                "claim_kinds": [],
                "execution_authority": False,
            }
        },
    )

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.fact_kinds == ()
    assert observation.limitation_kinds == ()
    assert observation.claim_kinds == ()


def test_project_semantic_assurance_entails_current_state_claims_from_typed_output() -> None:
    function_node = SimpleNamespace(
        node_id="state",
        kind=SimpleNamespace(value="function"),
        depends_on=("resource",),
        arguments={"function_name": "query.resource_current_state", "arguments": {}},
    )
    result = _runtime_result(
        nodes=(function_node,),
        result_node_id="state",
        value={
            "rows": [
                {
                    "row_id": "resource-current-state",
                    "values": {
                        "name": "example-resource",
                        "provisioning_status": "Succeeded",
                        "running_status": "Running",
                        "source_observed_at": None,
                        "inventory_read_at": "2026-08-22T00:00:00+00:00",
                        "execution_authority": False,
                    },
                }
            ],
            "complete": False,
            "truncation_reason": "source_observed_at_unavailable",
        },
    )

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.fact_kinds == (
        "resource.identity",
        "resource.provisioning_state",
        "resource.runtime_state",
    )
    assert observation.limitation_kinds == ("missing_resource_state_is_unknown",)
    assert observation.claim_kinds == (
        "missing_resource_state_is_unknown",
        "resource.identity",
        "resource.provisioning_state",
        "resource.runtime_state",
    )


def test_project_semantic_assurance_entails_relationship_schema_claims() -> None:
    result = _function_result(
        function_name="query.ontology_relationships",
        value={
            "object_types": ["Resource", "NetworkRoute"],
            "relationships": [
                {
                    "link_type": "routes_via_route",
                    "from_type": "Resource",
                    "to_type": "NetworkRoute",
                    "cardinality": "many_to_many",
                    "description": "Reviewed route declaration.",
                }
            ],
            "complete": True,
            "authority": "ontology_release",
            "ontology_release_digest": _DIGEST,
            "execution_authority": False,
        },
    )

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.fact_kinds == (
        "relationship.direction",
        "relationship.path",
        "relationship.route",
    )
    assert observation.limitation_kinds == ()


def test_project_semantic_assurance_entails_evidence_health_claims() -> None:
    result = _function_result(
        function_name="query.ontology_evidence_health",
        value={
            "rows": [
                {
                    "row_id": "evidence-health:Resource",
                    "values": {
                        "ontology_release_digest": _DIGEST,
                        "object_type": "Resource",
                        "availability": "available",
                        "source": {
                            "generation": "generation-1",
                            "observed_at": "2026-08-22T00:00:00+00:00",
                        },
                        "freshness_state": "stale",
                        "complete": False,
                        "conflicts": ["state"],
                        "execution_authority": False,
                        "mutation_authority": False,
                    },
                }
            ],
            "complete": False,
            "truncation_reason": "source_incomplete",
        },
    )

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.fact_kinds == (
        "evidence.completeness",
        "evidence.conflicts",
        "evidence.freshness",
        "evidence.observed_at",
        "evidence.source_revision",
    )
    assert observation.limitation_kinds == ("incomplete_evidence_cannot_prove_health",)
    assert observation.evidence_posture == "conflicting"


def test_project_semantic_assurance_entails_incident_claims_and_gaps() -> None:
    result = _function_result(
        function_name="query.incident_evidence",
        value={
            "incident_id": "incident-1",
            "correlation_id": "correlation-1",
            "incident_profile": {"title": "Recorded symptom"},
            "correlated_evidence": [
                {
                    "audit_ref": "audit:1",
                    "action_kind": "incident.opened",
                    "recorded_at": "2026-08-22T00:00:00+00:00",
                }
            ],
            "root_cause": {"cause": "recorded"},
            "impact_evidence": [],
            "grounded_citations": [{"kind": "audit", "ref": "audit:1"}],
            "evidence_gaps": ["impact_evidence_missing", "correlated_audit_truncated"],
            "evidence_refs": ["audit:1"],
            "truncated": True,
            "authority": "audit_projection",
            "cause_claim_supported": True,
            "execution_authority": False,
        },
    )

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.fact_kinds == (
        "activity.operation",
        "activity.recorded_at",
        "evidence.completeness",
        "evidence.support",
        "incident.cause",
        "incident.evidence",
        "incident.identity",
        "incident.profile",
    )
    assert observation.limitation_kinds == (
        "missing_evidence_must_be_explicit",
        "retained_history_bounds_must_be_explicit",
    )


def test_project_semantic_assurance_entails_action_declaration_safety_claims() -> None:
    result = _function_result(
        function_name="query.ontology_declaration",
        value={
            "rows": [
                {
                    "row_id": "action:ops.restart-service",
                    "values": {
                        "ontology_release_digest": _DIGEST,
                        "declaration_kind": "action",
                        "declaration_name": "ops.restart-service",
                        "section": "detail",
                        "declaration": {
                            "rollback_contract": "state_forward_only",
                            "promotion_gate": {"min_samples": 30},
                            "preconditions": [{"kind": "graph_fresh_within_seconds"}],
                            "stop_conditions": [{"kind": "time_box_exceeded_seconds"}],
                            "blast_radius": {"computation": "static_enum"},
                            "argument_schema": {"type": "object"},
                            "ceiling_by_tier": {"t0": {"max_autonomy": "enforce_hil"}},
                        },
                        "redaction_reasons": [],
                        "execution_authority": False,
                        "mutation_authority": False,
                    },
                }
            ],
            "complete": True,
            "truncation_reason": None,
        },
    )

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.fact_kinds == (
        "action_type.authority_ceiling",
        "action_type.constraints",
        "action_type.identity",
        "action_type.safeguards",
    )
    assert observation.limitation_kinds == ()


def test_project_semantic_assurance_marks_no_read_terminal_as_unavailable() -> None:
    planning = SimpleNamespace(plan=None, frame=None, investigation_intent=None)
    result = RuntimeSemanticTurnResult(
        disposition="clarification",
        reason="semantic_clarification_required",
        planning=cast(Any, planning),
    )

    observation = project_semantic_assurance(result, disposition="clarification")

    assert observation.frame is None
    assert observation.evidence_posture == "unavailable"
    assert observation.read_performed is False
    assert observation.authority_posture == "read_only"


def _function_result(*, function_name: str, value: object) -> RuntimeSemanticTurnResult:
    function_node = SimpleNamespace(
        node_id="function-result",
        kind=SimpleNamespace(value="function"),
        depends_on=(),
        arguments={"function_name": function_name, "arguments": {}},
    )
    return _runtime_result(
        nodes=(function_node,),
        result_node_id="function-result",
        value=value,
    )


def _runtime_result(
    *,
    nodes: tuple[object, ...],
    value: object | None = None,
    result_node_id: str = "resource",
) -> RuntimeSemanticTurnResult:
    frame = SimpleNamespace(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=(),
        temporal_scope={},
        output_shape="resource_current_state",
        frame_digest=_DIGEST,
    )
    plan = SimpleNamespace(nodes=nodes)
    planning = SimpleNamespace(plan=plan, frame=frame, investigation_intent=None)
    receipt = GoalTaskReceipt(
        task_id="query:resource",
        goal_id="resource",
        intent="object_set",
        capability="query.object_set",
        evidence_mode=GoalEvidenceMode.OPERATIONAL,
        status=TaskStatus.COMPLETED,
        duration_ms=1,
        evidence_refs=("inventory:one",),
        started_at="2026-08-22T00:00:00Z",
        completed_at="2026-08-22T00:00:00Z",
    )
    table = value or QueryTable(
        rows=(QueryRow.from_values("resource", {"state": "running"}),),
        complete=True,
    )
    execution = QueryPlanExecution(
        plan_digest=_DIGEST,
        status="completed",
        results=MappingProxyType({result_node_id: QueryNodeResult(value=table)}),
        receipts=(receipt,),
        output_node_ids=(result_node_id,),
    )
    return RuntimeSemanticTurnResult(
        disposition="answered",
        reason="semantic_execution_completed",
        planning=cast(Any, planning),
        execution=execution,
        intent_graph={},
        intent_graph_evidence={},
    )
