"""Deterministic gateway compilation over synthetic typed requests and principal manifests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.conversation.semantic_gateway_diagnostic_planning import (
    compile_gateway_diagnostic_plan,
)
from fdai.core.ontology_platform import (
    OntologyQueryPlanVerifier,
    QueryManifest,
    build_query_manifest,
)
from fdai.core.ontology_platform.gateway_diagnostics import (
    GATEWAY_DIAGNOSTIC_FUNCTION_NAME,
    GATEWAY_DIAGNOSTIC_OUTPUT_SHAPE,
    gateway_diagnostic_function_type,
)
from fdai.core.ontology_platform.resource_configuration_queries import (
    RESOURCE_CONFIGURATION_FUNCTION_NAME,
    resource_configuration_function_type,
)
from fdai.core.ontology_platform.resource_configuration_snapshots import (
    RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
    resource_configuration_snapshot_function_type,
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
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)

NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)


def _manifest(
    *,
    gateway_bound: bool = True,
    configuration_bound: bool = False,
    routes: bool = True,
    type_readable: bool = True,
) -> QueryManifest:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "name": PropertyDecl(type=PropertyType.STRING),
            "type": PropertyDecl(
                type=PropertyType.STRING,
                access_scope=CeilingRole.READER if type_readable else CeilingRole.OWNER,
            ),
        },
    )
    link = OntologyLinkType(
        schema_version="1.0.0",
        name="routes_to",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
        is_transitive=False,
        forward_role="routes_to",
        reverse_role="receives_routes_from",
    )
    functions = (
        gateway_diagnostic_function_type(),
        resource_configuration_function_type(),
        resource_configuration_snapshot_function_type(),
    )
    links = (link,) if routes else ()
    release = build_ontology_release(
        object_types=(resource,),
        link_types=links,
        function_types=functions,
    )
    bound = ((GATEWAY_DIAGNOSTIC_FUNCTION_NAME,) if gateway_bound else ()) + (
        (RESOURCE_CONFIGURATION_FUNCTION_NAME, RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME)
        if configuration_bound
        else ()
    )
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=(resource,),
        link_types=links,
        functions=functions,
        bound_function_names=bound,
    )


def _frame(
    *,
    utterance: str = "Compare example-gateway and its observed backends.",
    constraints: tuple[str, ...] = ("Resource", "Resource.name=example-gateway"),
    scope: dict[str, Any] | None = None,
    operation: str = "compare",
    measures: tuple[str, ...] = (),
    shape: str = GATEWAY_DIAGNOSTIC_OUTPUT_SHAPE,
) -> SemanticProblemFrame:
    temporal = scope or {}
    body = {
        "schema_version": "1.0.0",
        "operation": operation,
        "subject_constraints": constraints,
        "measure_concepts": measures,
        "temporal_scope": temporal,
        "output_shape": shape,
        "evidence_requirements": (),
        "unresolved_terms": (),
        "input_digest": content_digest({"utterance": utterance}),
        "authority": "candidate_only",
        "execution_authority": False,
    }
    return SemanticProblemFrame(
        **{key: value for key, value in body.items() if key != "temporal_scope"},
        temporal_scope_json=canonical_json(temporal),
        frame_digest=content_digest(body),
    )


def _compile(
    frame: SemanticProblemFrame,
    *,
    manifest: QueryManifest | None = None,
    include_configuration: bool = True,
) -> OntologyQueryPlan | None:
    return compile_gateway_diagnostic_plan(
        frame=frame,
        manifest=manifest or _manifest(),
        verifier=OntologyQueryPlanVerifier(
            available_kinds=(
                QueryNodeKind.OBJECT_SET,
                QueryNodeKind.TYPED_PATH,
                QueryNodeKind.FUNCTION,
            )
        ),
        evaluation_time=NOW,
        purpose="operations-review",
        include_configuration=include_configuration,
    )


@pytest.mark.parametrize(
    "utterance",
    [
        "Compare the gateway's measured delay with its recorded backend evidence.",
        "Show gateway errors alongside the same baseline window for its backends.",
        "게이트웨이 지연과 연결된 백엔드의 지표를 같은 시간대로 비교해 주세요.",
        "오류가 어디서 관측됐는지 확인하되 원인으로 단정하지 마세요.",
    ],
)
def test_gateway_plan_is_typed_exact_scoped_and_phrase_independent(utterance: str) -> None:
    plan = _compile(_frame(utterance=utterance))
    assert plan is not None and plan.execution_authority is False
    assert len(plan.nodes) == 3
    target, backends, diagnostic = plan.nodes
    definition = target.arguments["definition"]
    assert definition["selector"] == {"kind": "object_type", "name": "Resource"}
    assert definition["limit"] == 2
    assert len(definition["predicates"]) == 1
    assert definition["predicates"][0]["property"] == "name"
    assert definition["predicates"][0]["equals"] == "example-gateway"
    assert backends.kind is QueryNodeKind.TYPED_PATH
    assert backends.depends_on == (target.node_id,)
    assert backends.arguments["steps"] == [
        {
            "link_type": "routes_to",
            "direction": "outgoing",
            "max_hops": 1,
            "selector": {"kind": "object_type", "name": "Resource"},
        }
    ]
    assert backends.arguments["limit"] == 6
    assert diagnostic.arguments["function_name"] == GATEWAY_DIAGNOSTIC_FUNCTION_NAME
    assert diagnostic.arguments["dependency_arguments"] == {
        target.node_id: "query_result",
        backends.node_id: "backend_query_result",
    }
    windows = diagnostic.arguments["arguments"]
    assert windows["current_end"] == NOW.isoformat()
    assert windows["current_start"] == windows["baseline_end"]
    assert windows["baseline_start"] == (NOW - timedelta(minutes=30)).isoformat()
    assert plan.output_node_ids == (diagnostic.node_id,)


@pytest.mark.parametrize(
    "constraints",
    [
        ("Resource",),
        ("Resource", "Resource.type=network.application-gateway"),
        ("Resource", "Resource.name=example-a", "Resource.name=example-b"),
        ("Resource", "Resource.name=example-a", "Resource.parent_id=example-group"),
        ("Resource", "Resource.name="),
        ("Resource", "example-gateway"),
    ],
)
def test_gateway_compiler_never_drops_non_exact_or_additional_scope(
    constraints: tuple[str, ...],
) -> None:
    assert _compile(_frame(constraints=constraints)) is None


@pytest.mark.parametrize(
    "scope",
    [
        {"window_seconds": True},
        {"window_seconds": 0},
        {"window_seconds": 86_401},
        {"window_seconds": 900, "unrecognized": 1},
        {
            "baseline_start": "2026-09-06T10:00:00",
            "baseline_end": "2026-09-06T10:15:00",
            "current_start": "2026-09-06T10:15:00",
            "current_end": "2026-09-06T10:30:00",
        },
        {
            "baseline_start": "2026-09-06T11:00:00Z",
            "baseline_end": "2026-09-06T11:15:00Z",
            "current_start": "2026-09-06T11:10:00Z",
            "current_end": "2026-09-06T11:25:00Z",
        },
        {
            "baseline_start": "2026-09-06T11:00:00Z",
            "baseline_end": "2026-09-06T11:15:00Z",
            "current_start": "2026-09-06T11:15:00Z",
            "current_end": "2026-09-06T11:45:00Z",
        },
        {
            "baseline_start": "2026-09-06T12:00:00Z",
            "baseline_end": "2026-09-06T12:15:00Z",
            "current_start": "2026-09-06T12:15:00Z",
            "current_end": "2026-09-06T12:30:00Z",
        },
    ],
)
def test_gateway_compiler_rejects_unbounded_or_non_comparable_windows(
    scope: dict[str, Any],
) -> None:
    assert _compile(_frame(scope=scope)) is None


@pytest.mark.parametrize(
    "manifest_options",
    [
        {"gateway_bound": False},
        {"routes": False},
        {"type_readable": False},
    ],
)
def test_gateway_compiler_requires_readable_capabilities(
    manifest_options: dict[str, bool],
) -> None:
    assert _compile(_frame(), manifest=_manifest(**manifest_options)) is None


@pytest.mark.parametrize(
    "frame_options",
    [
        {"operation": "action_draft"},
        {"shape": "resource_list"},
        {"measures": ("unreviewed.metric",)},
    ],
)
def test_gateway_compiler_does_not_reinterpret_mutation_or_unrelated_frames(
    frame_options: dict[str, Any],
) -> None:
    assert _compile(_frame(**frame_options)) is None


def test_gateway_configuration_is_independent_scoped_history_not_global_topology() -> None:
    plan = _compile(_frame(), manifest=_manifest(configuration_bound=True))
    assert plan is not None and len(plan.nodes) == 9
    diagnostic, before, after, comparison = plan.nodes[2:6]
    backend_before, backend_after, backend_comparison = plan.nodes[6:]
    windows = diagnostic.arguments["arguments"]
    assert before.arguments["function_name"] == RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME
    assert before.arguments["arguments"]["as_of"] == windows["baseline_end"]
    assert after.arguments["arguments"]["as_of"] == windows["current_end"]
    assert before.arguments["arguments"]["known_at"] == after.arguments["arguments"]["known_at"]
    assert before.depends_on == after.depends_on == ("gateway-target",)
    assert comparison.arguments["function_name"] == RESOURCE_CONFIGURATION_FUNCTION_NAME
    assert backend_before.depends_on == backend_after.depends_on == ("gateway-backends",)
    assert backend_before.arguments["arguments"]["as_of"] == windows["baseline_end"]
    assert backend_after.arguments["arguments"]["as_of"] == windows["current_end"]
    assert plan.output_node_ids == (
        diagnostic.node_id,
        comparison.node_id,
        backend_comparison.node_id,
    )
    assert all(node.kind is not QueryNodeKind.TOPOLOGY_AT for node in plan.nodes)
    assert all("query_result" not in node.arguments.get("arguments", {}) for node in plan.nodes)


def test_gateway_configuration_can_be_explicitly_omitted() -> None:
    plan = _compile(
        _frame(),
        manifest=_manifest(configuration_bound=True),
        include_configuration=False,
    )
    assert plan is not None and len(plan.nodes) == 3


@pytest.mark.parametrize(
    "field,value,property_name,expected_value,limit",
    [
        ("id", "example-backend", "id", "example-backend", 2),
        ("name", "example-deployment", "name", "example-deployment", 2),
        ("model_name", "example-model", "type", "llm-model-deployment", 17),
    ],
)
def test_gateway_requested_backend_uses_an_additional_bounded_authorized_scope(
    field: str,
    value: str,
    property_name: str,
    expected_value: str,
    limit: int,
) -> None:
    plan = _compile(
        _frame(
            constraints=("Resource", "Resource.name=example-gateway", f"Backend.{field}={value}"),
        )
    )
    assert plan is not None and len(plan.nodes) == 4
    root, observed, requested, diagnostic = plan.nodes
    assert root.arguments["definition"]["predicates"][0]["equals"] == "example-gateway"
    assert observed.kind is QueryNodeKind.TYPED_PATH
    assert requested.kind is QueryNodeKind.OBJECT_SET
    definition = requested.arguments["definition"]
    assert definition["limit"] == limit
    assert definition["include_relationships"] is False
    assert definition["as_of"] == root.arguments["definition"]["as_of"]
    assert definition["purpose"] == root.arguments["definition"]["purpose"]
    assert len(definition["predicates"]) == 1
    assert definition["predicates"][0]["property"] == property_name
    assert definition["predicates"][0]["equals"] == expected_value
    assert diagnostic.arguments["arguments"]["requested_backend_filter"] == {
        "field": field,
        "value": value,
    }
    assert diagnostic.arguments["dependency_arguments"][requested.node_id] == (
        "requested_backend_query_result"
    )
    assert "requested_backend_query_result" not in diagnostic.arguments["arguments"]
    assert plan.execution_authority is False


@pytest.mark.parametrize(
    "backend",
    [
        "Backend.type=llm-model-deployment",
        "Backend.model_name=",
    ],
)
def test_gateway_requested_backend_rejects_unsupported_or_unbounded_identity(backend: str) -> None:
    assert (
        _compile(
            _frame(
                constraints=("Resource", "Resource.id=example-gateway", backend),
            )
        )
        is None
    )


@pytest.mark.parametrize("backend", ["Backend.name= ", "Backend.model_name=" + "x" * 257])
def test_invalid_backend_constraint_is_rejected_at_frame_boundary(backend: str) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _frame(constraints=("Resource", "Resource.id=example-gateway", backend))


def test_gateway_requested_backend_cannot_drop_a_second_requested_identity() -> None:
    assert (
        _compile(
            _frame(
                constraints=(
                    "Resource",
                    "Resource.id=example-gateway",
                    "Backend.name=example-a",
                    "Backend.name=example-b",
                )
            )
        )
        is None
    )


def test_gateway_filtered_request_does_not_disclose_unfiltered_backend_configurations() -> None:
    plan = _compile(
        _frame(
            constraints=(
                "Resource",
                "Resource.name=example-gateway",
                "Backend.model_name=example-model",
            )
        ),
        manifest=_manifest(configuration_bound=True),
    )
    assert plan is not None and len(plan.nodes) == 7
    assert plan.output_node_ids == ("gateway-diagnostics", "gateway-configuration-changes")
    for node in plan.nodes:
        if node.arguments.get("function_name") == RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME:
            assert node.depends_on == ("gateway-target",)
