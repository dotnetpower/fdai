"""T1-first semantic planning and bounded T2 escalation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fdai.composition.semantic_query_model_targets import t1_model_targets, t2_model_targets
from fdai.core.conversation.semantic_activity_planning import normalize_activity_proposal
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import (
    BoundIncident,
    SemanticFrameProposal,
    SemanticPlanningDisposition,
)
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    METRIC_ARGUMENT_SCHEMAS,
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanExecutor,
    OntologyQueryPlanVerifier,
    build_query_manifest,
)
from fdai.core.ontology_platform.evidence_health_queries import (
    ontology_evidence_health_function_type,
)
from fdai.core.ontology_platform.incident_queries import (
    INCIDENT_EVIDENCE_MAX_RECORDS,
    incident_evidence_function_type,
)
from fdai.core.ontology_platform.inventory_impact_queries import inventory_impact_function_type
from fdai.core.ontology_platform.property_values import PropertyValueDomain, PropertyValueGroup
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
    OntologyFunctionType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import QueryNodeKind, SemanticOperation

NOW = datetime(2026, 8, 14, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[4]
DIGEST = "sha256:" + ("a" * 64)
_NAMED_INSTANCE_UTTERANCE = "aks-fdai-observe-lab 클러스터 상태 요약해줘"


class _ManifestProvider:
    def __init__(self, manifest: Any) -> None:
        self._manifest = manifest

    def manifest_for(self, *, principal: Principal, purpose: str):  # type: ignore[no-untyped-def]
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


class _AcceptingVerifier:
    def verify(self, _plan: object, *, manifest: object) -> None:
        assert manifest is not None


def _fixture(
    *,
    property_values: tuple[PropertyValueDomain, ...] = (),
    include_rule: bool = False,
    include_resource_type: bool = False,
    function_types: tuple[OntologyFunctionType, ...] = (),
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
    object_types = (resource, rule) if include_rule else (resource,)
    release = build_ontology_release(object_types=object_types, function_types=function_types)
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=object_types,
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


def _run(service: SemanticPlanningService, *, utterance: str = "Show matching resources"):  # type: ignore[no-untyped-def]
    return service.plan(
        utterance=utterance,
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )


def test_valid_t1_plan_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_evidence_validation_without_a_coverage_function_is_unsupported() -> None:
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

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
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

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
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

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
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
    assert outcome.frame is None
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
    node["arguments"]["arguments"] = {  # type: ignore[index]
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
