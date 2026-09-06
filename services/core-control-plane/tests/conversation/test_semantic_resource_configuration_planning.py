"""Typed configuration comparison plans are phrase-independent, bounded, and principal-verified."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.core.conversation.semantic_resource_configuration_planning import (
    RESOURCE_CONFIGURATION_OUTPUT_SHAPE,
    build_resource_configuration_frame,
    compile_resource_configuration_plan,
)
from fdai.core.ontology_platform import (
    OntologyQueryPlanVerifier,
    QueryManifest,
    build_query_manifest,
)
from fdai.core.ontology_platform.resource_configuration_queries import (
    MAX_CONFIGURATION_WINDOW_SECONDS,
    RESOURCE_CONFIGURATION_FUNCTION_NAME,
    resource_configuration_function_type,
)
from fdai.core.ontology_platform.resource_configuration_snapshots import (
    RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME,
    resource_configuration_snapshot_function_type,
)
from fdai.shared.contracts.models import (
    CeilingRole,
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
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal, SemanticTarget

NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)


def test_typed_judgment_builds_exact_configuration_frame_without_frame_model() -> None:
    target = "narrator-gpt-5-4-mini"
    utterance = f"Compare {target} during the last hour."
    start = utterance.index(target)
    time_value = "last hour"
    time_start = utterance.index(time_value)
    result = build_resource_configuration_frame(
        judgment=SemanticJudgmentProposal(
            primary_intent="query.resource_configuration_changes",
            targets=(
                SemanticTarget(
                    kind="resource",
                    value=target,
                    source_start=start,
                    source_end=start + len(target),
                ),
                SemanticTarget(
                    kind="time_range",
                    value=time_value,
                    canonical_value="duration.PT1H",
                    source_start=time_start,
                    source_end=time_start + len(time_value),
                ),
            ),
            requested_facets=("last_hour", "capacity_units", "authoritative_tpm"),
            confidence=0.98,
            ambiguous=False,
            action_posture="advise_only",
            action_subject="none",
            authority="candidate_only",
            execution_authority=False,
        ),
        utterance=utterance,
        context=(),
        descriptors=tuple(_manifest().descriptors),
    )

    assert result is not None
    _proposal, frame = result
    assert frame.operation == "compare"
    assert frame.subject_constraints == ("Resource", f"Resource.name={target}")
    assert frame.temporal_scope == {"lookback_seconds": 3_600}
    assert frame.output_shape == RESOURCE_CONFIGURATION_OUTPUT_SHAPE


def test_future_hour_target_does_not_build_past_configuration_frame() -> None:
    utterance = "Compare deployment-a one hour from now."
    result = build_resource_configuration_frame(
        judgment=SemanticJudgmentProposal(
            primary_intent="query.resource_configuration_changes",
            targets=(
                SemanticTarget(
                    kind="resource",
                    value="deployment-a",
                    source_start=8,
                    source_end=20,
                ),
                SemanticTarget(
                    kind="time_range",
                    value="one hour",
                    canonical_value="duration.PT1H",
                    source_start=21,
                    source_end=29,
                ),
            ),
            requested_facets=("configuration_changes",),
            confidence=0.98,
            ambiguous=False,
            action_posture="advise_only",
            action_subject="none",
            authority="candidate_only",
            execution_authority=False,
        ),
        utterance=utterance,
        context=(),
        descriptors=tuple(_manifest().descriptors),
    )

    assert result is None


def test_last_hour_facet_without_time_target_does_not_build_configuration_frame() -> None:
    utterance = "Compare deployment-a one hour from now."
    result = build_resource_configuration_frame(
        judgment=SemanticJudgmentProposal(
            primary_intent="query.resource_configuration_changes",
            targets=(
                SemanticTarget(
                    kind="resource",
                    value="deployment-a",
                    source_start=8,
                    source_end=20,
                ),
            ),
            requested_facets=("last_hour", "configuration_changes"),
            confidence=0.98,
            ambiguous=False,
            action_posture="advise_only",
            action_subject="none",
            authority="candidate_only",
            execution_authority=False,
        ),
        utterance=utterance,
        context=(),
        descriptors=tuple(_manifest().descriptors),
    )

    assert result is None


def _manifest(*, bound: bool = True, snapshot_bound: bool = True) -> QueryManifest:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            key: PropertyDecl(type=PropertyType.STRING, required=key == "id")
            for key in ("id", "name", "type", "parent_id")
        },
    )
    declaration = resource_configuration_function_type()
    snapshot = resource_configuration_snapshot_function_type()
    release = build_ontology_release(
        object_types=(resource,),
        function_types=(declaration, snapshot),
    )
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest="sha256:" + "a" * 64,
        object_types=(resource,),
        functions=(declaration, snapshot),
        bound_function_names=(
            ((declaration.name,) if bound else ()) + ((snapshot.name,) if snapshot_bound else ())
        ),
    )


def _frame(
    utterance: str = "Compare the selected resources.",
    *,
    scope: dict[str, Any] | None = None,
    constraints: tuple[str, ...] = ("Resource", "Resource.type=llm-model-deployment"),
    operation: str = "compare",
    measures: tuple[str, ...] = (),
) -> SemanticProblemFrame:
    temporal = scope if scope is not None else {"lookback_seconds": 3600}
    body: dict[str, Any] = {
        "schema_version": "1.0.0",
        "operation": operation,
        "subject_constraints": constraints,
        "measure_concepts": measures,
        "temporal_scope": temporal,
        "output_shape": RESOURCE_CONFIGURATION_OUTPUT_SHAPE,
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


def _verifier() -> OntologyQueryPlanVerifier:
    return OntologyQueryPlanVerifier(
        available_kinds=(
            QueryNodeKind.OBJECT_SET,
            QueryNodeKind.FUNCTION,
        ),
    )


def _compile(frame: SemanticProblemFrame) -> OntologyQueryPlan | None:
    return compile_resource_configuration_plan(
        frame=frame,
        manifest=_manifest(),
        verifier=_verifier(),
        evaluation_time=NOW,
        purpose="operations-review",
    )


@pytest.mark.parametrize(
    "utterance",
    [
        "Compare model deployment configuration against one hour ago.",
        "What changed in the selected deployment's capacity allocation?",
        "선택한 모델 배포의 용량 설정이 한 시간 전과 어떻게 달라졌나요?",
        "Show the earlier and later deployment settings without claiming a runtime effect.",
    ],
)
def test_paraphrases_with_same_typed_frame_produce_same_bounded_read_nodes(utterance: str) -> None:
    plan = _compile(_frame(utterance))
    reference = _compile(_frame())
    assert plan is not None and reference is not None
    assert plan.nodes == reference.nodes
    assert plan.problem_frame_digest != reference.problem_frame_digest
    assert plan.execution_authority is False
    assert [node.kind for node in plan.nodes] == [
        QueryNodeKind.OBJECT_SET,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.FUNCTION,
        QueryNodeKind.FUNCTION,
    ]
    scope = plan.nodes[0].arguments["definition"]
    assert scope["limit"] == 16
    assert scope["include_relationships"] is False
    assert scope["predicates"] == [
        {
            "property": "type",
            "operator": "equals",
            "equals": "llm-model-deployment",
        }
    ]
    assert plan.nodes[1].arguments["arguments"] == {
        "as_of": "2026-09-06T11:00:00+00:00",
        "known_at": NOW.isoformat(),
    }
    for node in plan.nodes[1:3]:
        assert node.arguments["function_name"] == RESOURCE_CONFIGURATION_SNAPSHOT_FUNCTION_NAME
        assert node.depends_on == ("configuration-current-scope",)
        assert node.arguments["dependency_arguments"] == {
            "configuration-current-scope": "query_result"
        }
        assert node.output_kind == "resource.configuration_snapshot"
    comparison = plan.nodes[-1]
    assert comparison.arguments["function_name"] == RESOURCE_CONFIGURATION_FUNCTION_NAME
    assert comparison.arguments["dependency_arguments"] == {
        "configuration-current-scope": "query_result",
        "configuration-before": "before_snapshot",
        "configuration-after": "after_snapshot",
    }
    assert plan.output_node_ids == ("configuration-compare",)


def test_generic_exact_resource_constraints_need_no_model_or_phrase_branch() -> None:
    plan = _compile(
        _frame(
            constraints=("Resource", "Resource.name=example-resource"),
            scope={
                "before_as_of": "2026-09-05T12:00:00Z",
                "after_as_of": "2026-09-06T00:00:00Z",
            },
        )
    )
    assert plan is not None
    assert plan.nodes[0].arguments["definition"]["predicates"] == [
        {
            "property": "name",
            "operator": "equals",
            "equals": "example-resource",
        }
    ]
    assert plan.nodes[0].arguments["definition"]["as_of"] == "2026-09-06T12:00:00Z"
    assert plan.nodes[2].arguments["arguments"]["as_of"] == "2026-09-06T00:00:00+00:00"


@pytest.mark.parametrize(
    "scope",
    [
        {},
        {"lookback_seconds": True},
        {"lookback_seconds": 299},
        {"lookback_seconds": MAX_CONFIGURATION_WINDOW_SECONDS + 1},
        {"before_as_of": "2026-09-06T12:00:00Z", "after_as_of": "2026-09-05T12:00:00Z"},
        {"before_as_of": "2026-09-05T12:00:00", "after_as_of": NOW.isoformat()},
        {"before_as_of": "2026-09-05T12:00:00Z", "after_as_of": "2026-09-07T00:00:00Z"},
        {"lookback_seconds": 3600, "known_at": "2026-09-07T00:00:00Z"},
    ],
)
def test_ambiguous_unbounded_or_future_time_is_not_compiled(scope: dict[str, Any]) -> None:
    assert _compile(_frame(scope=scope)) is None


@pytest.mark.parametrize(
    "constraints",
    [
        ("the model deployment",),
        ("Resource", "example-resource"),
        ("Resource", "Resource.secret=example"),
        ("Resource", "Resource.name="),
        ("Resource", "Resource.name=a", "Resource.name=b"),
        ("Resource", "Resource.id=a", "Resource.name=b"),
    ],
)
def test_untyped_or_conflicting_constraints_never_broaden_scope(
    constraints: tuple[str, ...],
) -> None:
    assert _compile(_frame(constraints=constraints)) is None


def test_metric_or_action_request_is_not_silently_replaced_by_config_evidence() -> None:
    assert _compile(_frame(measures=("model.response.429.count",))) is None
    assert _compile(_frame(operation="action_draft")) is None


def test_missing_history_or_function_binding_stays_unavailable() -> None:
    assert (
        compile_resource_configuration_plan(
            frame=_frame(),
            manifest=_manifest(snapshot_bound=False),
            verifier=_verifier(),
            evaluation_time=NOW,
            purpose="operations-review",
        )
        is None
    )
    assert (
        compile_resource_configuration_plan(
            frame=_frame(),
            manifest=_manifest(bound=False),
            verifier=_verifier(),
            evaluation_time=NOW,
            purpose="operations-review",
        )
        is None
    )
