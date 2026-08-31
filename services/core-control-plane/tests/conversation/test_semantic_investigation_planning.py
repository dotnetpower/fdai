"""Deterministic evidence-wave compilation for verified investigations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fdai.core.conversation.intent_graph import build_intent_graph_evidence
from fdai.core.conversation.semantic_impact_planning import service_resource_query_sides
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
from fdai.core.conversation.semantic_latency_recovery_planning import (
    LatencyRecoveryWindowPendingError,
    compile_latency_recovery_plan,
)
from fdai.core.conversation.semantic_mysql_pressure_planning import (
    compile_mysql_pressure_plan,
)
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_frame_core import build_semantic_frame
from fdai.core.conversation.semantic_planning_frame_normalization import (
    normalize_bound_latency_recovery,
    normalize_missing_resource_slowness_investigation,
)
from fdai.core.conversation.semantic_planning_models import (
    BoundInvestigationContinuation,
    SemanticFrameProposal,
    SemanticPlanningDisposition,
)
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    METRIC_ARGUMENT_SCHEMAS,
    TOPOLOGY_ARGUMENT_SCHEMAS,
    OntologyQueryPlanVerifier,
    QueryPlanExecution,
    build_query_manifest,
)
from fdai.core.ontology_platform.latency_recovery_evidence import (
    LATENCY_RECOVERY_FUNCTION_NAME,
    latency_recovery_function_type,
)
from fdai.core.ontology_platform.mysql_pressure_evidence import (
    MYSQL_DEMAND_BUNDLE_FUNCTION_NAME,
    MYSQL_PRESSURE_FUNCTION_NAME,
    MYSQL_SATURATION_BUNDLE_FUNCTION_NAME,
    mysql_demand_bundle_function_type,
    mysql_pressure_function_type,
    mysql_saturation_bundle_function_type,
)
from fdai.core.ontology_platform.property_values import (
    PropertyValueDomain,
    PropertyValueGroup,
)
from fdai.core.ontology_platform.resource_activity_queries import (
    RESOURCE_ACTIVITY_FUNCTION_NAME,
    resource_activity_function_type,
)
from fdai.core.ontology_platform.resource_state_queries import (
    RESOURCE_STATE_FUNCTION_NAME,
    resource_state_function_type,
)
from fdai.core.ontology_platform.vm_process_evidence import (
    VM_PROCESS_CPU_FUNCTION_NAME,
    vm_process_cpu_function_type,
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
    "database.mysql.active_connections",
    "database.mysql.cpu.utilization_pct",
    "database.mysql.query.count",
    "database.mysql.slow_query.count",
    "dependency.latency",
    "network.change",
    "request.errors",
    "request.timeout",
    "request.volume",
    "resource.activation.failure",
    "resource.cpu.utilization_pct",
    "resource.saturation",
    "service.latency",
)


def test_exact_resource_slowness_completes_structured_investigation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    utterance = "ca-example-core가 갑자기 왜 느려졌어?"
    proposal = SemanticFrameProposal(
        operation="explain_change",
        subject_constraints=("Resource", "ca-example-core"),
        measure_concepts=(),
        temporal_scope={},
        output_shape="causal_evidence",
        evidence_requirements=("support_and_refutation",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=0.91,
    )

    with caplog.at_level(logging.INFO):
        normalized = normalize_missing_resource_slowness_investigation(
            proposal,
            utterance=utterance,
            descriptors=_manifest().descriptors,
            metric_concepts=METRICS,
            inventory_query_language=INVENTORY_LANGUAGE,
            semantic_judgment={
                "requested_facets": ("cause",),
                "action_posture": "advise_only",
                "execution_authority": False,
            },
        )

    assert normalized.investigation is not None
    assert normalized.investigation.entities[0].span.text == "ca-example-core"
    assert normalized.investigation.symptom_measures[0].span.text == "느려졌어"
    assert normalized.investigation.temporal_cues[0].span.text == "갑자기"
    assert tuple(item.hypothesis_id for item in normalized.investigation.hypotheses) == (
        "dependency-latency",
        "traffic-load",
    )
    verified = verify_investigation_intent(
        normalized.investigation,
        utterance=utterance,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
    )
    plan = compile_investigation_plan(
        verified,
        manifest=_manifest(),
        verifier=_verifier(),
        windows=InvestigationTimeWindows(
            baseline_start=NOW - timedelta(minutes=30),
            baseline_end=NOW - timedelta(minutes=15),
            current_start=NOW - timedelta(minutes=15),
            current_end=NOW,
            known_at=NOW,
        ),
        purpose="operations-review",
    )
    assert plan.execution_authority is False
    assert {"hypothesis-dependency-latency", "hypothesis-traffic-load"} <= {
        node.node_id for node in plan.nodes
    }
    dependency = next(node for node in plan.nodes if node.node_id == "cause-dependency-latency")
    traffic = next(node for node in plan.nodes if node.node_id == "cause-traffic-load")
    assert dependency.depends_on == ("expand-dependencies",)
    assert traffic.depends_on == ("expand-dependencies",)
    diagnostic = next(
        record
        for record in caplog.records
        if record.message == "semantic_planning_resource_slowness_recovery_evaluated"
    )
    assert diagnostic.failed_preconditions == "none"
    assert diagnostic.failed_precondition_count == 0


def test_exact_resource_latency_decrease_is_not_normalized_as_slowness() -> None:
    utterance = "Why did ca-example-core latency suddenly decrease?"
    proposal = SemanticFrameProposal(
        operation="explain_change",
        subject_constraints=("Resource", "ca-example-core"),
        measure_concepts=(),
        temporal_scope={},
        output_shape="causal_evidence",
        evidence_requirements=("support_and_refutation",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=0.91,
    )

    normalized = normalize_missing_resource_slowness_investigation(
        proposal,
        utterance=utterance,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
        inventory_query_language=INVENTORY_LANGUAGE,
        semantic_judgment={
            "requested_facets": ("cause",),
            "action_posture": "advise_only",
            "execution_authority": False,
        },
    )

    assert normalized is proposal


def test_resource_slowness_diagnostic_reports_missing_cause(
    caplog: pytest.LogCaptureFixture,
) -> None:
    utterance = "ca-example-core가 갑자기 느려졌어?"
    proposal = SemanticFrameProposal(
        operation="explain_change",
        subject_constraints=("Resource", "ca-example-core"),
        measure_concepts=(),
        temporal_scope={},
        output_shape="causal_evidence",
        evidence_requirements=("support_and_refutation",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=0.91,
    )

    with caplog.at_level(logging.INFO):
        normalized = normalize_missing_resource_slowness_investigation(
            proposal,
            utterance=utterance,
            descriptors=_manifest().descriptors,
            metric_concepts=METRICS,
            inventory_query_language=INVENTORY_LANGUAGE,
            semantic_judgment={
                "requested_facets": (),
                "action_posture": "advise_only",
                "execution_authority": False,
            },
        )

    assert normalized is proposal
    diagnostic = next(
        record
        for record in caplog.records
        if record.message == "semantic_planning_resource_slowness_recovery_evaluated"
    )
    assert "cause_facet_present" in diagnostic.failed_preconditions.split(",")


def test_resource_slowness_recovers_missing_outer_type_from_verified_target() -> None:
    utterance = "ca-example-core가 갑자기 왜 느려졌어?"
    proposal = SemanticFrameProposal(
        operation="explain_change",
        subject_constraints=("ca-example-core",),
        measure_concepts=(),
        temporal_scope={},
        output_shape="causal_evidence",
        evidence_requirements=("support_and_refutation",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=0.91,
    )

    normalized = normalize_missing_resource_slowness_investigation(
        proposal,
        utterance=utterance,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
        inventory_query_language=INVENTORY_LANGUAGE,
        semantic_judgment={
            "targets": (
                {
                    "kind": "resource",
                    "value": "ca-example-core",
                    "canonical_value": None,
                },
            ),
            "requested_facets": ("cause",),
            "action_posture": "advise_only",
            "execution_authority": False,
        },
    )

    assert normalized.subject_constraints == ("Resource", "ca-example-core")
    assert normalized.investigation is not None
    verified = verify_investigation_intent(
        normalized.investigation,
        utterance=utterance,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
    )
    assert verified.entities[0].object_type_candidates == ("Resource",)


def test_resource_slowness_does_not_infer_type_from_untyped_target() -> None:
    utterance = "ca-example-core가 갑자기 왜 느려졌어?"
    proposal = SemanticFrameProposal(
        operation="explain_change",
        subject_constraints=("ca-example-core",),
        measure_concepts=(),
        temporal_scope={},
        output_shape="causal_evidence",
        evidence_requirements=("support_and_refutation",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=0.91,
    )

    normalized = normalize_missing_resource_slowness_investigation(
        proposal,
        utterance=utterance,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
        inventory_query_language=INVENTORY_LANGUAGE,
        semantic_judgment={
            "targets": (
                {
                    "kind": "localized_label",
                    "value": "ca-example-core",
                    "canonical_value": None,
                },
            ),
            "requested_facets": ("cause",),
            "action_posture": "advise_only",
            "execution_authority": False,
        },
    )

    assert normalized is proposal


@pytest.mark.parametrize(
    ("utterance", "subject_constraints"),
    (
        (
            "Why did ca-example-core not suddenly become slower?",
            ("Resource", "ca-example-core"),
        ),
        (
            "ca-example-core가 갑자기 왜 느려졌어?",
            ("Resource", "BusinessService", "ca-example-core"),
        ),
        (
            "Why isn't ca-example-core suddenly slower?",
            ("Resource", "ca-example-core"),
        ),
        (
            "Why did prod-slower-app suddenly restart?",
            ("Resource", "prod-slower-app"),
        ),
        (
            "Why hasn't ca-example-core suddenly become slower?",
            ("Resource", "ca-example-core"),
        ),
        (
            "ca-example-core가 갑자기 왜 안 느려졌어?",
            ("Resource", "ca-example-core"),
        ),
        (
            "Why was ca-example-core restarted after it suddenly became slower?",
            ("Resource", "ca-example-core"),
        ),
        (
            "Why couldn't ca-example-core suddenly become slower?",
            ("Resource", "ca-example-core"),
        ),
        (
            "Why did ca-example-core suddenly become slower because of network latency?",
            ("Resource", "ca-example-core"),
        ),
    ),
)
def test_resource_slowness_recovery_rejects_unsafe_contexts(
    utterance: str,
    subject_constraints: tuple[str, ...],
) -> None:
    proposal = SemanticFrameProposal(
        operation="explain_change",
        subject_constraints=subject_constraints,
        measure_concepts=(),
        temporal_scope={},
        output_shape="causal_evidence",
        evidence_requirements=("support_and_refutation",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=0.91,
    )

    normalized = normalize_missing_resource_slowness_investigation(
        proposal,
        utterance=utterance,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
        inventory_query_language=INVENTORY_LANGUAGE,
        semantic_judgment={
            "requested_facets": ("cause",),
            "action_posture": "advise_only",
            "execution_authority": False,
        },
    )

    assert normalized is proposal


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


def test_service_resource_query_sides_requires_unique_reverse_sides() -> None:
    descriptors = _manifest().descriptors

    assert service_resource_query_sides(descriptors) == (
        "service_implemented_by_workload.outgoing",
        "workload_runs_on_resource.outgoing",
    )

    missing = tuple(
        descriptor
        if descriptor.get("name") != "workload_runs_on_resource"
        else {
            **descriptor,
            "query_sides": {
                key: value
                for key, value in descriptor["query_sides"].items()
                if value.get("direction") != "outgoing"
            },
        }
        for descriptor in descriptors
    )
    assert service_resource_query_sides(missing) is None

    ambiguous = tuple(
        descriptor
        if descriptor.get("name") != "workload_runs_on_resource"
        else {
            **descriptor,
            "query_sides": {
                **descriptor["query_sides"],
                "duplicate": {
                    **next(
                        value
                        for value in descriptor["query_sides"].values()
                        if value.get("direction") == "outgoing"
                    ),
                    "query_id": "workload_runs_on_resource.duplicate",
                },
            },
        }
        for descriptor in descriptors
    )
    assert service_resource_query_sides(ambiguous) is None


def _manifest(*, bind_process_evidence: bool = True):  # type: ignore[no-untyped-def]
    activity_function = resource_activity_function_type()
    mysql_demand_function = mysql_demand_bundle_function_type()
    mysql_pressure_function = mysql_pressure_function_type()
    mysql_saturation_function = mysql_saturation_bundle_function_type()
    latency_recovery_function = latency_recovery_function_type()
    process_function = vm_process_cpu_function_type()
    resource_state_function = resource_state_function_type()
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
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "name": PropertyDecl(type=PropertyType.STRING, required=True),
            "type": PropertyDecl(type=PropertyType.STRING, required=True),
        },
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
        function_types=(
            activity_function,
            mysql_demand_function,
            mysql_pressure_function,
            mysql_saturation_function,
            latency_recovery_function,
            process_function,
            resource_state_function,
        ),
    )
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(service, workload, resource),
        link_types=(implementation, placement),
        functions=(
            activity_function,
            mysql_demand_function,
            mysql_pressure_function,
            mysql_saturation_function,
            latency_recovery_function,
            process_function,
            resource_state_function,
        ),
        property_values=(
            PropertyValueDomain(
                object_type="Resource",
                property_name="type",
                values=("compute.vm", "mysql-server"),
                groups=(
                    PropertyValueGroup(
                        id="mysql-server",
                        values=("mysql-server",),
                        terms=("mysql", "mysql database", "mysql server"),
                    ),
                ),
            ),
        ),
        bound_function_names=(
            (
                MYSQL_PRESSURE_FUNCTION_NAME,
                MYSQL_DEMAND_BUNDLE_FUNCTION_NAME,
                MYSQL_SATURATION_BUNDLE_FUNCTION_NAME,
                LATENCY_RECOVERY_FUNCTION_NAME,
                RESOURCE_ACTIVITY_FUNCTION_NAME,
                RESOURCE_STATE_FUNCTION_NAME,
                VM_PROCESS_CPU_FUNCTION_NAME,
            )
            if bind_process_evidence
            else (
                MYSQL_DEMAND_BUNDLE_FUNCTION_NAME,
                MYSQL_PRESSURE_FUNCTION_NAME,
                MYSQL_SATURATION_BUNDLE_FUNCTION_NAME,
                LATENCY_RECOVERY_FUNCTION_NAME,
                RESOURCE_ACTIVITY_FUNCTION_NAME,
                RESOURCE_STATE_FUNCTION_NAME,
            )
        ),
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
        QueryNodeKind.TYPED_PATH,
        QueryNodeKind.FUNCTION,
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
        "service-resource-state",
        "hypothesis-dependency-latency",
        "hypothesis-resource-saturation",
    )
    target_definition = plan.nodes[0].arguments["definition"]
    assert target_definition["predicates"] == [
        {"property": "name", "operator": "equals", "equals": "A서비스"}
    ]
    assert plan.nodes[1].depends_on == ("resolve-target",)
    assert plan.nodes[1].arguments["steps"] == [
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
    assert plan.nodes[2].depends_on == ("expand-dependencies",)
    assert plan.nodes[2].arguments["function_name"] == RESOURCE_STATE_FUNCTION_NAME
    assert plan.nodes[-1].depends_on == (
        "cause-resource-saturation",
        "symptom-current",
        "topology-change",
        "symptom-change",
    )
    saturation = next(node for node in plan.nodes if node.node_id == "cause-resource-saturation")
    dependency = next(node for node in plan.nodes if node.node_id == "cause-dependency-latency")
    assert saturation.depends_on == ("expand-dependencies",)
    assert dependency.depends_on == ("expand-dependencies",)
    assert plan.execution_authority is False


def _verified_vm_cpu_intent():  # type: ignore[no-untyped-def]
    utterance = "vm-example VM의 CPU 급증 원인과 영향을 받는 서비스를 조사해줘."
    proposal = InvestigationIntentProposal.model_validate(
        {
            "operation": "explain_change",
            "entities": [
                {
                    "mention_id": "target",
                    "span": _span(utterance, "vm-example"),
                    "role": "affected_target",
                    "object_type_candidates": ["Resource"],
                }
            ],
            "symptom_measures": [
                {
                    "measure_id": "cpu-spike",
                    "span": _span(utterance, "CPU 급증"),
                    "concept_id": "resource.cpu.utilization_pct",
                    "target_mention_id": "target",
                    "direction": "increase",
                }
            ],
            "primary_symptom_measure_id": "cpu-spike",
            "temporal_cues": [
                {
                    "cue_id": "onset",
                    "span": _span(utterance, "급증"),
                    "role": "onset",
                }
            ],
            "relationship_intents": [
                {
                    "relationship_id": "service-impact",
                    "span": _span(utterance, "영향을 받는 서비스"),
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
                    "hypothesis_id": "traffic-load",
                    "span": _span(utterance, "원인"),
                    "relationship_id": "service-impact",
                    "cause_measure_concept": "request.volume",
                    "effect_measure_id": "cpu-spike",
                    "competing_explanations": ["dependency-latency"],
                },
                {
                    "hypothesis_id": "dependency-latency",
                    "span": _span(utterance, "원인"),
                    "relationship_id": "service-impact",
                    "cause_measure_concept": "dependency.latency",
                    "effect_measure_id": "cpu-spike",
                    "competing_explanations": ["traffic-load"],
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


def test_vm_cpu_spike_compiles_exact_percent_windows_and_service_impact_path() -> None:
    intent = _verified_vm_cpu_intent()

    plan = compile_investigation_plan(
        intent,
        manifest=_manifest(),
        verifier=_verifier(),
        windows=_windows(),
        purpose="operations-review",
    )

    baseline = next(node for node in plan.nodes if node.node_id == "symptom-baseline")
    current = next(node for node in plan.nodes if node.node_id == "symptom-current")
    impact = next(node for node in plan.nodes if node.node_id == "expand-service-impact")
    assert baseline.arguments["concept_id"] == "resource.cpu.utilization_pct"
    assert current.arguments["concept_id"] == "resource.cpu.utilization_pct"
    assert impact.arguments["steps"] == [
        {
            "link_type": "workload_runs_on_resource",
            "direction": "incoming",
            "selector": {"kind": "object_type", "name": "Workload"},
        },
        {
            "link_type": "service_implemented_by_workload",
            "direction": "incoming",
            "selector": {"kind": "object_type", "name": "BusinessService"},
        },
    ]
    process = next(node for node in plan.nodes if node.node_id == "vm-process-evidence")
    assert process.depends_on == ("resolve-target",)
    assert process.arguments == {
        "function_name": VM_PROCESS_CPU_FUNCTION_NAME,
        "arguments": {
            "start": _windows().current_start.isoformat(),
            "end": _windows().current_end.isoformat(),
            "limit": 8,
        },
        "dependency_arguments": {"resolve-target": "query_result"},
    }
    assert "vm-process-evidence" in plan.output_node_ids
    assert len(plan.nodes) == 14
    assert plan.execution_authority is False


def test_vm_cpu_spike_stops_when_process_evidence_is_unbound() -> None:
    intent = _verified_vm_cpu_intent()

    with pytest.raises(ValueError, match="declaration is absent"):
        compile_investigation_plan(
            intent,
            manifest=_manifest(bind_process_evidence=False),
            verifier=_verifier(),
            windows=_windows(),
            purpose="operations-review",
        )


def test_mysql_pressure_compiles_aligned_metrics_activity_and_service_impact() -> None:
    utterance = (
        "mysql-example-target MySQL의 DB 지연이 MySQL 포화인지 요청량 증가인지 "
        "반증 근거까지 포함해 판단해줘."
    )
    proposal = InvestigationIntentProposal.model_validate(
        {
            "operation": "explain_change",
            "entities": [
                {
                    "mention_id": "target",
                    "span": _span(utterance, "mysql-example-target"),
                    "role": "affected_target",
                    "object_type_candidates": ["Resource"],
                }
            ],
            "symptom_measures": [
                {
                    "measure_id": "database-latency",
                    "span": _span(utterance, "DB 지연"),
                    "concept_id": "dependency.latency",
                    "target_mention_id": "target",
                    "direction": "increase",
                }
            ],
            "primary_symptom_measure_id": "database-latency",
            "temporal_cues": [
                {
                    "cue_id": "onset",
                    "span": _span(utterance, "DB 지연"),
                    "role": "onset",
                }
            ],
            "relationship_intents": [
                {
                    "relationship_id": "service-impact",
                    "span": _span(utterance, "요청량 증가"),
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
                    "hypothesis_id": "mysql-saturation",
                    "span": _span(utterance, "MySQL 포화"),
                    "relationship_id": "service-impact",
                    "cause_measure_concept": "database.mysql.cpu.utilization_pct",
                    "effect_measure_id": "database-latency",
                    "competing_explanations": ["request-growth"],
                },
                {
                    "hypothesis_id": "request-growth",
                    "span": _span(utterance, "요청량 증가"),
                    "relationship_id": "service-impact",
                    "cause_measure_concept": "database.mysql.query.count",
                    "effect_measure_id": "database-latency",
                    "competing_explanations": ["mysql-saturation"],
                },
            ],
            "evidence_standard": "support_and_refutation",
            "answer_shape": "diagnosis",
            "confidence": 0.9,
        }
    )
    intent = verify_investigation_intent(
        proposal,
        utterance=utterance,
        descriptors=_manifest().descriptors,
        metric_concepts=METRICS,
    )

    plan = compile_mysql_pressure_plan(
        investigation_intent=intent,
        manifest=_manifest(),
        verifier=_verifier(),
        windows=_windows(),
        purpose="operations-review",
        problem_frame_digest=intent.intent_digest,
        available_metric_concepts=METRICS,
    )

    assert plan is not None
    assert len(plan.nodes) == 16
    metric_nodes = tuple(
        node for node in plan.nodes if node.kind is QueryNodeKind.METRIC_SCOPE_SERIES
    )
    assert len(metric_nodes) == 10
    assert all(
        node.depends_on == ("impact-services",)
        for node in metric_nodes
        if node.arguments["concept_id"] == "dependency.latency"
    )
    assert all(
        node.depends_on == ("mysql-target",)
        for node in metric_nodes
        if node.arguments["concept_id"] != "dependency.latency"
    )
    reducer = next(node for node in plan.nodes if node.node_id == "mysql-pressure-evidence")
    assert reducer.arguments["function_name"] == MYSQL_PRESSURE_FUNCTION_NAME
    assert reducer.arguments["arguments"] == {}
    assert reducer.depends_on == (
        "mysql-demand-metric-bundle",
        "mysql-saturation-metric-bundle",
    )
    assert len(reducer.arguments["dependency_arguments"]) == 2
    demand = next(node for node in plan.nodes if node.node_id == "mysql-demand-metric-bundle")
    saturation = next(
        node for node in plan.nodes if node.node_id == "mysql-saturation-metric-bundle"
    )
    assert len(demand.depends_on) == 4
    assert len(saturation.depends_on) == 6
    assert plan.output_node_ids == (
        "mysql-pressure-evidence",
        "change-activity",
        "impact-services",
    )
    assert plan.execution_authority is False


def test_exact_mysql_pressure_frame_recovers_omitted_investigation_without_t2() -> None:
    utterance = (
        "mysql-example-target MySQL의 DB 지연이 MySQL 포화인지 요청량 증가인지 "
        "반증 근거까지 포함해 판단해줘."
    )
    frame = {
        "operation": "explain_change",
        "subject_constraints": ["MySQL", "mysql-example-target"],
        "measure_concepts": ["dependency.latency"],
        "temporal_scope": {"kind": "current"},
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
        inventory_query_language=INVENTORY_LANGUAGE,
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED, outcome.reason
    assert outcome.investigation_intent is not None
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("Resource", "mysql-example-target")
    assert outcome.plan is not None
    assert len(outcome.plan.nodes) == 16
    assert outcome.plan.output_node_ids == (
        "mysql-pressure-evidence",
        "change-activity",
        "impact-services",
    )
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_targetless_mysql_pressure_returns_candidates_before_generic_causal_plan() -> None:
    utterance = "DB 지연이 MySQL 포화인지 요청량 증가인지 반증 근거까지 포함해 판단해줘."
    frame = {
        "operation": "explain_change",
        "subject_constraints": ["Resource", "mysql-server"],
        "measure_concepts": ["dependency.latency"],
        "temporal_scope": {"kind": "current"},
        "output_shape": "causal_evidence",
        "evidence_requirements": ["support_and_refutation"],
        "unresolved_terms": [],
        "clarification_requirements": [],
        "clarification": None,
        "investigation": None,
        "confidence": 0.9,
    }
    model = _InvestigationModel(frame)
    service = SemanticPlanningService(
        model=model,
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

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED, outcome.reason
    assert outcome.frame is not None
    assert outcome.frame.output_shape == "resource_target_candidates"
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].arguments["definition"]["predicates"] == [
        {"property": "type", "operator": "equals", "equals": "mysql-server"}
    ]
    assert model.plan_calls == 0
    assert outcome.execution_authority is False


def test_targetless_network_application_latency_requires_exact_service() -> None:
    utterance = "지난 10분간 응답 지연이 네트워크 때문인지 애플리케이션 때문인지 비교해줘."
    frame = {
        "operation": "explain_change",
        "subject_constraints": [],
        "measure_concepts": ["service.latency"],
        "temporal_scope": {"kind": "windowed"},
        "output_shape": "causal_evidence",
        "evidence_requirements": ["support_and_refutation"],
        "unresolved_terms": [],
        "clarification_requirements": [],
        "clarification": None,
        "investigation": None,
        "confidence": 0.9,
    }
    model = _InvestigationModel(frame)
    service = SemanticPlanningService(
        model=model,
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

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.clarification == "응답 지연을 조사할 정확한 서비스 이름 또는 ID를 알려주세요?"
    assert outcome.plan is None
    assert model.plan_calls == 0


def test_exact_network_application_latency_compiles_server_investigation_without_t2() -> None:
    utterance = (
        "service-example-api 서비스의 지난 10분간 응답 지연이 네트워크 때문인지 "
        "애플리케이션 때문인지 비교해줘."
    )
    frame = {
        "operation": "explain_change",
        "subject_constraints": ["Service", "service-example-api"],
        "measure_concepts": ["service.latency"],
        "temporal_scope": {"kind": "windowed"},
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
    assert outcome.frame is not None
    assert outcome.frame.subject_constraints == ("BusinessService", "service-example-api")
    assert outcome.investigation_intent is not None
    assert outcome.plan is not None
    assert len(outcome.plan.nodes) == 13
    assert "change-activity" not in {node.node_id for node in outcome.plan.nodes}
    traversal = next(
        node for node in outcome.plan.nodes if node.node_id == "expand-service-resources"
    )
    assert traversal.arguments["steps"] == [
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
    for node_id in ("cause-network-latency", "cause-application-latency"):
        node = next(node for node in outcome.plan.nodes if node.node_id == node_id)
        assert node.depends_on == ("expand-service-resources",)
    state = next(node for node in outcome.plan.nodes if node.node_id == "service-resource-state")
    assert state.depends_on == ("expand-service-resources",)
    assert state.node_id in outcome.plan.output_node_ids
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize(
    ("operation", "output_shape"),
    (("compare", "temporal_comparison"), ("validate", "evidence_validation")),
)
def test_exact_network_application_latency_recovers_read_only_frame_variants(
    operation: str,
    output_shape: str,
) -> None:
    utterance = (
        "core-control-plane 서비스의 지난 10분간 응답 지연이 네트워크 때문인지 "
        "애플리케이션 때문인지 비교해줘."
    )
    frame = {
        "operation": operation,
        "subject_constraints": ["BusinessService", "core-control-plane"],
        "measure_concepts": ["service.latency"],
        "temporal_scope": {"kind": "windowed"},
        "output_shape": output_shape,
        "evidence_requirements": [],
        "unresolved_terms": [],
        "clarification_requirements": [],
        "clarification": None,
        "investigation": None,
        "confidence": 0.9,
    }
    model = _InvestigationModel(frame)
    service = SemanticPlanningService(
        model=model,
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

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED, outcome.reason
    assert outcome.frame is not None
    assert outcome.frame.operation.value == "explain_change"
    assert outcome.frame.output_shape == "causal_evidence"
    assert outcome.investigation_intent is not None
    assert outcome.plan is not None
    assert len(outcome.plan.nodes) == 13
    assert model.plan_calls == 0


def test_exact_network_application_latency_replaces_noncanonical_inner_target() -> None:
    utterance = (
        "core-control-plane 서비스의 지난 10분간 응답 지연이 네트워크 때문인지 "
        "애플리케이션 때문인지 비교해줘."
    )
    frame = {
        "operation": "explain_change",
        "subject_constraints": ["Service", "core-control-plane"],
        "measure_concepts": ["service.latency"],
        "temporal_scope": {"kind": "windowed"},
        "output_shape": "causal_evidence",
        "evidence_requirements": ["support_and_refutation"],
        "unresolved_terms": [],
        "clarification_requirements": [],
        "clarification": None,
        "investigation": {
            "operation": "explain_change",
            "entities": [
                {
                    "mention_id": "target",
                    "span": _span(utterance, "core-control-plane"),
                    "role": "affected_target",
                    "object_type_candidates": ["Service"],
                }
            ],
            "symptom_measures": [
                {
                    "measure_id": "latency",
                    "span": _span(utterance, "응답 지연"),
                    "concept_id": "service.latency",
                    "target_mention_id": "target",
                    "direction": "increase",
                }
            ],
            "primary_symptom_measure_id": "latency",
            "temporal_cues": [
                {
                    "cue_id": "onset",
                    "span": _span(utterance, "응답 지연"),
                    "role": "onset",
                }
            ],
            "relationship_intents": [
                {
                    "relationship_id": "resources",
                    "span": _span(utterance, "애플리케이션 때문인지"),
                    "source_mention_id": "target",
                    "query_side_candidates": ["service_implemented_by_workload.outgoing"],
                }
            ],
            "hypotheses": [
                {
                    "hypothesis_id": "network",
                    "span": _span(utterance, "네트워크 때문인지"),
                    "relationship_id": "resources",
                    "cause_measure_concept": "network.change",
                    "effect_measure_id": "latency",
                    "competing_explanations": ["application"],
                },
                {
                    "hypothesis_id": "application",
                    "span": _span(utterance, "애플리케이션 때문인지"),
                    "relationship_id": "resources",
                    "cause_measure_concept": "dependency.latency",
                    "effect_measure_id": "latency",
                    "competing_explanations": ["network"],
                },
            ],
            "evidence_standard": "support_and_refutation",
            "answer_shape": "diagnosis",
            "confidence": 0.8,
        },
        "confidence": 0.8,
    }
    model = _InvestigationModel(frame)
    service = SemanticPlanningService(
        model=model,
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

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED, outcome.reason
    assert outcome.investigation_intent is not None
    target = next(
        entity
        for entity in outcome.investigation_intent.entities
        if entity.role.value == "affected_target"
    )
    assert target.object_type_candidates == ("BusinessService",)
    assert outcome.plan is not None
    assert outcome.plan.execution_authority is False
    assert model.plan_calls == 0


def _latency_recovery_continuation() -> BoundInvestigationContinuation:
    return BoundInvestigationContinuation(
        source_session_id="session-1",
        source_turn_id="turn-1",
        source_turn_sequence=1,
        target_type="BusinessService",
        target_value="service-example-api",
        recovery_measure_concepts=("dependency.latency", "service.latency"),
        baseline_start=NOW - timedelta(minutes=40),
        baseline_end=NOW - timedelta(minutes=30),
        initial_observation_cutoff=NOW - timedelta(minutes=20),
        ontology_release_digest=_manifest().release_digest,
        principal_manifest_digest=_manifest().manifest_digest,
        source_frame_digest=f"sha256:{'f' * 64}",
        source_plan_digest=f"sha256:{'e' * 64}",
        source_execution_receipt_digest=f"sha256:{'d' * 64}",
    )


def test_bound_latency_recovery_compiles_original_baseline_and_later_window() -> None:
    continuation = _latency_recovery_continuation()
    proposal = SemanticFrameProposal.model_validate(
        {
            "operation": "validate",
            "subject_constraints": ["Resource"],
            "measure_concepts": [],
            "temporal_scope": {"kind": "current"},
            "output_shape": "target_health_assessment",
            "evidence_requirements": [],
            "unresolved_terms": ["target"],
            "clarification_requirements": ["resource_identity"],
            "clarification": "Which target?",
            "investigation": None,
            "confidence": 0.8,
        }
    )

    normalized = normalize_bound_latency_recovery(
        proposal,
        continuation=continuation,
        semantic_judgment={"requested_facets": ["health", "recovery", "dependency"]},
    )
    frame = build_semantic_frame(
        normalized,
        utterance="Verify recovery.",
        context=(),
    )
    plan = compile_latency_recovery_plan(
        frame=frame,
        continuation=continuation,
        manifest=_manifest(),
        verifier=_verifier(),
        evaluation_time=NOW,
        purpose="operations-review",
        available_metric_concepts=METRICS,
    )

    assert normalized.subject_constraints == ("BusinessService", "service-example-api")
    assert normalized.unresolved_terms == ()
    assert plan is not None
    assert len(plan.nodes) == 9
    assert plan.output_node_ids == ("latency-recovery-evidence",)
    baseline = next(node for node in plan.nodes if node.node_id == "service-latency-baseline")
    current = next(node for node in plan.nodes if node.node_id == "service-latency-current")
    assert baseline.arguments["start"] == (NOW - timedelta(minutes=40)).isoformat()
    assert baseline.arguments["end"] == (NOW - timedelta(minutes=30)).isoformat()
    assert current.arguments["start"] == (NOW - timedelta(minutes=10)).isoformat()
    assert current.arguments["end"] == NOW.isoformat()
    reducer = next(node for node in plan.nodes if node.node_id == "latency-recovery-evidence")
    assert reducer.depends_on == (
        "service-latency-recovery",
        "dependency-latency-recovery",
    )
    assert plan.execution_authority is False


def test_bound_latency_recovery_waits_for_non_overlapping_window() -> None:
    continuation = _latency_recovery_continuation()
    proposal = SemanticFrameProposal.model_validate(
        {
            "operation": "validate",
            "subject_constraints": ["BusinessService", "service-example-api"],
            "measure_concepts": ["dependency.latency", "service.latency"],
            "temporal_scope": {"kind": "windowed"},
            "output_shape": "evidence_validation",
            "evidence_requirements": ["recovery_verification"],
            "unresolved_terms": [],
            "clarification_requirements": [],
            "clarification": None,
            "investigation": None,
            "confidence": 0.8,
        }
    )
    frame = build_semantic_frame(proposal, utterance="Verify recovery.", context=())

    with pytest.raises(LatencyRecoveryWindowPendingError):
        compile_latency_recovery_plan(
            frame=frame,
            continuation=continuation,
            manifest=_manifest(),
            verifier=_verifier(),
            evaluation_time=NOW - timedelta(minutes=15),
            purpose="operations-review",
            available_metric_concepts=METRICS,
        )


def test_exact_vm_cpu_frame_recovers_omitted_structured_investigation_without_t2() -> None:
    utterance = "vm-example-target VM의 CPU 급증 원인과 영향을 받는 서비스를 조사해줘."
    frame = {
        "operation": "explain_change",
        "subject_constraints": ["Resource", "vm-example-target"],
        "measure_concepts": ["resource.cpu.utilization_pct"],
        "temporal_scope": {"kind": "current"},
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
    assert outcome.investigation_intent.symptom_measures[0].concept_id == (
        "resource.cpu.utilization_pct"
    )
    assert outcome.plan is not None
    assert len(outcome.plan.nodes) == 14
    assert "vm-process-evidence" in outcome.plan.output_node_ids
    assert outcome.plan.execution_authority is False
    assert (t1.frame_calls, t1.plan_calls) == (1, 0)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_exact_vm_cpu_frame_without_service_impact_stays_unsupported() -> None:
    utterance = "vm-example-target VM의 CPU 급증 원인을 조사해줘."
    frame = {
        "operation": "explain_change",
        "subject_constraints": ["Resource", "vm-example-target"],
        "measure_concepts": ["resource.cpu.utilization_pct"],
        "temporal_scope": {"kind": "current"},
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
        inventory_query_language=INVENTORY_LANGUAGE,
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


@pytest.mark.parametrize(
    ("utterance", "symptom"),
    (
        ("vm-example VM의 CPU 급증 원인을 조사해줘.", "CPU 급증"),
        ("Investigate the cause of the CPU spike on vm-example.", "CPU spike"),
    ),
)
def test_reviewed_cpu_spike_rebinds_vm_symptom(utterance: str, symptom: str) -> None:
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
    proposal["symptom_measures"][0]["span"] = _span(
        utterance,
        "원인" if "원인" in utterance else "cause",
    )
    proposal["symptom_measures"][0]["concept_id"] = "resource.saturation"
    investigation = InvestigationIntentProposal.model_validate(proposal)

    normalized = normalize_investigation_symptom(
        investigation,
        utterance=utterance,
        metric_concepts=METRICS,
        inventory_query_language=INVENTORY_LANGUAGE,
    )

    assert normalized.symptom_measures[0].concept_id == "resource.cpu.utilization_pct"
    assert normalized.symptom_measures[0].span.text == symptom


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
