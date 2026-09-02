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
    EvidenceAuthority,
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


def test_project_semantic_assurance_preserves_resource_health_unknown_limitation() -> None:
    result = _function_result(
        function_name="query.resource_health_inventory",
        value={
            "rows": [
                {
                    "row_id": "resource-health-0001",
                    "values": {
                        "name": "service-a",
                        "evidence_family": "resource_health",
                        "coverage_state": "observed",
                        "availability_state": "unknown",
                        "provider_observed_at": "2026-08-22T00:00:00+00:00",
                        "execution_authority": False,
                    },
                }
            ],
            "complete": True,
            "truncation_reason": None,
        },
    )

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.fact_kinds == (
        "evidence.observed_at",
        "resource.identity",
        "resource_health.availability_state",
        "resource_health.coverage",
    )
    assert observation.limitation_kinds == ("resource_health.unknown_is_not_healthy",)


def test_resource_state_assurance_does_not_claim_missing_identity() -> None:
    result = _function_result(
        function_name="query.resource_state_inventory",
        value={
            "rows": [
                {
                    "row_id": "resource-state-0001",
                    "values": {
                        "name": None,
                        "state_concept": "resource_state.running",
                        "source_observed_at": "2026-08-22T00:00:00+00:00",
                        "execution_authority": False,
                    },
                }
            ],
            "complete": True,
            "truncation_reason": None,
        },
    )

    observation = project_semantic_assurance(result, disposition="answered")

    assert "resource.identity" not in observation.fact_kinds
    assert observation.fact_kinds == (
        "evidence.observed_at",
        "resource.runtime_state",
        "resource_state.collection",
    )


def test_project_semantic_assurance_blocks_all_clear_for_incomplete_health_coverage() -> None:
    result = _function_result(
        function_name="query.resource_health_inventory",
        value={
            "rows": [
                {
                    "row_id": "resource-health-0001",
                    "values": {
                        "name": "service-a",
                        "evidence_family": "resource_health",
                        "coverage_state": "scope_unreadable",
                        "availability_state": None,
                        "execution_authority": False,
                    },
                }
            ],
            "complete": False,
            "truncation_reason": "scope_unreadable",
        },
    )

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.fact_kinds == (
        "resource.identity",
        "resource_health.coverage",
    )
    assert observation.limitation_kinds == (
        "incomplete_evidence_cannot_prove_health",
        "resource_health.scope_unreadable",
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


def test_project_semantic_assurance_bounds_only_verified_relationship_paths() -> None:
    relationships = [
        {
            "link_type": f"relationship_{index:02d}",
            "from_type": "Resource",
            "to_type": f"RelatedType{index:02d}",
            "cardinality": "many_to_many",
            "description": "Reviewed relationship.",
        }
        for index in range(18)
    ]
    result = _function_result(
        function_name="query.ontology_relationships",
        value={
            "object_types": ["Resource"],
            "relationships": relationships,
            "complete": True,
            "authority": "ontology_release",
            "ontology_release_digest": _DIGEST,
            "execution_authority": False,
        },
    )
    result.planning.plan.nodes[0].arguments["arguments"] = {
        "object_types": ["Resource"],
        "limit": 100,
    }
    result.planning.plan.ontology_release_digest = _DIGEST

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.link_types == tuple(f"relationship_{index:02d}" for index in range(18))
    assert len(observation.ontology_paths) == 16


def test_schema_ownership_relationships_do_not_claim_current_instance_identity() -> None:
    result = _function_result(
        function_name="query.ontology_relationships",
        value={
            "object_types": ["Agent", "Resource"],
            "relationships": [
                {
                    "link_type": "owns",
                    "from_type": "Agent",
                    "to_type": "Resource",
                    "cardinality": "many_to_many",
                    "description": "Reviewed ownership declaration.",
                }
            ],
            "complete": True,
            "authority": "ontology_release",
            "ontology_release_digest": _DIGEST,
            "execution_authority": False,
        },
    )

    observation = project_semantic_assurance(result, disposition="held")

    assert "agent.identity" not in observation.fact_kinds
    assert "resource.identity" not in observation.fact_kinds
    assert "agent.ownership_scope" not in observation.fact_kinds
    assert observation.limitation_kinds == (
        "catalog_relationships_do_not_prove_current_mapping",
        "ontology_ownership_does_not_grant_execution",
    )


def test_composite_instance_path_entails_current_service_agent_ownership() -> None:
    path_node = SimpleNamespace(
        node_id="service-agent-paths",
        kind=SimpleNamespace(value="ontology_instance_path"),
        depends_on=("schema-1", "schema-2", "schema-3"),
        arguments={
            "root_selector": {"kind": "object_type", "name": "BusinessService"},
            "steps": [
                {
                    "link_type": "implemented_by",
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Workload"},
                },
                {
                    "link_type": "workload_runs_on",
                    "direction": "outgoing",
                    "selector": {"kind": "object_type", "name": "Resource"},
                },
                {
                    "link_type": "owns",
                    "direction": "incoming",
                    "selector": {"kind": "object_type", "name": "Agent"},
                },
            ],
        },
    )
    frame = SimpleNamespace(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Agent", "BusinessService", "Resource", "Workload"),
        measure_concepts=(),
        temporal_scope={"kind": "current"},
        output_shape="ontology_relationships",
        frame_digest=_DIGEST,
    )
    planning = SimpleNamespace(
        plan=SimpleNamespace(nodes=(path_node,)),
        frame=frame,
        investigation_intent=None,
    )
    table = QueryTable(
        rows=(
            QueryRow.from_values(
                "path-1",
                {
                    "root_id": "service:a",
                    "root_type": "BusinessService",
                    "step_1_id": "workload:a",
                    "step_1_type": "Workload",
                    "step_2_id": "resource:a",
                    "step_2_type": "Resource",
                    "step_3_id": "agent:a",
                    "step_3_type": "Agent",
                    "target_id": "agent:a",
                    "target_type": "Agent",
                    "execution_authority": False,
                },
            ),
        ),
        complete=True,
    )
    result = QueryNodeResult(
        value=table,
        evidence_refs=("ontology-instance-path:proof",),
        authority=EvidenceAuthority.SERVER_ONTOLOGY_INSTANCE_PATH,
        authority_inputs=(
            EvidenceAuthority.SERVER_INVENTORY_GRAPH,
            EvidenceAuthority.SERVER_ONTOLOGY_MANIFEST,
        ),
    )
    receipt = GoalTaskReceipt(
        task_id="query:service-agent-paths",
        goal_id="service-agent-paths",
        intent="ontology_instance_path",
        capability="query.ontology_instance_path",
        evidence_mode=GoalEvidenceMode.OPERATIONAL,
        status=TaskStatus.COMPLETED,
        duration_ms=1,
        evidence_refs=result.evidence_refs,
        authority=result.authority,
        authority_inputs=result.authority_inputs,
        started_at="2026-08-22T00:00:00Z",
        completed_at="2026-08-22T00:00:00Z",
    )
    runtime_result = RuntimeSemanticTurnResult(
        disposition="answered",
        reason="semantic_execution_completed",
        planning=cast(Any, planning),
        execution=QueryPlanExecution(
            plan_digest=_DIGEST,
            status="completed",
            results=MappingProxyType({"service-agent-paths": result}),
            receipts=(receipt,),
            output_node_ids=("service-agent-paths",),
        ),
        intent_graph={},
        intent_graph_evidence={},
    )

    observation = project_semantic_assurance(runtime_result, disposition="answered")

    assert observation.fact_kinds == (
        "agent.identity",
        "agent.ownership_scope",
        "relationship.path",
        "service.identity",
    )
    assert observation.limitation_kinds == ("ontology_ownership_does_not_grant_execution",)
    assert len(observation.ontology_paths) == 1
    assert len(observation.ontology_paths[0].steps) == 3
    assert "object_set" in observation.capabilities
    assert "ontology_relationships" in observation.capabilities


def test_project_semantic_assurance_entails_rule_trace_claims() -> None:
    result = _function_result(
        function_name="query.ontology_relationships",
        value={
            "object_types": ["Rule", "ActionType", "ResourceType", "SignalType"],
            "relationships": [
                {
                    "link_type": "applies_to",
                    "from_type": "Rule",
                    "to_type": "ResourceType",
                    "cardinality": "many_to_many",
                    "description": "Reviewed applicability.",
                },
                {
                    "link_type": "remediates",
                    "from_type": "Rule",
                    "to_type": "ActionType",
                    "cardinality": "many_to_many",
                    "description": "Reviewed remediation.",
                },
                {
                    "link_type": "triggered_by",
                    "from_type": "Rule",
                    "to_type": "SignalType",
                    "cardinality": "many_to_many",
                    "description": "Reviewed trigger.",
                },
            ],
            "complete": True,
            "authority": "ontology_release",
            "ontology_release_digest": _DIGEST,
            "execution_authority": False,
        },
    )

    observation = project_semantic_assurance(result, disposition="answered")

    assert {
        "action_type.identity",
        "resource_type.identity",
        "rule.identity",
        "signal_type.identity",
    } <= set(observation.fact_kinds)
    assert observation.limitation_kinds == ("catalog_relationships_do_not_prove_current_finding",)


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
            "impact_evidence": [{"kind": "recorded_impact"}],
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
        "incident.activity",
        "incident.cause",
        "incident.evidence",
        "incident.identity",
        "incident.impact",
        "incident.profile",
    )
    assert observation.limitation_kinds == (
        "missing_evidence_must_be_explicit",
        "missing_historical_evidence_must_be_explicit",
        "recorded_cause_requires_citations",
        "retained_history_bounds_must_be_explicit",
    )
    assert observation.object_types == ("Incident",)


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


def test_project_semantic_assurance_content_addresses_free_form_measure_concepts() -> None:
    result = _runtime_result(nodes=())
    result.planning.frame.measure_concepts = ("mapped service", "metric.cpu.utilization")

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.frame is not None
    assert observation.frame.measure_concepts == (
        "concept:6c85c5c8525499fd0c600bca6673cd3bcb52d3ed3b71bdc6f95cfe2e92e4b007",
        "metric.cpu.utilization",
    )


def test_project_semantic_assurance_preserves_named_temporal_scope() -> None:
    current = _runtime_result(nodes=())
    current.planning.frame.temporal_scope = {"kind": "current"}
    historical = _runtime_result(nodes=())
    historical.planning.frame.temporal_scope = {"kind": "historical"}

    current_observation = project_semantic_assurance(current, disposition="action_draft")
    historical_observation = project_semantic_assurance(
        historical,
        disposition="action_draft",
    )

    assert current_observation.frame is not None
    assert current_observation.frame.temporal_scope == "current"
    assert historical_observation.frame is not None
    assert historical_observation.frame.temporal_scope == "historical"


def test_project_semantic_assurance_prefers_windowed_frame_over_output_fallback() -> None:
    result = _runtime_result(nodes=())
    result.planning.frame.temporal_scope = {"kind": "windowed"}
    result.planning.frame.output_shape = "temporal_comparison"

    observation = project_semantic_assurance(result, disposition="unsupported")

    assert observation.frame is not None
    assert observation.frame.temporal_scope == "windowed"


def test_project_semantic_assurance_uses_output_fallback_without_frame_scope() -> None:
    result = _runtime_result(nodes=())
    result.planning.frame.temporal_scope = {}
    result.planning.frame.output_shape = "temporal_comparison"

    observation = project_semantic_assurance(result, disposition="unsupported")

    assert observation.frame is not None
    assert observation.frame.temporal_scope == "historical"


def test_project_semantic_assurance_marks_current_state_output_current() -> None:
    result = _runtime_result(nodes=())
    result.planning.frame.temporal_scope = {}
    result.planning.frame.output_shape = "target_current_state"

    observation = project_semantic_assurance(result, disposition="answered")

    assert observation.frame is not None
    assert observation.frame.temporal_scope == "current"


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
