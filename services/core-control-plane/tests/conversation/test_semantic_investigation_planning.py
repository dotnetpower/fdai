"""Deterministic evidence-wave compilation for verified investigations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fdai.core.conversation.intent_graph import build_intent_graph_evidence
from fdai.core.conversation.semantic_investigation import (
    InvestigationIntentProposal,
    normalize_investigation_competitors,
    normalize_investigation_relationships,
    normalize_investigation_symptom,
    normalize_investigation_target,
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
from fdai.rule_catalog.schema.inventory_query_language import (
    load_inventory_query_language_from_mapping,
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
REPO_ROOT = Path(__file__).resolve().parents[4]
INVENTORY_LANGUAGE = load_inventory_query_language_from_mapping(
    yaml.safe_load(
        (REPO_ROOT / "rule-catalog/vocabulary/inventory-query-language.yaml").read_text(
            encoding="utf-8"
        )
    )
)
METRICS = (
    "dependency.latency",
    "request.errors",
    "request.timeout",
    "resource.activation.failure",
    "resource.saturation",
    "service.latency",
)


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
            QueryNodeKind.TYPED_PATH,
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
        QueryNodeKind.TYPED_PATH,
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
    assert plan.nodes[2].arguments["steps"] == [
        {
            "link_type": "service_implemented_by_workload",
            "direction": "outgoing",
            "selector": {"kind": "object_type", "name": "Workload"},
        },
        {
            "link_type": "workload_runs_on_resource",
            "direction": "outgoing",
            "selector": {"kind": "object_type", "name": "Resource"},
        },
    ]
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


def test_exact_outer_frame_repairs_only_the_affected_target_type_and_span() -> None:
    utterance = "service-example-api Container App이 갑자기 느려졌어. 원인을 조사해 줘."
    proposal = _verified_intent().model_dump(
        mode="python",
        exclude={
            "schema_version",
            "input_digest",
            "intent_digest",
            "authority",
            "execution_authority",
        },
    )
    proposal["entities"][0]["span"] = _span(utterance, "Container App")
    proposal["entities"][0]["object_type_candidates"] = ["ContainerApp"]
    proposal["relationship_intents"][0]["query_side_candidates"] = [
        "workload_runs_on_resource.incoming",
        "service_implemented_by_workload.incoming",
    ]
    proposal["symptom_measures"][0]["span"] = _span(utterance, "느려졌어")
    proposal["temporal_cues"][0]["span"] = _span(utterance, "갑자기")
    proposal["relationship_intents"][0]["span"] = _span(utterance, "원인을")
    proposal["hypotheses"][0]["span"] = _span(utterance, "원인을")
    proposal["hypotheses"][1]["span"] = _span(utterance, "조사해")
    investigation = InvestigationIntentProposal.model_validate(proposal)

    repaired = normalize_investigation_target(
        investigation,
        subject_constraints=("Resource", "service-example-api"),
        utterance=utterance,
        descriptors=_manifest().descriptors,
    )

    assert repaired is not None
    target = repaired.entities[0]
    assert target.span.text == "service-example-api"
    assert target.object_type_candidates == ("Resource",)
    assert repaired.symptom_measures == investigation.symptom_measures
    assert repaired.relationship_intents == investigation.relationship_intents
    assert repaired.hypotheses == investigation.hypotheses
    verified = verify_investigation_intent(
        repaired,
        utterance=utterance,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
    )
    assert verified.entities[0].object_type_candidates == ("Resource",)


@pytest.mark.parametrize("candidate_types", ((), ("ContainerApp",)))
def test_relationship_path_repairs_omitted_outer_target_type(
    candidate_types: tuple[str, ...],
) -> None:
    utterance = "service-example-api Container App이 갑자기 느려졌어. 원인을 조사해 줘."
    proposal = _verified_intent().model_dump(
        mode="python",
        exclude={
            "schema_version",
            "input_digest",
            "intent_digest",
            "authority",
            "execution_authority",
        },
    )
    proposal["entities"][0]["span"] = _span(utterance, "Container App")
    proposal["entities"][0]["object_type_candidates"] = list(candidate_types)
    proposal["relationship_intents"][0]["query_side_candidates"] = [
        "workload_runs_on_resource.incoming",
        "service_implemented_by_workload.incoming",
    ]
    proposal["symptom_measures"][0]["span"] = _span(utterance, "느려졌어")
    proposal["temporal_cues"][0]["span"] = _span(utterance, "갑자기")
    proposal["relationship_intents"][0]["span"] = _span(utterance, "원인을")
    proposal["hypotheses"][0]["span"] = _span(utterance, "원인을")
    proposal["hypotheses"][1]["span"] = _span(utterance, "조사해")
    investigation = InvestigationIntentProposal.model_validate(proposal)

    repaired = normalize_investigation_target(
        investigation,
        subject_constraints=("ContainerApp",),
        utterance=utterance,
        descriptors=_manifest().descriptors,
    )

    target = repaired.entities[0]
    assert target.span.text == "service-example-api"
    assert target.object_type_candidates == ("Resource",)
    verify_investigation_intent(
        repaired,
        utterance=utterance,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
    )


def test_exact_resource_causal_frame_replaces_mixed_path_with_unique_service_path() -> None:
    utterance = "service-example-api Container App 요청이 갑자기 시간 초과돼. 원인을 조사해 줘."
    investigation = _verified_intent().model_dump(
        mode="python",
        exclude={
            "schema_version",
            "input_digest",
            "intent_digest",
            "authority",
            "execution_authority",
        },
    )
    investigation["entities"][0]["span"] = _span(utterance, "Container App")
    investigation["entities"][0]["object_type_candidates"] = ["ContainerApp"]
    investigation["symptom_measures"][0]["span"] = _span(utterance, "시간 초과")
    investigation["symptom_measures"][0]["concept_id"] = "request.timeout"
    investigation["temporal_cues"][0]["span"] = _span(utterance, "갑자기")
    investigation["relationship_intents"][0]["span"] = _span(utterance, "원인을")
    investigation["relationship_intents"][0]["query_side_candidates"] = [
        "workload_runs_on_resource.incoming",
        "workload_runs_on_resource.outgoing",
    ]
    investigation["hypotheses"][0]["span"] = _span(utterance, "원인을")
    investigation["hypotheses"][1]["span"] = _span(utterance, "조사해")
    frame = {
        "operation": "explain_change",
        "subject_constraints": ["ContainerApp", "service-example-api"],
        "measure_concepts": ["request.timeout"],
        "temporal_scope": {"cue": "current_failure"},
        "output_shape": "causal_evidence",
        "evidence_requirements": ["support_and_refutation"],
        "unresolved_terms": [],
        "clarification_requirements": [],
        "clarification": None,
        "investigation": investigation,
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
        inventory_query_language=INVENTORY_LANGUAGE,
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.investigation_intent is not None
    assert outcome.investigation_intent.relationship_intents[0].query_side_candidates == (
        "workload_runs_on_resource.incoming",
        "service_implemented_by_workload.incoming",
    )
    assert outcome.plan is not None
    assert len(outcome.plan.nodes) == 13
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_exact_resource_causal_frame_does_not_choose_an_ambiguous_service_path() -> None:
    proposal_data = _verified_intent().model_dump(
        mode="python",
        exclude={
            "schema_version",
            "input_digest",
            "intent_digest",
            "authority",
            "execution_authority",
        },
    )
    proposal_data["entities"][0]["object_type_candidates"] = ["Resource"]
    proposal_data["relationship_intents"][0]["query_side_candidates"] = [
        "workload_runs_on_resource.incoming",
        "workload_runs_on_resource.outgoing",
    ]
    proposal = InvestigationIntentProposal.model_validate(proposal_data)
    descriptors = (
        *_manifest().descriptors,
        {
            "kind": "link",
            "name": "alternate_runs_on_resource",
            "from_type": "AlternateWorkload",
            "to_type": "Resource",
            "query_sides": {
                "source": {
                    "query_id": "alternate_runs_on_resource.outgoing",
                    "direction": "outgoing",
                },
                "target": {
                    "query_id": "alternate_runs_on_resource.incoming",
                    "direction": "incoming",
                },
            },
        },
        {
            "kind": "link",
            "name": "alternate_service_implementation",
            "from_type": "BusinessService",
            "to_type": "AlternateWorkload",
            "query_sides": {
                "source": {
                    "query_id": "alternate_service_implementation.outgoing",
                    "direction": "outgoing",
                },
                "target": {
                    "query_id": "alternate_service_implementation.incoming",
                    "direction": "incoming",
                },
            },
        },
    )

    normalized = normalize_investigation_relationships(
        proposal,
        descriptors=descriptors,
    )

    assert normalized is proposal


def test_relationship_path_does_not_repair_mixed_target_types() -> None:
    utterance = "service-example-api Container App이 갑자기 느려졌어. 원인을 조사해 줘."
    proposal = _verified_intent().model_dump(
        mode="python",
        exclude={
            "schema_version",
            "input_digest",
            "intent_digest",
            "authority",
            "execution_authority",
        },
    )
    proposal["entities"][0]["span"] = _span(utterance, "Container App")
    proposal["entities"][0]["object_type_candidates"] = ["Resource", "ContainerApp"]
    proposal["relationship_intents"][0]["query_side_candidates"] = [
        "workload_runs_on_resource.incoming",
        "service_implemented_by_workload.incoming",
    ]
    proposal["symptom_measures"][0]["span"] = _span(utterance, "느려졌어")
    proposal["temporal_cues"][0]["span"] = _span(utterance, "갑자기")
    proposal["relationship_intents"][0]["span"] = _span(utterance, "원인을")
    proposal["hypotheses"][0]["span"] = _span(utterance, "원인을")
    proposal["hypotheses"][1]["span"] = _span(utterance, "조사해")
    investigation = InvestigationIntentProposal.model_validate(proposal)

    normalized = normalize_investigation_target(
        investigation,
        subject_constraints=("ContainerApp",),
        utterance=utterance,
        descriptors=_manifest().descriptors,
    )

    assert normalized is investigation
    with pytest.raises(
        ValueError,
        match="investigation entity type is absent from the principal manifest",
    ):
        verify_investigation_intent(
            normalized,
            utterance=utterance,
            descriptors=_manifest().descriptors,
            metric_concepts=METRICS,
        )


@pytest.mark.parametrize(
    ("subject_constraints", "candidate_types"),
    (
        pytest.param(
            ("Resource", "service-example-api"),
            ("Resource", "ContainerApp"),
            id="mixed-valid-and-invalid-target-types",
        ),
        pytest.param(
            ("Resource", "BusinessService", "service-example-api"),
            ("ContainerApp",),
            id="ambiguous-outer-types",
        ),
        pytest.param(
            ("Resource", "service-example-api", "service-example-worker"),
            ("ContainerApp",),
            id="multiple-residual-identities",
        ),
    ),
)
def test_exact_outer_frame_does_not_repair_ambiguous_target_evidence(
    subject_constraints: tuple[str, ...],
    candidate_types: tuple[str, ...],
) -> None:
    utterance = (
        "service-example-api와 service-example-worker Container App이 갑자기 느려졌어. "
        "원인을 조사해 줘."
    )
    proposal = _verified_intent().model_dump(
        mode="python",
        exclude={
            "schema_version",
            "input_digest",
            "intent_digest",
            "authority",
            "execution_authority",
        },
    )
    proposal["entities"][0]["span"] = _span(utterance, "Container App")
    proposal["entities"][0]["object_type_candidates"] = list(candidate_types)
    proposal["relationship_intents"][0]["query_side_candidates"] = [
        "workload_runs_on_resource.incoming",
        "service_implemented_by_workload.incoming",
    ]
    proposal["symptom_measures"][0]["span"] = _span(utterance, "느려졌어")
    proposal["temporal_cues"][0]["span"] = _span(utterance, "갑자기")
    proposal["relationship_intents"][0]["span"] = _span(utterance, "원인을")
    proposal["hypotheses"][0]["span"] = _span(utterance, "원인을")
    proposal["hypotheses"][1]["span"] = _span(utterance, "조사해")
    investigation = InvestigationIntentProposal.model_validate(proposal)

    normalized = normalize_investigation_target(
        investigation,
        subject_constraints=subject_constraints,
        utterance=utterance,
        descriptors=_manifest().descriptors,
    )

    assert normalized == investigation
    with pytest.raises(
        ValueError,
        match="investigation entity type is absent from the principal manifest",
    ):
        verify_investigation_intent(
            normalized,
            utterance=utterance,
            descriptors=_manifest().descriptors,
            metric_concepts=METRICS,
        )


def test_wholly_invalid_hypothesis_competitors_are_rebound_to_proposed_ids() -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"
    proposal = _verified_intent().model_dump(
        mode="python",
        exclude={
            "schema_version",
            "input_digest",
            "intent_digest",
            "authority",
            "execution_authority",
        },
    )
    proposal["hypotheses"][0]["competing_explanations"] = ["network-delay"]
    proposal["hypotheses"][1]["competing_explanations"] = ["cpu-pressure"]
    investigation = InvestigationIntentProposal.model_validate(proposal)

    normalized = normalize_investigation_competitors(investigation)

    assert normalized.hypotheses[0].competing_explanations == ("resource-saturation",)
    assert normalized.hypotheses[1].competing_explanations == ("dependency-latency",)
    verified = verify_investigation_intent(
        normalized,
        utterance=utterance,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
    )
    assert len(verified.hypotheses) == 2


def test_mixed_valid_and_invalid_hypothesis_competitors_remain_rejected() -> None:
    utterance = "A서비스가 갑자기 왜 느려졌어?"
    proposal = _verified_intent().model_dump(
        mode="python",
        exclude={
            "schema_version",
            "input_digest",
            "intent_digest",
            "authority",
            "execution_authority",
        },
    )
    proposal["hypotheses"][0]["competing_explanations"] = [
        "resource-saturation",
        "network-delay",
    ]
    investigation = InvestigationIntentProposal.model_validate(proposal)

    normalized = normalize_investigation_competitors(investigation)

    assert normalized is investigation
    with pytest.raises(ValueError, match="investigation hypothesis competitors are invalid"):
        verify_investigation_intent(
            normalized,
            utterance=utterance,
            descriptors=_manifest().descriptors,
            metric_concepts=METRICS,
        )


def test_multiple_reviewed_symptom_signals_do_not_rewrite_one_measure() -> None:
    utterance = "요청 시간 초과와 HTTP 500 오류가 함께 발생했어."
    proposal = _verified_intent().model_dump(
        mode="python",
        exclude={
            "schema_version",
            "input_digest",
            "intent_digest",
            "authority",
            "execution_authority",
        },
    )
    proposal["symptom_measures"][0]["span"] = _span(utterance, "시간 초과")
    proposal["symptom_measures"][0]["concept_id"] = "request.duration"
    investigation = InvestigationIntentProposal.model_validate(proposal)

    normalized = normalize_investigation_symptom(
        investigation,
        utterance=utterance,
        metric_concepts=METRICS,
        inventory_query_language=INVENTORY_LANGUAGE,
    )

    assert normalized is investigation


def test_reviewed_symptom_rebinds_a_downstream_effect_span() -> None:
    utterance = "A서비스가 activation failed 상태에서 갑자기 멈췄어. 원인을 조사해 줘."
    proposal = _verified_intent().model_dump(
        mode="python",
        exclude={
            "schema_version",
            "input_digest",
            "intent_digest",
            "authority",
            "execution_authority",
        },
    )
    proposal["symptom_measures"][0]["span"] = _span(utterance, "멈췄어")
    proposal["symptom_measures"][0]["concept_id"] = "service.availability"
    investigation = InvestigationIntentProposal.model_validate(proposal)

    normalized = normalize_investigation_symptom(
        investigation,
        utterance=utterance,
        metric_concepts=METRICS,
        inventory_query_language=INVENTORY_LANGUAGE,
    )

    assert normalized.symptom_measures[0].concept_id == "resource.activation.failure"
    assert normalized.symptom_measures[0].span.text == "activation failed"
    assert normalized.symptom_measures[0].span.start == utterance.index("activation failed")


@pytest.mark.parametrize("candidate_types", (None, ["ContainerApp"]))
@pytest.mark.parametrize("include_frame_target", (True, False))
@pytest.mark.parametrize("canonical_symptom_candidate", (True, False))
@pytest.mark.parametrize("include_canonical_outer_type", (True, False))
@pytest.mark.parametrize(
    ("utterance", "symptom", "concept_id", "candidate_concept_id"),
    (
        (
            "service-example-api Container App이 activation failed 상태에서 갑자기 멈췄어. "
            "원인을 조사해 줘.",
            "activation failed",
            "resource.activation.failure",
            "container.activation.failure",
        ),
        (
            "service-example-api Container App 요청이 갑자기 시간 초과돼. 원인을 조사해 줘.",
            "시간 초과",
            "request.timeout",
            "container.request.timeout",
        ),
        (
            "service-example-api Container App에서 갑자기 HTTP 500 오류가 발생해. "
            "원인을 조사해 줘.",
            "HTTP 500",
            "request.errors",
            "http.response.500",
        ),
    ),
)
def test_exact_resource_causal_frame_repairs_missing_or_provider_target_type_without_t2(
    candidate_types: list[str] | None,
    include_frame_target: bool,
    canonical_symptom_candidate: bool,
    include_canonical_outer_type: bool,
    utterance: str,
    symptom: str,
    concept_id: str,
    candidate_concept_id: str,
) -> None:
    proposed_concept_id = concept_id if canonical_symptom_candidate else candidate_concept_id
    target_entity: dict[str, object] = {
        "mention_id": "target",
        "span": _span(utterance, "Container App"),
        "role": "affected_target",
    }
    if candidate_types is not None:
        target_entity["object_type_candidates"] = candidate_types
    investigation = {
        "operation": "explain_change",
        "entities": [target_entity],
        "symptom_measures": [
            {
                "measure_id": "symptom",
                "span": _span(utterance, symptom),
                "concept_id": proposed_concept_id,
                "target_mention_id": "target",
                "direction": "increase",
            }
        ],
        "primary_symptom_measure_id": "symptom",
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
                "span": _span(utterance, "원인을"),
                "source_mention_id": "target",
                "target_mention_id": None,
                "query_side_candidates": [
                    "workload_runs_on_resource.incoming",
                    "service_implemented_by_workload.incoming",
                ],
            }
        ],
        "hypotheses": [
            {
                "hypothesis_id": "dependency-latency",
                "span": _span(utterance, "원인을"),
                "relationship_id": "dependencies",
                "cause_measure_concept": "dependency.latency",
                "effect_measure_id": "symptom",
                "competing_explanations": ["resource-saturation"],
            },
            {
                "hypothesis_id": "resource-saturation",
                "span": _span(utterance, "조사해"),
                "relationship_id": "dependencies",
                "cause_measure_concept": "resource.saturation",
                "effect_measure_id": "symptom",
                "competing_explanations": ["dependency-latency"],
            },
        ],
        "evidence_standard": "support_and_refutation",
        "answer_shape": "diagnosis",
        "confidence": 0.9,
    }
    frame = {
        "operation": "explain_change",
        "subject_constraints": [
            *(("Resource",) if include_canonical_outer_type else ("ContainerApp",)),
            *(["service-example-api"] if include_frame_target else []),
        ],
        "measure_concepts": [proposed_concept_id],
        "temporal_scope": {"cue": "current_failure"},
        "output_shape": "causal_evidence",
        "evidence_requirements": ["support_and_refutation"],
        "unresolved_terms": [],
        "clarification_requirements": [],
        "clarification": None,
        "investigation": investigation,
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
        inventory_query_language=INVENTORY_LANGUAGE,
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.investigation_intent is not None
    assert outcome.frame is not None
    assert outcome.frame.measure_concepts == (concept_id,)
    assert outcome.investigation_intent.symptom_measures[0].concept_id == concept_id
    target = next(
        entity
        for entity in outcome.investigation_intent.entities
        if entity.role.value == "affected_target"
    )
    assert target.span.text == "service-example-api"
    assert target.object_type_candidates == ("Resource",)
    assert outcome.plan is not None
    assert len(outcome.plan.nodes) == 13
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)
