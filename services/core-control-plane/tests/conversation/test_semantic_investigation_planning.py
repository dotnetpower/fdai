"""Deterministic evidence-wave compilation for verified investigations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.conversation.intent_graph import build_intent_graph_evidence
from fdai.core.conversation.semantic_investigation import (
    InvestigationIntentProposal,
    verify_investigation_intent,
)
from fdai.core.conversation.semantic_investigation_planning import (
    InvestigationClarificationRequiredError,
    InvestigationTimeWindows,
    compile_investigation_plan,
)
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import SemanticPlanningDisposition
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    METRIC_ARGUMENT_SCHEMAS,
    TOPOLOGY_ARGUMENT_SCHEMAS,
    OntologyQueryPlanVerifier,
    QueryPlanExecution,
    build_query_manifest,
)
from fdai.core.ontology_platform.resource_activity_queries import (
    RESOURCE_ACTIVITY_FUNCTION_NAME,
    resource_activity_function_type,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    LinkCardinality,
    OntologyLinkType,
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

NOW = datetime(2026, 8, 20, 4, 0, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)
METRICS = ("dependency.latency", "resource.saturation", "service.latency")


class _ManifestProvider:
    def manifest_for(self, *, principal: Principal, purpose: str):  # type: ignore[no-untyped-def]
        assert principal.role is Role.READER
        assert purpose == "operations-review"
        return _manifest()


class _InvestigationModel:
    def __init__(self, frame: dict[str, object]) -> None:
        self.frame = frame
        self.frame_calls = 0
        self.plan_calls = 0

    def propose_frame(self, **_kwargs: object) -> dict[str, object]:
        self.frame_calls += 1
        return self.frame

    def propose_plan(self, **_kwargs: object) -> dict[str, object]:
        self.plan_calls += 1
        raise AssertionError("verified investigation intent MUST use the server compiler")


def _span(utterance: str, text: str) -> dict[str, object]:
    start = utterance.index(text)
    return {"start": start, "end": start + len(text), "text": text}


def _manifest():  # type: ignore[no-untyped-def]
    activity_function = resource_activity_function_type()
    service = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "name": PropertyDecl(type=PropertyType.STRING, required=True),
        },
    )
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    workload = OntologyObjectType(
        schema_version="1.0.0",
        name="Workload",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    implementation = OntologyLinkType(
        schema_version="1.0.0",
        name="service_implemented_by_workload",
        version="1.0.0",
        from_type="BusinessService",
        to_type="Workload",
        cardinality=LinkCardinality.ONE_TO_MANY,
    )
    placement = OntologyLinkType(
        schema_version="1.0.0",
        name="workload_runs_on_resource",
        version="1.0.0",
        from_type="Workload",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    release = build_ontology_release(
        object_types=(service, workload, resource),
        link_types=(implementation, placement),
        function_types=(activity_function,),
    )
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(service, workload, resource),
        link_types=(implementation, placement),
        functions=(activity_function,),
        bound_function_names=(RESOURCE_ACTIVITY_FUNCTION_NAME,),
    )


def _verified_intent(  # type: ignore[no-untyped-def]
    *,
    target_types: tuple[str, ...] = ("BusinessService",),
    ambiguous_target: bool = False,
):
    utterance = "A서비스가 갑자기 왜 느려졌어?"
    entities: list[dict[str, object]] = [
        {
            "mention_id": "target",
            "span": _span(utterance, "A서비스"),
            "role": "affected_target",
            "object_type_candidates": list(target_types),
        }
    ]
    if ambiguous_target:
        entities.append(
            {
                "mention_id": "second-target",
                "span": _span(utterance, "A서비스"),
                "role": "affected_target",
                "object_type_candidates": ["BusinessService"],
            }
        )
    proposal = InvestigationIntentProposal.model_validate(
        {
            "operation": "explain_change",
            "entities": entities,
            "symptom_measures": [
                {
                    "measure_id": "latency",
                    "span": _span(utterance, "느려졌어"),
                    "concept_id": "service.latency",
                    "target_mention_id": "target",
                    "direction": "increase",
                }
            ],
            "primary_symptom_measure_id": "latency",
            "temporal_cues": [
                {
                    "cue_id": "onset",
                    "span": _span(utterance, "갑자기"),
                    "role": "onset",
                }
            ],
            "relationship_intents": [
                {
                    "relationship_id": "dependencies",
                    "span": _span(utterance, "왜"),
                    "source_mention_id": "target",
                    "target_mention_id": None,
                    "query_side_candidates": [
                        "service_implemented_by_workload.outgoing",
                        "workload_runs_on_resource.outgoing",
                    ],
                }
            ],
            "hypotheses": [
                {
                    "hypothesis_id": "dependency-latency",
                    "span": _span(utterance, "왜"),
                    "relationship_id": "dependencies",
                    "cause_measure_concept": "dependency.latency",
                    "effect_measure_id": "latency",
                    "competing_explanations": ["resource-saturation"],
                },
                {
                    "hypothesis_id": "resource-saturation",
                    "span": _span(utterance, "왜"),
                    "relationship_id": "dependencies",
                    "cause_measure_concept": "resource.saturation",
                    "effect_measure_id": "latency",
                    "competing_explanations": ["dependency-latency"],
                },
            ],
            "evidence_standard": "support_and_refutation",
            "answer_shape": "diagnosis",
            "confidence": 0.9,
        }
    )
    return verify_investigation_intent(
        proposal,
        utterance=utterance,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
    )


def _verifier() -> OntologyQueryPlanVerifier:
    enabled_extensions = (
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.METRIC_COMPARISON,
        QueryNodeKind.TOPOLOGY_AT,
        QueryNodeKind.TOPOLOGY_DIFF,
        QueryNodeKind.EVIDENCE_JOIN,
    )
    all_schemas = {**TOPOLOGY_ARGUMENT_SCHEMAS, **METRIC_ARGUMENT_SCHEMAS}
    schemas = {kind: all_schemas[kind] for kind in enabled_extensions}
    return OntologyQueryPlanVerifier(
        available_kinds=(
            QueryNodeKind.OBJECT_SET,
            QueryNodeKind.FUNCTION,
            QueryNodeKind.RELATIONSHIP_TRAVERSAL,
            QueryNodeKind.METRIC_SCOPE_SERIES,
            QueryNodeKind.METRIC_COMPARISON,
            QueryNodeKind.TOPOLOGY_AT,
            QueryNodeKind.TOPOLOGY_DIFF,
            QueryNodeKind.EVIDENCE_JOIN,
        ),
        extension_argument_schemas=schemas,
        reviewed_metric_concepts=METRICS,
    )


def _windows() -> InvestigationTimeWindows:
    return InvestigationTimeWindows(
        baseline_start=NOW - timedelta(minutes=20),
        baseline_end=NOW - timedelta(minutes=10),
        current_start=NOW - timedelta(minutes=10),
        current_end=NOW,
        known_at=NOW,
    )


def test_compiler_builds_entity_topology_temporal_and_competing_hypothesis_waves() -> None:
    plan = compile_investigation_plan(
        _verified_intent(),
        manifest=_manifest(),
        verifier=_verifier(),
        windows=_windows(),
        purpose="operations-review",
    )

    assert tuple(node.kind for node in plan.nodes) == (
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.RELATIONSHIP_TRAVERSAL,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.METRIC_COMPARISON,
        QueryNodeKind.TOPOLOGY_AT,
        QueryNodeKind.TOPOLOGY_AT,
        QueryNodeKind.TOPOLOGY_DIFF,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.EVIDENCE_JOIN,
        QueryNodeKind.METRIC_SCOPE_SERIES,
        QueryNodeKind.EVIDENCE_JOIN,
    )
    assert plan.output_node_ids == (
        "symptom-change",
        "change-activity",
        "hypothesis-dependency-latency",
        "hypothesis-resource-saturation",
    )
    target_definition = plan.nodes[0].arguments["definition"]
    assert target_definition["predicates"] == [
        {"property": "name", "operator": "equals", "equals": "A서비스"}
    ]
    assert plan.nodes[1].depends_on == ("resolve-target",)
    assert plan.nodes[1].arguments == {
        "function_name": RESOURCE_ACTIVITY_FUNCTION_NAME,
        "arguments": {"lookback_seconds": 86_400},
        "dependency_arguments": {"resolve-target": "query_result"},
    }
    assert plan.nodes[2].depends_on == ("resolve-target",)
    assert plan.nodes[2].arguments["link_types"] == [
        "service_implemented_by_workload",
        "workload_runs_on_resource",
    ]
    assert plan.nodes[2].arguments["max_depth"] == 2
    assert plan.nodes[-1].depends_on == (
        "cause-resource-saturation",
        "symptom-current",
        "topology-change",
        "symptom-change",
    )
    saturation = next(node for node in plan.nodes if node.node_id == "cause-resource-saturation")
    dependency = next(node for node in plan.nodes if node.node_id == "cause-dependency-latency")
    assert saturation.depends_on == ("resolve-target",)
    assert dependency.depends_on == ("resolve-target",)
    assert plan.execution_authority is False


def test_compiler_requires_entity_type_clarification_before_plan() -> None:
    with pytest.raises(InvestigationClarificationRequiredError, match="entity_type_ambiguous"):
        compile_investigation_plan(
            _verified_intent(target_types=("BusinessService", "Resource")),
            manifest=_manifest(),
            verifier=_verifier(),
            windows=_windows(),
            purpose="operations-review",
        )


def test_compiler_requires_affected_target_clarification_before_plan() -> None:
    with pytest.raises(InvestigationClarificationRequiredError, match="affected_target_ambiguous"):
        compile_investigation_plan(
            _verified_intent(ambiguous_target=True),
            manifest=_manifest(),
            verifier=_verifier(),
            windows=_windows(),
            purpose="operations-review",
        )


def test_server_windows_reject_unequal_duration() -> None:
    with pytest.raises(ValueError, match="equal duration"):
        InvestigationTimeWindows(
            baseline_start=NOW - timedelta(minutes=30),
            baseline_end=NOW - timedelta(minutes=10),
            current_start=NOW - timedelta(minutes=10),
            current_end=NOW,
            known_at=NOW,
        )


def test_semantic_service_compiles_and_projects_full_investigation_receipts() -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"
    verified = _verified_intent()
    investigation = verified.model_dump(
        mode="json",
        exclude={
            "schema_version",
            "input_digest",
            "intent_digest",
            "authority",
            "execution_authority",
        },
    )
    model = _InvestigationModel(
        {
            "operation": "explain_change",
            "subject_constraints": ["BusinessService", "A서비스"],
            "measure_concepts": ["service.latency"],
            "temporal_scope": {"cue": "sudden"},
            "output_shape": "causal_evidence",
            "evidence_requirements": ["support_and_refutation"],
            "unresolved_terms": [],
            "clarification_requirements": [],
            "clarification": None,
            "investigation": investigation,
            "confidence": 0.9,
        }
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(),
        verifier=_verifier(),
        metric_concepts=METRICS,
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
    assert outcome.investigation_intent is not None
    assert outcome.frame is not None
    assert outcome.frame.investigation_intent_digest == outcome.investigation_intent.intent_digest
    assert outcome.plan.problem_frame_digest == outcome.frame.frame_digest
    assert (model.frame_calls, model.plan_calls) == (1, 0)
    assert outcome.intent_graph is not None
    execution = QueryPlanExecution(
        plan_digest=outcome.plan.plan_digest,
        status="completed",
        results={},
        receipts=tuple(
            GoalTaskReceipt(
                task_id=f"query:{node.node_id}",
                goal_id=node.node_id,
                intent=node.kind.value,
                capability=f"query.{node.kind.value}",
                evidence_mode=GoalEvidenceMode.OPERATIONAL,
                status=TaskStatus.COMPLETED,
                duration_ms=1,
                depends_on=node.depends_on,
                evidence_refs=(f"evidence:{node.node_id}",),
                started_at=NOW,
                completed_at=NOW,
            )
            for node in outcome.plan.nodes
        ),
        output_node_ids=outcome.plan.output_node_ids,
    )

    evidence = build_intent_graph_evidence(
        graph=outcome.intent_graph,
        plan=outcome.plan,
        execution=execution,
    )

    assert len(evidence.goals) == len(outcome.plan.nodes) == 13
    assert evidence.execution_authority is False


def test_semantic_service_rejects_omitted_investigation_without_t2() -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"
    frame = {
        "operation": "explain_change",
        "subject_constraints": ["BusinessService", "A서비스"],
        "measure_concepts": ["service.latency"],
        "temporal_scope": {"cue": "sudden"},
        "output_shape": "causal_evidence",
        "evidence_requirements": ["support_and_refutation"],
        "unresolved_terms": [],
        "clarification_requirements": [],
        "clarification": None,
        "investigation": None,
        "confidence": 0.9,
    }
    t1 = _InvestigationModel(frame)
    t2 = _InvestigationModel(frame)
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(),
        verifier=_verifier(),
        metric_concepts=METRICS,
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_plan_invalid"
    assert outcome.investigation_intent is None
    assert outcome.plan is None
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)
